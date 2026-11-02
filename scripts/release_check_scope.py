"""Keep core release checks mandatory; broaden browser coverage for other changes."""
import ast
from pathlib import Path
import re
import subprocess

ROOT = Path(__file__).resolve().parents[1]

# Only surfaces with explicit workflow coverage get the faster path. Shared
# palettes, renderer internals, backend, dependencies and unknown files stay full.
UI_SUITES = {
    'gui/viewport.css': ('viewport', 'workspace', 'assembly', 'model-export', 'showcase'),
    'gui/roster.js': ('identity', 'find', 'library', 'viewport'),
    'gui/roster.css': ('identity', 'find', 'library'),
    'gui/workspace.js': ('workspace', 'assembly', 'viewport'),
    'gui/workspace.css': ('workspace', 'assembly'),
    'gui/workspace-dock.js': ('workspace',),
    'gui/library-tools.js': ('library', 'find', 'material-bulk'),
    'gui/library-tools.css': ('library', 'find', 'material-bulk'),
    'gui/library-pins.js': ('library', 'identity'),
    'gui/library-pins.css': ('library', 'identity'),
    'gui/material-workflow.css': ('viewport', 'material-replacement', 'material-bulk'),
    'tests/workspace_checks.py': ('workspace',),
    'tests/home_layout_checks.py': ('identity',),
    'tests/app_colour_home_checks.py': ('identity',),
    'tests/app_colour_identity_checks.py': ('identity',),
    'tests/find_checks.py': ('find',),
    'tests/library_workflow_checks.py': ('library',),
    'tests/library_pins_checks.py': ('library',),
    'tests/assembly_browser_checks.py': ('assembly',),
    'tests/viewport_inspection_checks.py': ('viewport',),
    'tests/model_studio_export_browser_checks.py': ('model-export',),
}
SHARED_UI_SUITES = {
    'gui/app.js': ('library', 'find', 'identity', 'material-bulk'),
    'gui/viewport.js': ('viewport', 'workspace', 'assembly'),
}


def outside_ui(name, text):
    if name == 'gui/app.js':
        text = omit_region(text, 'function buildGrid(', 'function _editedDots(')
        return text.replace('let _homeCategoriesExpanded=false;\n', '')
    if name == 'gui/viewport.js':
        text = omit_region(text, 'function pickMaterial(', 'async function openConnectedEditor(')
        return omit_region(text, 'function buildMaterialInspector(', 'function colorField(')
    raise ValueError('Unknown shared UI surface.')


def omit_region(text, start, end):
    first = text.find(start)
    last = text.find(end, first + len(start)) if first >= 0 else -1
    if first < 0 or last < 0 or text.count(start) != 1 or text.count(end) != 1:
        raise ValueError('Unknown source layout; run the full browser suite.')
    return text[:first] + text[last:]


def gui_without_updates(name, text):
    if name == 'gui/app.js':
        text = omit_region(text, '// ── update check', '// ── project picker')
        # Normalize only the updater's startup acknowledgement. Other init()
        # changes still require the complete browser coverage.
        text = text.replace('''  await checkProject(() => {
    checkUpdate(update);
    if (document.getElementById("project-overlay").classList.contains("active")) {
      acknowledgeUpdateStartup();
    }
  });''', '  await checkProject(() => checkUpdate(update));')
        return re.sub(r'(?m)^[ \t]*acknowledgeUpdateStartup\(\);\n', '', text)
    if name == 'gui/index.html':
        return omit_region(text, '<!-- ── update check / download', '<!-- ── release notes')
    if name == 'window.py':
        marker = 'from pathlib import Path\nfrom atelier.updates import recover_interrupted'
        if marker in text:
            text = omit_region(text, marker, 'if sys.platform.startswith("linux")')
        return text
    raise ValueError('Unrecognized shared interface file.')


def routes_without_updates(text):
    module = ast.parse(text)
    body = []
    globals_ = {'_updater', '_update_cache', '_update_state', '_update_state_lock', '_update_progress'}
    functions = {'api_update_check', 'api_update_open_release', 'api_update_download',
                 'api_update_status', 'api_update_progress', 'api_update_apply',
                 'api_update_ready', 'api_update_ready_required', '_do_update_download'}
    for node in module.body:
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)) and node.name in functions:
            continue
        if isinstance(node, ast.Assign) and all(isinstance(target, ast.Name) and target.id in globals_ for target in node.targets):
            continue
        if isinstance(node, ast.ImportFrom) and node.module == 'atelier':
            node.names = [name for name in node.names if name.name != 'updates']
            if not node.names:
                continue
        body.append(node)
    return ast.dump(ast.Module(body=body, type_ignores=[]))


def browser_mode(changed, before, after):
    if not changed:
        return 'full'
    try:
        ui = False
        for name in changed:
            if name in UI_SUITES:
                ui = True
                continue
            if name in SHARED_UI_SUITES:
                try:
                    if outside_ui(name, before(name)) == outside_ui(name, after(name)):
                        ui = True
                        continue
                except ValueError:
                    pass
            if name in {'gui/app.js', 'gui/index.html', 'window.py'}:
                if gui_without_updates(name, before(name)) != gui_without_updates(name, after(name)):
                    return 'full'
            elif name.startswith('gui/') or name in {'main.py', 'io_lib.py', 'server.py'}:
                return 'full'
            elif name == 'atelier/web/routes.py':
                if routes_without_updates(before(name)) != routes_without_updates(after(name)):
                    return 'full'
            elif name.startswith('atelier/') and name.endswith('.py') and name not in {
                    'atelier/updates.py', 'atelier/update_protocol.py', 'atelier/update_helper.py'}:
                return 'full'
            elif name.startswith(('scripts/', '.github/', 'packaging/', 'native/', 'toolchain/', 'requirements')):
                return 'full'
            elif name.startswith('tests/') and not Path(name).name.startswith('test_'):
                return 'full'
            elif name not in {'version', 'CHANGELOG.md', 'LICENSE', '.gitignore', 'update_keys.json',
                              'atelier/updates.py', 'atelier/update_protocol.py', 'atelier/update_helper.py',
                              'atelier/web/routes.py'} and not (name.endswith('.md') or name.startswith(('docs/', 'images/', 'tests/'))):
                return 'full'
    except (OSError, ValueError, SyntaxError, subprocess.SubprocessError):
        return 'full'
    return 'ui' if ui else 'updates'


def select(context):
    def before(name):
        return subprocess.check_output(['git', 'show', context['previous_tag'] + ':' + name], cwd=ROOT, text=True, encoding='utf-8')
    return browser_mode(context['changed'], before, lambda name: (ROOT / name).read_text(encoding='utf-8'))
