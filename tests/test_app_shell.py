"""Regressions for keyboard navigation and standalone frontend bundling."""
from pathlib import Path
import sys
import tempfile
import unittest

from playwright.sync_api import expect, sync_playwright

ROOT = Path(__file__).resolve().parents[1]
GUI = ROOT / 'gui'
sys.path.insert(0, str(ROOT))

from scripts import bundle_frontend


class AppShellKeyboardTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        playwright = sync_playwright().start()
        cls.addClassCleanup(playwright.stop)
        cls.browser = playwright.chromium.launch()
        cls.addClassCleanup(cls.browser.close)

    def setUp(self):
        self.page = self.browser.new_page()
        self.addCleanup(self.page.close)

    def script(self, filename):
        self.page.add_script_tag(path=GUI / filename)

    def test_command_palette_enter_runs_the_focused_result(self):
        self.page.set_content('''
            <style>.overlay:not(.active) { display: none }</style>
            <button id="page-library" onclick="document.body.dataset.command = 'library'">Library</button>
            <button id="page-workspace" onclick="document.body.dataset.command = 'workspace'">Workspace</button>
        ''')
        self.script('modal-trap.js')
        self.script('command-palette.js')
        self.page.locator('#page-library').focus()
        self.page.keyboard.press('Control+k')
        self.page.keyboard.press('Tab')
        self.page.keyboard.press('Tab')
        expect(self.page.get_by_role('option', name='Open Recolour costume workspace')).to_be_focused()
        self.page.keyboard.press('Enter')
        self.assertEqual(self.page.locator('body').get_attribute('data-command'), 'workspace')
        expect(self.page.locator('#page-library')).to_be_focused()

    def test_focus_search_uses_the_current_workspace(self):
        self.page.set_content('''
            <style>.overlay:not(.active) { display: none }</style>
            <body data-page="workspace">
              <input id="search-input" hidden>
              <section id="workspace-choice"><input id="workspace-search"></section>
              <div class="overlay mounted active" id="viewport-overlay"><input id="viewport-material-search"></div>
            </body>
        ''')
        self.script('command-palette.js')
        for target in ('#workspace-search', '#viewport-material-search'):
            with self.subTest(target=target):
                self.page.locator('#workspace-choice').evaluate('(choice, target) => { choice.hidden = target !== "#workspace-search" }', target)
                self.page.keyboard.press('Control+k')
                self.page.locator('#cmd-input').fill('Focus search')
                self.page.keyboard.press('Enter')
                expect(self.page.locator(target)).to_be_focused(timeout=1000)

    def test_modal_tab_wrap_skips_negative_tabindex(self):
        self.page.set_content('''
            <button id="background-start">Open</button>
            <div class="overlay active">
              <section role="dialog">
                <button tabindex="-1">Programmatic start</button>
                <button id="first">First</button>
                <button id="last">Last</button>
                <button tabindex="-1">Programmatic end</button>
              </section>
            </div>
            <button id="background-end">Outside</button>
        ''')
        self.script('modal-trap.js')
        self.page.locator('#last').focus()
        self.page.keyboard.press('Tab')
        expect(self.page.locator('#first')).to_be_focused(timeout=1000)
        self.page.keyboard.press('Shift+Tab')
        expect(self.page.locator('#last')).to_be_focused(timeout=1000)

    def test_context_menu_can_handle_tab_while_a_modal_is_open(self):
        self.page.set_content('''
            <div class="overlay active">
              <section role="dialog"><button id="menu-opener">Open menu</button></section>
            </div>
            <div id="ctx-menu" class="active"><button id="menu-option">Menu option</button></div>
            <script>
              document.getElementById('ctx-menu').addEventListener('keydown', event => {
                document.body.dataset.handledTab = String(!event.defaultPrevented);
                event.preventDefault();
                document.getElementById('menu-opener').focus();
                event.currentTarget.classList.remove('active');
              });
            </script>
        ''')
        self.script('modal-trap.js')
        self.page.locator('#menu-option').focus()
        self.page.keyboard.press('Tab')
        self.assertEqual(self.page.locator('body').get_attribute('data-handled-tab'), 'true')
        expect(self.page.locator('#menu-opener')).to_be_focused()

    def test_settings_arrow_navigation_exposes_the_labelled_section(self):
        self.page.set_content('''
            <div id="setup-overlay" class="overlay active">
              <div id="setup-dialog" role="dialog">
                <div id="settings-tabs" role="tablist" aria-label="Settings sections"></div>
                <div class="setup-body">
                  <input aria-label="Theme" data-settings-group="appearance">
                  <input aria-label="Game folder" data-settings-group="paths">
                </div>
              </div>
            </div>
        ''')
        self.page.add_style_tag(path=GUI / 'settings-tabs.css')
        self.script('settings-tabs.js')
        self.page.get_by_role('tab', name='All', exact=True).focus()
        self.page.keyboard.press('ArrowRight')
        self.page.keyboard.press('ArrowRight')
        expect(self.page.get_by_role('tab', name='Paths & keys', selected=True)).to_be_focused()
        panel = self.page.get_by_role('tabpanel', name='Paths & keys')
        expect(panel.get_by_role('textbox', name='Game folder')).to_be_visible(timeout=1000)
        expect(self.page.get_by_role('textbox', name='Theme')).to_be_hidden()


class FrontendBundleSafetyTest(unittest.TestCase):
    def setUp(self):
        self.root = Path(self.enterContext(tempfile.TemporaryDirectory()))
        self.source = self.root / 'gui'
        self.source.mkdir()
        self.index = self.source / 'index.html'
        self.index.write_text('<head></head><body></body>', encoding='utf-8')

    def test_rejects_the_source_as_output(self):
        with self.assertRaises(ValueError):
            bundle_frontend.bundle(self.source, self.source)
        self.assertTrue(self.index.is_file())

    def test_rejects_a_parent_of_the_source_as_output(self):
        with self.assertRaises(ValueError):
            bundle_frontend.bundle(self.source, self.root)
        self.assertTrue(self.index.is_file())

    def test_rejects_an_output_inside_the_source(self):
        with self.assertRaises(ValueError):
            bundle_frontend.bundle(self.source, self.source / 'bundle')
        self.assertFalse((self.source / 'bundle').exists())

    def test_preserves_an_existing_destination_with_unrelated_files(self):
        output = self.root / 'output'
        output.mkdir()
        original = output / 'keep.txt'
        original.write_text('keep', encoding='utf-8')
        with self.assertRaises(ValueError):
            bundle_frontend.bundle(self.source, output)
        self.assertEqual(original.read_text(encoding='utf-8'), 'keep')

    def test_can_regenerate_owned_output(self):
        output = self.root / 'output'
        bundle_frontend.bundle(self.source, output)
        self.index.write_text('<head></head><body>Updated</body>', encoding='utf-8')
        bundle_frontend.bundle(self.source, output)
        self.assertIn('Updated', (output / 'index.html').read_text(encoding='utf-8'))


if __name__ == '__main__':
    unittest.main(verbosity=2)
