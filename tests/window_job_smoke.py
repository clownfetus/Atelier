"""Hidden real WebView2 close: cancel a child process and persist its outcome."""
import argparse
import json
import os
from pathlib import Path
import socket
import subprocess
import sys
import time

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))


def child(report):
    os.environ['ATELIER_DATA_DIR']=str(report/'data')
    os.environ['ATELIER_PORT']=str(json.loads((report/'port.json').read_text())['port'])
    from atelier import config as C, jobs as J, hostos
    from atelier.web import routes as R
    R._get_latest_usmap_from_github=lambda:None
    hostos.notify=lambda *_args:None
    hostos.focus_window=lambda *_args:None
    project=Path(C.project_dir('Shutdown check'));project.mkdir(parents=True)
    C.set_active_project('Shutdown check')
    import webview
    import window
    original_create,original_start=webview.create_window,webview.start
    created=[]
    def create(*args,**kwargs):
        kwargs['hidden']=True
        result=original_create(*args,**kwargs);created.append(result);return result
    webview.create_window=create
    def probe():
        marker=report/'native-child-started'
        def work(job):
            J.run_process([sys.executable,'-c',
                'from pathlib import Path;import time;Path('+repr(str(marker))+').write_text("ready");time.sleep(30)'],
                capture_output=True,text=True)
            return {'ok':True}
        record=J.manager().submit('export','Desktop shutdown check',str(project),'Shutdown check',work)
        deadline=time.monotonic()+5
        while not marker.exists() and time.monotonic()<deadline:time.sleep(.02)
        (report/'job-id.json').write_text(json.dumps({'id':record['id'],'started':marker.exists()}))
        created[0].destroy()
    def start(*args,**kwargs):
        return original_start(probe,debug=False,private_mode=True)
    webview.start=start
    window.main()


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--report-dir',type=Path,required=True)
    parser.add_argument('--child',action='store_true')
    args=parser.parse_args();report=args.report_dir.resolve()
    if args.child:
        child(report);return
    if report.exists():parser.error('Use a fresh report directory')
    report.mkdir(parents=True)
    with socket.socket() as listener:
        listener.bind(('127.0.0.1',0));port=listener.getsockname()[1]
    (report/'port.json').write_text(json.dumps({'port':port}))
    started=time.monotonic()
    proc=subprocess.run([sys.executable,'-u','-B',str(Path(__file__).resolve()),'--child','--report-dir',str(report)],
                         capture_output=True,text=True,encoding='utf-8',errors='replace',timeout=35)
    (report/'desktop.log').write_text(proc.stdout+proc.stderr,encoding='utf-8')
    assert proc.returncode==0,(proc.returncode,(proc.stdout+proc.stderr)[-2000:])
    job=json.loads((report/'job-id.json').read_text())
    assert job['started'],'Owned child did not start'
    record=json.loads((report/'data'/'_jobs'/(job['id']+'.json')).read_text())
    assert record['state']=='cancelled',record
    result=dict(ok=True,state=record['state'],elapsed_seconds=round(time.monotonic()-started,2),
                checks=['real hidden WebView2 closing event drained the managed job',
                        'owned child cancelled and terminal status persisted before process exit'])
    (report/'results.json').write_text(json.dumps(result,indent=2))
    print('PASS '+'; '.join(result['checks']))


if __name__=='__main__':main()
