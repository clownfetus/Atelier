"""Keep core release checks mandatory; broaden browser coverage for other changes."""
import ast
from pathlib import Path
import subprocess

ROOT = Path(__file__).resolve().parents[1]


def omit_region(text, start, end):
    first = text.find(start)
    last = text.find(end, first + len(start)) if first >= 0 else -1
    if first < 0 or last < 0:
        raise ValueError('Unknown source layout; run the full browser suite.')
    return text[:first] + text[last:]


def gui_without_updates(name, text):
    if name == 'gui/app.js':
        text = omit_region(text, '// ── update check', '// ── project picker')
        return omit_region(text, '// ── initial load', '// ── Shader Studio')
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
    for node in module.body:
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)) and (node.name.startswith('api_update_') or node.name == '_do_update_download'):
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
        for name in changed:
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
    except (OSError, ValueError, SyntaxError, subprocess.SubprocessError):
        return 'full'
    return 'updates'


def select(context):
    def before(name):
        return subprocess.check_output(['git', 'show', context['previous_tag'] + ':' + name], cwd=ROOT, text=True, encoding='utf-8')
    return browser_mode(context['changed'], before, lambda name: (ROOT / name).read_text(encoding='utf-8'))
