"""Real button -> jobs -> built-in blending -> project files, with native decode fixtures."""
import json
from pathlib import Path
import shutil
import tempfile
from unittest.mock import patch

from PIL import Image


def run_s_maps_checks(page, context, url, report, checks):
    from atelier import config as C, s_maps as S
    previous_project = C.get_active_project()
    name = 'S maps browser'
    root = Path(C.PROJECTS_ROOT, name); root.mkdir(exist_ok=True)
    folder = 'Characters/Fixture/Skin/Textures/'
    def image(stem, color, size=(16, 12)):
        gr = folder + stem; path = Path(C.project_base(gr, str(root)) + '.png')
        path.parent.mkdir(parents=True, exist_ok=True); Image.new('RGBA', size, color).save(path)
        return gr, path
    d, d_path = image('T_Body_D', '#e03020')
    missing, _ = image('T_Eyes_D', '#2266cc')
    s = folder + 'T_Body_S'; original_d = d_path.read_bytes()
    errors = []
    tab = context.new_page(); tab.on('pageerror', lambda error: errors.append(str(error)))
    def browse(route):
        items = [dict(type='asset', file_type='texture', game_rel=folder + path.stem,
                      name=path.stem, imported=True) for path in sorted(d_path.parent.glob('*.png'))]
        route.fulfill(json=items)
    def prefetch(route):
        route.fulfill(json={'ok':True, 'cached':route.request.post_data_json['game_rels'], 'pending':[], 'failed':[]})
    try:
        with tempfile.TemporaryDirectory(prefix='atelier-s-map-decode-') as scratch:
            native = Path(scratch, 'original.png'); Image.new('RGBA', (5, 7), (90, 90, 90, 47)).save(native)
            with patch.object(S, 'ensure_index', lambda: [(s + '.uasset',)]), \
                 patch.object(S.T, 'ensure_work_base', return_value='fixture-game-source'), \
                 patch.object(S.T, 'decode_png', side_effect=lambda base, cb: shutil.copy2(native, base + '.png')):
                tab.route('**/api/browse?*', browse)
                tab.route('**/api/prefetch_thumbs', prefetch)
                tab.goto(url); tab.wait_for_function("window.atelierProject && !document.querySelector('.overlay.active')")
                tab.evaluate("async name => { await _selectProject(name); document.documentElement.dataset.theme = 'dark'; }", name)
                button = tab.locator('#process-s-maps')
                assert button.is_enabled()
                # Export selection has no effect on the all-edited-D processing scope.
                tab.evaluate('() => { Object.values(sidebarData).forEach(i => i.selected = false); renderSidebar(); }')
                button.click()
                tab.wait_for_function("s => Object.values(sidebarData).some(i => i.game_rel === s)", arg=s)
                tab.wait_for_function("document.getElementById('process-s-maps').textContent === 'Process S maps'")
                assert not tab.locator('#s-maps-overlay').count()
                with Image.open(C.project_base(s, str(root)) + '.png') as output:
                    assert output.size == (5, 7) and output.getpixel((0, 0))[3] == 47
                assert d_path.read_bytes() == original_d
                assert native.read_bytes() == next((root / '.atelier/s-map-backups').rglob('T_Body_S.png')).read_bytes()
                tab.locator('#job-activity').click()
                tab.wait_for_function("document.querySelector('#job-overlay').textContent.includes('S maps processed')")
                assert 'T_Eyes_D' in tab.locator('#job-overlay').inner_text()
                tab.locator('#job-overlay .job-modal > button').click()
                checks.append('One click runs real S-map jobs, imports the matching game S map, retains alpha/D files and lists unmatched maps in Activity')

                first, _ = image('T_Equip_01_D', '#dd2200')
                second, _ = image('T_Equip_02_D', '#0044dd')
                shared, shared_path = image('T_Equip_S', '#777777')
                before = shared_path.read_bytes()
                tab.evaluate('async () => { await loadSidebar(); await renderGrid(); }')
                button.click(); tab.locator('#s-maps-overlay.active').wait_for()
                apply = tab.locator('#s-maps-overlay .btn.primary')
                assert apply.is_disabled() and shared_path.read_bytes() == before
                tab.locator('#s-maps-overlay select').select_option(second)
                assert apply.is_enabled()
                apply.click()
                tab.wait_for_function("!document.querySelector('#s-maps-overlay').classList.contains('active')")
                tab.wait_for_function("document.getElementById('process-s-maps').textContent === 'Process S maps'")
                records = [json.loads(path.read_text()) for path in (root / '.atelier/s-map-backups').rglob('batch.json')]
                assert any(any(row['s'] == shared and row['d'] == second for row in item['processed']) for item in records)
                assert shared_path.read_bytes() != before
                tab.wait_for_function("_gridStatus === 'ready' && document.querySelectorAll('#grid-area img').length > 0 && [...document.querySelectorAll('#grid-area img, #sidebar-list .sb-thumb img')].every(image => image.complete && image.naturalWidth > 0)")
                tab.wait_for_function("!document.querySelector('.texture-reconstruction')")
                tab.screenshot(path=str(report / 'process-s-maps-dark.png'))
                checks.append('Shared S maps require an explicit D choice; the chosen pairing is saved in the batch record and its S output appears in Edited Assets')

                button.click(); tab.locator('#s-maps-overlay.active').wait_for()
                tab.locator('#s-maps-overlay select').select_option(first)
                before = shared_path.read_bytes()
                tab.evaluate("_activeProjectName = 'Smoke B'")
                apply.click()
                assert 'Project changed' in tab.locator('.s-maps-status').inner_text()
                assert shared_path.read_bytes() == before
                tab.keyboard.press('Escape')
                tab.evaluate('() => { sidebarData = {}; renderSidebar(); }')
                assert button.is_disabled()
                checks.append('Project switches reject stale pairing dialogs and the processing button disables when no edited D maps remain')
                assert not errors, errors
    finally:
        tab.close()
        C.set_active_project(previous_project)
