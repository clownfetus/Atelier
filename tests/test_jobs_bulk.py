"""Behavioural job, recovery and bulk-save regressions; all data is disposable."""
import atexit
import copy
import io
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import threading
import time
import unittest
from unittest.mock import patch
from urllib.parse import quote
import uuid
from wsgiref.util import setup_testing_defaults

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
_data = tempfile.TemporaryDirectory(prefix="atelier-jobs-tests-")
os.environ["ATELIER_DATA_DIR"] = _data.name
from atelier import config as C, jobs as J, bulk as B, storage as S, operations as O
from atelier.handlers import curve as CV, vfx as V, material as M, texture as T
from atelier.web import routes as R


def cleanup():
    J.shutdown(5)
    R._observer.stop()
    R._observer.join()
    _data.cleanup()


atexit.register(cleanup)


def call(path, body=None, method="POST", project="A"):
    env = {}
    setup_testing_defaults(env)
    payload = json.dumps(body or {}).encode()
    env.update(REQUEST_METHOD=method, PATH_INFO=path, CONTENT_TYPE="application/json",
               CONTENT_LENGTH=str(len(payload)), HTTP_X_ATELIER_PROJECT=quote(project, safe=""),
               **{"wsgi.input": io.BytesIO(payload)})
    status = []
    response = R.app(env, lambda s, h, exc_info=None: status.append(s))
    try:
        data = json.loads(b"".join(response).decode())
    finally:
        if hasattr(response, "close"):
            response.close()
    return int(status[0].split()[0]), data


def curve():
    channels = []
    for value in (1.0, 2.0, 3.0, .4):
        keys = [{"Value": [{"Value": {"Time": t, "Value": value,
                  "InterpMode": "RCIM_Cubic", "ArriveTangent": 2.0, "LeaveTangent": -3.0,
                  "ArriveTangentWeight": .7}}]} for t in (0.0, 1.5)]
        channels.append({"Name": "FloatCurves", "Value": [{"Value": keys}]})
    return {"Exports": [{"Data": channels}], "Unrelated": "preserve"}


def mpc():
    def entry(name, value):
        return {"OriginalStructHeader": {"preserved": True}, "Value": [
            {"Name": "ParameterName", "Value": name},
            {"Name": "DefaultValue", "Value": value, "IsZero": name == "Zero"}]}
    return {"Exports": [{"Data": [
        {"Name": "ScalarParameters", "Value": [entry("Zero", 0.0), entry("Speed", 5.0)]},
        {"Name": "VectorParameters", "Value": [entry("Tint", [{"Value": dict(R=2., G=3., B=4., A=.25)}])]},
    ]}]}


class Cases(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix="atelier-job-case-")
        self.root = Path(self.temp.name).resolve()
        self.project = self.root / "projects" / "A"
        self.project.mkdir(parents=True)
        self.manager = J.JobManager(self.root / "jobs")
        self.context = C.project_context(str(self.project))
        self.context.__enter__()

    def tearDown(self):
        self.manager.shutdown(3)
        self.context.__exit__(None, None, None)
        self.temp.cleanup()

    def write(self, gr, data):
        path = Path(C.project_base(gr) + ".json")
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(data), encoding="utf-8")
        return path

    def wait(self, record):
        deadline = time.monotonic() + 5
        while time.monotonic() < deadline:
            row = self.manager.snapshot(record["id"], "A")
            if row["state"] not in J.ACTIVE:
                # The persisted terminal state precedes reservation cleanup.
                job = self.manager.live.get(record["id"])
                if job:
                    job.thread.join(2)
                return row
            time.sleep(.01)
        self.fail("Job did not finish")

    def submit(self, work, kind="export"):
        return self.manager.submit(kind, "Test job", str(self.project), "A", work)

    def test_job_keeps_its_project_and_persists_result(self):
        record = self.submit(lambda job: {"ok": True, "root": C.get_import_root()})
        result = self.wait(record)
        self.assertEqual(result["state"], "succeeded")
        self.assertEqual(result["result"]["root"], str(self.project))
        reopened = J.JobManager(self.root / "jobs")
        self.assertEqual(reopened.snapshot(record["id"], "A")["result"], result["result"])

    def test_start_claim_blocks_project_changes_and_duplicate_jobs(self):
        entered, finish = threading.Event(), threading.Event()
        def work(job):
            entered.set(); finish.wait(2); return {"ok": True}
        record = self.submit(work)
        try:
            self.assertTrue(entered.wait(1))
            with self.assertRaises(O.BusyError):
                with O.change_projects(str(self.project)):
                    pass
            with self.assertRaises(O.BusyError):
                self.submit(work)
        finally:
            finish.set()
        self.wait(record)
        with O.change_projects(str(self.project)):
            pass

    def test_cancellation_stops_owned_child_and_preserves_old_output(self):
        marker = self.root / "started"
        output = self.root / "previous.pak"
        output.write_bytes(b"previous output")
        def work(job):
            J.run_process([sys.executable, "-c", "from pathlib import Path; import time; Path(" + repr(str(marker)) + ").write_text('ready'); time.sleep(30)"],
                          capture_output=True, text=True)
            output.write_bytes(b"should never be published")
            return {"ok": True}
        record = self.submit(work)
        deadline = time.monotonic() + 3
        while not marker.exists() and time.monotonic() < deadline:
            time.sleep(.02)
        self.assertTrue(marker.exists())
        self.assertTrue(self.manager.cancel(record["id"], "A"))
        result = self.wait(record)
        self.assertEqual(result["state"], "cancelled")
        self.assertEqual(output.read_bytes(), b"previous output")

    def test_publication_cannot_be_cancelled_and_shutdown_waits(self):
        publishing, finish = threading.Event(), threading.Event()
        def work(job):
            job.begin_publication("Publishing")
            publishing.set(); finish.wait(3); return {"ok": True}
        record = self.submit(work)
        try:
            self.assertTrue(publishing.wait(1))
            self.assertFalse(self.manager.cancel(record["id"], "A"))
            self.assertFalse(self.manager.shutdown(.03))
            with self.assertRaises(O.BusyError):
                self.submit(lambda job: {"ok": True})
        finally:
            finish.set()
        self.assertEqual(self.wait(record)["state"], "succeeded")

    def test_restart_marks_unfinished_jobs_and_cleans_only_owned_workspace(self):
        job_id = str(uuid.uuid4())
        record = dict(id=job_id, project="A", state="running", kind="export", created=1, can_cancel=True)
        S.atomic_json(str(self.root / "jobs" / (job_id + ".json")), record)
        workspace = Path(self.manager.workspace(job_id)); workspace.mkdir(parents=True)
        (workspace / "private.bin").write_bytes(b"scratch")
        preserved = self.root / "jobs" / "unrelated"; preserved.mkdir()
        restarted = J.JobManager(self.root / "jobs")
        self.assertEqual(restarted.snapshot(job_id, "A")["state"], "interrupted")
        self.assertFalse(workspace.exists())
        self.assertTrue(preserved.exists())

    def test_other_project_cannot_read_or_cancel_job(self):
        record = self.submit(lambda job: {"ok": True})
        self.wait(record)
        with self.assertRaises(ValueError): self.manager.snapshot(record["id"], "B")
        with self.assertRaises(ValueError): self.manager.cancel(record["id"], "B")
        self.assertEqual(self.manager.list("B"), [])

    def test_finished_job_retains_reservation_until_cleanup_callback_finishes(self):
        entered, finish=threading.Event(),threading.Event()
        def settled():
            entered.set();finish.wait(2)
        record=self.manager.submit('export','Callback test',str(self.project),'A',lambda job:{'ok':True},settled)
        try:
            self.assertTrue(entered.wait(1))
            with self.assertRaises(O.BusyError):self.submit(lambda job:{'ok':True})
        finally:
            finish.set()
        self.wait(record)

    def test_native_timeout_releases_reservation_and_does_not_publish(self):
        def work(job):
            J.run_process([sys.executable, "-c", "import time;time.sleep(5)"], timeout=.1)
            return {"ok": True}
        record = self.submit(work)
        self.assertEqual(self.wait(record)["state"], "failed")
        with O.change_projects(str(self.project)): pass

    def test_preview_has_no_project_writes_and_apply_preserves_timing_alpha_and_tangents(self):
        path = self.write("VFX/C_Test", curve())
        before = path.read_bytes()
        preview = B.preview(["VFX/C_Test"], dict(operation="multiply", scope="rgb", factor=2))
        self.assertEqual(path.read_bytes(), before)
        self.assertEqual(preview["changed_values"], 6)
        B.apply(preview["preview_id"])
        data = json.loads(path.read_text())
        channels = CV._channels(data)
        self.assertEqual(channels["R"][1]["time"], 1.5)
        self.assertEqual(channels["R"][0]["value"], 2)
        self.assertEqual(channels["A"][0]["value"], .4)
        self.assertEqual(channels["R"][0]["arriveTangent"], 4)
        self.assertEqual(channels["R"][0]["arriveTangentWeight"], .7)
        self.assertEqual(data["Unrelated"], "preserve")

    def test_recolor_preserves_alpha_and_zeros_constant_channel_slopes(self):
        path = self.write("VFX/C_Test", curve())
        preview = B.preview(["VFX/C_Test"], dict(operation="recolor", color=[4, .3, .2]))
        B.apply(preview["preview_id"])
        channels = CV._channels(json.loads(path.read_text()))
        self.assertEqual(channels["R"][0]["value"], 4)
        self.assertEqual(channels["R"][0]["leaveTangent"], 0)
        self.assertEqual(channels["A"][0]["value"], .4)

    def test_scalar_curve_bulk_edit_finds_keys_after_default_property(self):
        channel = curve()["Exports"][0]["Data"][0]
        channel["Name"] = "FloatCurve"
        channel["Value"][0]["Name"] = "Keys"
        channel["Value"].insert(0,{"Name":"DefaultValue","Value":0.0})
        path=self.write("VFX/Curve_Scalar",{"Exports":[{"Data":[channel]}]})
        result=B.preview(["VFX/Curve_Scalar"],dict(operation="multiply",scope="all",factor=3))
        B.apply(result["preview_id"])
        self.assertEqual(CV.read_curve("VFX/Curve_Scalar")["channels"]["R"][0]["value"],3)
        self.assertEqual(json.loads(path.read_text())["Exports"][0]["Data"][0]["Value"][0]["Value"],0.0)

    def test_stale_preview_rejects_entire_batch(self):
        a, b = self.write("A/C_Test", curve()), self.write("B/C_Test", curve())
        previous = b.read_bytes()
        preview = B.preview(["A/C_Test", "B/C_Test"], dict(operation="multiply", scope="all", factor=2))
        a.write_text('{"external_edit":true}')
        with self.assertRaisesRegex(RuntimeError, "changed after preview"):
            B.apply(preview["preview_id"])
        self.assertEqual(b.read_bytes(), previous)
        self.assertEqual(json.loads(a.read_text()), {"external_edit": True})

    def test_expired_and_cross_project_previews_cannot_apply(self):
        self.write("VFX/C_Test", curve())
        result = B.preview(["VFX/C_Test"], dict(operation="multiply", factor=2))
        other = self.root / "Other"; other.mkdir()
        with C.project_context(str(other)), self.assertRaises(ValueError):
            B.apply(result["preview_id"])
        with patch.object(B.time, "monotonic", return_value=time.monotonic()+B.LIFETIME+1), self.assertRaises(ValueError):
            B.apply(result["preview_id"])

    def test_niagara_rgb_edit_keeps_opacity_scalars_and_unrelated_saved_edits(self):
        gr = "VFX/NS_Test"
        path = self.write(gr, {"metadata": "keep", "vfx_edits": [{"export_indices": [9], "stops": [[7]], "channels": 1, "sample_count": 1}]})
        groups = [dict(export_indices=[1,2], channels=4, kind="emission", stops=[[2,3,4,.2]], sample_count=1),
                  dict(export_indices=[3], channels=4, kind="opacity", stops=[[.1,.1,.1,.5]], sample_count=1),
                  dict(export_indices=[9], channels=1, kind="scalar", stops=[[7]], sample_count=1)]
        with patch.object(V, "read_vfx", return_value={"groups": groups}):
            result = B.preview([gr], dict(operation="multiply", scope="rgb", factor=2))
        B.apply(result["preview_id"])
        d = json.loads(path.read_text())
        self.assertEqual(d["metadata"], "keep")
        self.assertEqual(len(d["vfx_edits"]), 2)
        self.assertEqual(d["vfx_edits"][0]["stops"], [[7]])
        self.assertEqual(d["vfx_edits"][1]["stops"], [[4,6,8,.2]])

    def test_mpc_all_values_and_intensity_metadata_are_one_save(self):
        path = self.write("VFX/MPC_Test", mpc())
        metadata = self.project / ".atelier" / "project.json"; metadata.parent.mkdir()
        metadata.write_text(json.dumps({"deselected":["UI/T_Keep"], "asset_opts":{"VFX/MPC_Test":{"color_inten":{"Tint":3},"dye_off":True}}}))
        result = B.preview(["VFX/MPC_Test"], dict(operation="multiply", scope="all", factor=2))
        self.assertTrue(result["assets"][0]["global"])
        B.apply(result["preview_id"])
        params = V.read_mpc("VFX/MPC_Test")
        self.assertEqual(params["vectors"][0]["rgba"], [4,6,8,.5])
        self.assertEqual(params["scalars"][1]["value"], 10)
        state = json.loads(metadata.read_text())
        self.assertEqual(state["deselected"], ["UI/T_Keep"])
        self.assertEqual(state["asset_opts"]["VFX/MPC_Test"], {"dye_off":True})

    def test_invalid_input_never_modifies_project(self):
        for items, spec in [(["../C_Test"],dict(operation="multiply",factor=2)),
                            (["UI/T_Test"],dict(operation="multiply",factor=2)),
                            (["VFX/C_Test"],dict(operation="multiply",factor=float('nan'))),
                            (["VFX/C_Test"]*2,dict(operation="multiply",factor=2))]:
            with self.subTest(items=items,spec=spec), self.assertRaises(ValueError):
                B.preview(items,spec)
        self.assertEqual(list(self.project.iterdir()), [])

    def test_save_failure_restores_every_previous_byte(self):
        a, b = self.write("A/C_Test",curve()), self.write("B/C_Test",curve())
        previous = [a.read_bytes(),b.read_bytes()]
        result = B.preview(["A/C_Test","B/C_Test"],dict(operation="multiply",factor=2))
        original = S.atomic_json
        def fail_second(path,data,**kwargs):
            if os.path.normcase(str(path)) == os.path.normcase(str(b)):
                raise OSError("injected disk failure")
            return original(path,data,**kwargs)
        with patch.object(S,"atomic_json",side_effect=fail_second), self.assertRaises(OSError):
            B.apply(result["preview_id"])
        self.assertEqual([a.read_bytes(),b.read_bytes()], previous)

    def test_restart_rolls_back_partial_project_save(self):
        old = self.write("VFX/C_Test",curve()); before = old.read_bytes()
        new = self.project / "VFX/C_New.json"
        folder = self.project / ".atelier/transactions" / str(uuid.uuid4()); folder.mkdir(parents=True)
        (folder/"0.bak").write_bytes(before)
        S.atomic_json(str(folder/"journal.json"),{"state":"publishing","entries":[
            {"path":"VFX/C_Test.json","had_old":True},{"path":"VFX/C_New.json","had_old":False}]})
        old.write_text('{}');new.write_text('{}')
        S.recover_project_writes(str(self.project))
        self.assertEqual(old.read_bytes(),before);self.assertFalse(new.exists());self.assertFalse(folder.exists())

    def test_zero_scalar_change_rebuilds_only_the_owning_unversioned_header(self):
        info = {"Name":"ParameterInfo","OriginalStructHeader":{"keep":True},"Value":[{"Name":"Name","Value":"Zero"}]}
        pv = {"Name":"ParameterValue","Value":0,"IsZero":True}
        entry = {"OriginalStructHeader":{"ZeroMask":[False,True,False]},"Value":[info,pv]}
        d = {"Exports":[{"Data":[{"Name":"ScalarParameterValues","Value":[entry]}]}]}
        M._apply_mat_edits(d,{}, {"Zero":.625})
        self.assertEqual(pv["Value"],.625);self.assertFalse(pv["IsZero"])
        self.assertIsNone(entry["OriginalStructHeader"])
        self.assertEqual(info["OriginalStructHeader"],{"keep":True})

    def test_background_http_export_keeps_legacy_result_and_owner(self):
        project_root = str(self.project.parent)
        with patch.multiple(C, PROJECTS_ROOT=project_root), patch.object(R,"PROJECTS_ROOT",project_root), \
             patch.object(J,"_instance",self.manager), patch.object(R,"_install_mod_payload",return_value={"ok":True,"pak_path":"test.pak","applied":["mat test"]}):
            code,response=call('/api/install_mod',{"background":True,"mod_name":"Test","items":["VFX/C_Test"]})
            self.assertEqual(code,200);self.assertIn('job_id',response)
            result=self.wait(response["job"])
            code,response=call('/api/jobs/'+result['id'],method='GET')
            self.assertEqual(code,200);self.assertEqual(response['job']['result']['pak_path'],'test.pak')
            code,_=call('/api/jobs/'+result['id'],method='GET',project='B')
            self.assertEqual(code,400)

    def test_queued_import_can_cancel_without_waiting_for_project_writer(self):
        project_root=str(self.project.parent)
        R._job.update(running=False,done=False,results=[],error=None,owner=None)
        with patch.multiple(C,PROJECTS_ROOT=project_root),patch.object(R,'PROJECTS_ROOT',project_root),patch.object(J,'_instance',self.manager):
            with O.project_use(str(self.project),write=True):
                code,response=call('/api/import_all',{'background':True,'items':[{'game_rel':'UI/T_A','name':'T_A'}]})
                self.assertEqual(code,200)
                code,cancelled=call('/api/jobs/'+response['job_id']+'/cancel')
                self.assertEqual(code,200);self.assertTrue(cancelled['ok'])
            self.assertEqual(self.wait(response['job'])['state'],'cancelled')
            self.assertFalse(R._job['running'])
            def decode(items,root):
                from PIL import Image
                for gr in items:
                    path=Path(C.project_base(gr,root)+'.png');path.parent.mkdir(parents=True,exist_ok=True)
                    Image.new('RGBA',(1,1)).save(path)
            with patch.object(R,'extract_many'),patch.object(R,'decode_flat',side_effect=decode):
                code,retry=call('/api/import_all',{'background':True,'items':[{'game_rel':'UI/T_A','name':'T_A'}]})
                self.assertEqual(code,200)
                self.assertEqual(self.wait(retry['job'])['state'],'succeeded')

    def test_import_retry_preserves_existing_painted_png(self):
        import atelier.asset_cache as AC
        base=self.root/'base';base.with_suffix('.uasset').write_bytes(b'fixture')
        png=Path(C.project_base('UI/T_Paint')+'.png');png.parent.mkdir(parents=True);png.write_bytes(b'painted-source')
        with patch.object(AC,'cache_base',return_value=str(base)),patch.object(T,'decode_png') as decode:
            T.decode_flat(['UI/T_Paint'],str(self.project))
        self.assertEqual(png.read_bytes(),b'painted-source');decode.assert_not_called()

    def test_cancelled_decode_never_publishes_partial_project_image(self):
        import atelier.asset_cache as AC
        base=self.root/'base';base.with_suffix('.uasset').write_bytes(b'fixture')
        def interrupted(destination,source):
            Path(destination+'.png').write_bytes(b'incomplete-native-output')
            raise J.Cancelled()
        with patch.object(AC,'cache_base',return_value=str(base)),patch.object(T,'decode_png',side_effect=interrupted),self.assertRaises(J.Cancelled):
            T.decode_flat(['UI/T_New'],str(self.project))
        self.assertFalse(Path(C.project_base('UI/T_New')+'.png').exists())


if __name__ == "__main__":
    unittest.main()
