"""Exercise appearance through Settings and first-run setup in real Chromium."""
from design_checks import assert_theme_tokens, measure_contrast


def assert_brand_follows_theme(tab):
    state = tab.evaluate("""() => {
      const brand = document.querySelector('.studio-brand'), probe = document.createElement('span');
      probe.style.color = 'var(--text)'; document.body.append(probe);
      const text = getComputedStyle(probe).color; probe.remove();
      const marks = [...brand.querySelectorAll(':scope > img, :scope > [data-atelier-motion="glyph"]')];
      return {text, letters: getComputedStyle(brand.querySelector('.studio-wordmark')).color,
              filters: marks.map(mark => getComputedStyle(mark).filter),
              signature: getComputedStyle(document.documentElement).getPropertyValue('--library-signature-filter')};
    }""")
    assert state['letters'] == state['text'], state
    assert all(value == 'none' for value in state['filters']), state
    assert 'brightness(0)' in state['signature'], state


def assert_lockups(tab):
    """D6: the spacing from bible p.12 in the header and on the start page, and a header that fits."""
    measure = """host => {
      const shown = [...host.querySelectorAll(':scope > img, :scope > [data-atelier-motion]')].find(el => el.getBoundingClientRect().width);
      const mark = shown.getBoundingClientRect(), name = host.querySelector(':scope > svg').getBoundingClientRect();
      return {mark: mark.height, markWidth: mark.width, cap: name.height, name: name.width, gap: name.left - mark.right};
    }"""
    near = lambda a, b: abs(a - b) < .3
    header = tab.locator('.studio-brand').evaluate(measure)
    assert near(header['mark'], 32.4) and near(header['cap'], 12) and near(header['gap'], 15.6), header
    assert 136 <= tab.locator('.studio-brand').evaluate('el => el.getBoundingClientRect().width') <= 146, header
    start = tab.evaluate("""measure => {
      const copy = document.querySelector('#setup-hero .at-proj-lockup').cloneNode(true);
      document.body.append(copy); const result = eval(measure)(copy); copy.remove(); return result;
    }""", measure)
    assert near(start['mark'], 64.8) and near(start['cap'], 24) and near(start['gap'], 31.2), start
    hero = tab.locator('#setup-hero')
    assert hero.locator('.at-proj-lockup').get_attribute('aria-label') == 'Atelier'
    assert hero.locator('.at-proj-rivals, .at-proj-tagline').count() == 0
    size = tab.viewport_size
    try:
        for width, named in ((1400, True), (1101, True), (1100, False), (900, False)):
            tab.set_viewport_size({'width': width, 'height': size['height']})
            state = tab.evaluate("""() => {
              const bar = document.getElementById('topbar'), name = document.querySelector('.studio-wordmark');
              return {fits: bar.scrollWidth <= bar.clientWidth, named: getComputedStyle(name).display !== 'none',
                      accessible: document.querySelector('.studio-brand').getAttribute('aria-label')};
            }""")
            assert state['fits'] and state['named'] == named and state['accessible'], (width, state)
    finally:
        tab.set_viewport_size(size)


EYEDROPPER_STUB = """
  window.__eyedropper = {result: '#2A7F62', cancel: false, opened: 0};
  window.EyeDropper = class {
    open() { window.__eyedropper.opened++;
      return window.__eyedropper.cancel ? Promise.reject(new DOMException('Cancelled', 'AbortError'))
                                        : Promise.resolve({sRGBHex: window.__eyedropper.result}); }
  };
"""


def run_eyedropper_checks(context, url, checks):
    """The pipette beside each swatch applies a pick through the swatch's own handlers."""
    tab = context.new_page(); errors = []
    tab.on('pageerror', lambda error: errors.append(str(error)))
    try:
        tab.add_init_script(EYEDROPPER_STUB)
        tab.goto(url); tab.wait_for_selector('#grid-area .card')
        state = tab.evaluate("""async () => {
          const row = document.createElement('div'); row.className = 'mat-row';
          row.innerHTML = '<span class="mat-color-well"><input type="color" id="probe-well" value="#ff0000" oninput="window.__inline = this.value"></span><input class="mat-hex">';
          document.body.append(row);
          const plain = document.createElement('input'); plain.type = 'color'; plain.value = '#000000'; plain.id = 'probe-plain';
          const events = []; for (const t of ['input', 'change']) plain.addEventListener(t, e => events.push([t, e.target.value]));
          document.body.append(plain);
          await new Promise(resolve => setTimeout(resolve, 0));
          const well = document.getElementById('probe-well'), wellButton = well.parentElement.nextElementSibling;
          wellButton.click(); await new Promise(resolve => setTimeout(resolve, 0));
          const plainButton = plain.nextElementSibling;
          plainButton.click(); await new Promise(resolve => setTimeout(resolve, 0));
          window.__eyedropper.cancel = true; window.__eyedropper.result = '#111111';
          plainButton.click(); await new Promise(resolve => setTimeout(resolve, 0));
          const theme = document.querySelector('[data-theme-color="accent"]');
          const result = {wellButton: wellButton?.className, wellValue: well.value, inline: window.__inline,
            plainButton: plainButton?.className, plainValue: plain.value, events, opened: window.__eyedropper.opened,
            pressed: plainButton.getAttribute('aria-pressed'), label: plainButton.getAttribute('aria-label'),
            icon: !!plainButton.querySelector('svg.studio-icon'),
            themeOrder: [...theme.parentElement.children].map(el => el.tagName.toLowerCase() + (el.className ? '.' + el.className : '')),
            backdrop: !!document.getElementById('viewport-backdrop-color').nextElementSibling?.classList.contains('eyedropper-btn')};
          row.remove(); plain.remove(); plainButton.remove(); return result;
        }""")
        assert state['wellButton'] == 'eyedropper-btn' and state['wellValue'] == '#2a7f62' and state['inline'] == '#2a7f62', state
        assert state['plainButton'] == 'eyedropper-btn' and state['plainValue'] == '#2a7f62', state
        assert state['events'] == [['input', '#2a7f62'], ['change', '#2a7f62']], state
        assert state['opened'] == 3 and state['pressed'] == 'false' and state['icon'], state
        assert state['label'] == 'Pick a colour from the screen', state
        assert state['themeOrder'] == ['input', 'output', 'button.eyedropper-btn'], state
        assert not state['backdrop'], state
        # Without the engine's EyeDropper (Linux WebKitGTK), no pipettes appear.
        bare = context.new_page()
        try:
            bare.add_init_script('delete window.EyeDropper')
            bare.goto(url); bare.wait_for_selector('#grid-area .card')
            assert bare.locator('.eyedropper-btn').count() == 0
        finally:
            bare.close()
        assert not errors, errors
        checks.append('Pipettes beside colour swatches apply a pick through the swatch handlers, keep it on cancel, and appear only where EyeDropper exists')
    finally:
        tab.close()


def run_appearance_checks(page, context, url, report, checks):
    run_eyedropper_checks(context, url, checks)
    tab = context.new_page()
    failures = []
    tab.on('pageerror', lambda error: failures.append(str(error)))

    def settings():
        tab.locator('#menu-btn').click()
        tab.locator('#ctx-menu button', has_text='Settings').click()
        tab.wait_for_function('!document.getElementById("setup-loading").classList.contains("active")')

    def color(key, value):
        tab.locator(f'[data-theme-color="{key}"]').fill(value)

    try:
        tab.goto(url)
        tab.wait_for_selector('#grid-area .card')
        assert tab.locator('#topbar [data-theme-picker]').count() == 0
        assert tab.locator('#topbar > :last-child').get_attribute('id') == 'menu-btn'
        # Materialize dropdowns that the editors create only after an asset opens.
        tab.route('**/api/curve_params?*', lambda route: route.fulfill(json={'ok': True,
            'channels': {'R': [{'time': 0, 'value': .5, 'interp': 'RCIM_Linear'}]}, 'stops': []}))
        tab.route('**/api/asset_opts?*', lambda route: route.fulfill(json={'ok': True, 'opts': {},
            'groups': ['TEXTUREGROUP_World', 'TEXTUREGROUP_Character'], 'format': 'DXT5'}))
        tab.evaluate("openCurveEditor({name:'Fixture curve',game_rel:'Fixture/Curve'})")
        tab.wait_for_selector('#curve-body select')
        tab.locator('#curve-close').click()
        tab.evaluate("openTexOpts({name:'Fixture texture',game_rel:'Fixture/Texture'})")
        tab.wait_for_selector('#texopt-body select')
        tab.locator('#texopt-close').click()
        settings()
        picker = tab.locator('#settings-theme')
        assert picker.locator('option').all_text_contents() == ['Light', 'Dark', 'System']
        for mode in ('dark', 'light'):
            picker.select_option(mode)
            for preset in ('studio', 'darcula', 'repak', 'contrast', 'blueprint', 'comic'):
                button = tab.locator(f'[data-theme-preset="{preset}"]')
                button.click()
                tab.wait_for_function("([mode,preset])=>document.documentElement.dataset.theme===mode && document.documentElement.dataset.palette===preset", arg=[mode,preset])
                assert button.get_attribute('aria-pressed') == 'true'
                assert button.locator('.theme-swatches i').count() == 4
                assert all(pair['ratio'] >= 4.5 for pair in measure_contrast(tab)), (mode, preset)
                assert_theme_tokens(tab, mode, preset)
                # Check popup options in every select, including dynamically created editors.
                styles = tab.evaluate('''() => [...document.querySelectorAll('select')].map(select => {
                  const option = select.querySelector('option');
                  const probe = document.createElement('span'); probe.style.color='var(--text)';
                  (select.closest('#viewport-box') || document.body).append(probe); const text=getComputedStyle(probe).color;
                  probe.style.color=select.closest('#viewport-box') ? 'var(--acc)' : 'var(--md-sys-color-on-secondary-container)'; const selected=getComputedStyle(probe).color; probe.remove();
                  return {scheme:getComputedStyle(select).colorScheme, color:getComputedStyle(select).color,
                    option:option ? getComputedStyle(option).color : text,
                    expected:option?.matches(':checked') && CSS.supports('appearance','base-select') ? selected : text,
                    background:option ? getComputedStyle(option).backgroundColor : 'none', text};
                })''')
                assert all(s['scheme'] == mode and s['color'] == s['text'] and s['option'] == s['expected']
                           and s['background'] != 'rgba(0, 0, 0, 0)' for s in styles), styles
                assert_brand_follows_theme(tab)
                tab.screenshot(path=str(report / f'appearance-{preset}-{mode}.png'), animations='disabled')
        assert_lockups(tab)
        checks.append('Settings presets show four swatches; all six presets pass contrast checks in light and dark, keep the piece colours fixed and fit status colours by lightness only; native selects/options follow the theme, and the logo keeps its colours with its letters in the text colour')

        # Real popup interaction keeps native focus, selection and dismissal behavior.
        picker.click()
        tab.screenshot(path=str(report / 'appearance-dropdown-light.png'), animations='disabled')
        tab.keyboard.press('ArrowDown')
        tab.keyboard.press('Enter')
        assert picker.input_value() == 'dark'
        picker.click()
        tab.keyboard.press('Escape')
        assert picker.input_value() == 'dark'
        tab.screenshot(path=str(report / 'appearance-settings-dark.png'), animations='disabled')
        checks.append('Dropdown popup selection works with ArrowDown/Enter; Escape dismisses without changing selection')

        picker.select_option('dark')
        tab.locator('[data-theme-preset="repak"]').click()
        tab.locator('[data-theme-preset="custom"]').click()
        assert tab.locator('[data-theme-color="background"]').evaluate('(el)=>el===document.activeElement')
        assert tab.locator('[data-theme-color]').evaluate_all('(els)=>els.every(el=>el.type==="color" && typeof el.showPicker==="function")')
        color('background', '#080808')
        color('surface', '#222222')
        color('foreground', '#f7f7f7')
        color('accent', '#ff5964')
        assert tab.locator('body').evaluate('(el)=>getComputedStyle(el).backgroundColor') == 'rgb(8, 8, 8)'
        assert tab.locator('body').evaluate('(el)=>getComputedStyle(el).color') == 'rgb(247, 247, 247)'
        tab.screenshot(path=str(report / 'appearance-custom-dark.png'), animations='disabled')
        picker.select_option('light')
        color('background', '#fff9ef')
        picker.select_option('dark')
        tab.wait_for_function("document.documentElement.dataset.theme==='dark'")
        assert tab.locator('[data-theme-color="background"]').input_value() == '#080808'
        # Visiting a preset must not discard the saved custom palette.
        tab.locator('[data-theme-preset="studio"]').click()
        tab.locator('[data-theme-preset="custom"]').click()
        tab.wait_for_function("document.documentElement.dataset.palette==='custom'")
        assert tab.locator('[data-theme-color="background"]').input_value() == '#080808'
        tab.reload()
        tab.wait_for_selector('#grid-area .card')
        assert tab.locator('html').get_attribute('data-palette') == 'custom'
        assert tab.locator('body').evaluate('(el)=>getComputedStyle(el).backgroundColor') == 'rgb(8, 8, 8)'
        # A second window synchronizes mode and palette through native storage events.
        settings()
        tab.locator('[data-theme-preset="darcula"]').click()
        page.wait_for_function('document.documentElement.dataset.palette === "darcula"')
        tab.emulate_media(color_scheme='light')
        picker.select_option('system')
        tab.wait_for_function("document.documentElement.dataset.theme==='light'")
        assert tab.locator('html').get_attribute('data-theme') == 'light'
        tab.emulate_media(color_scheme='dark')
        tab.wait_for_function('document.documentElement.dataset.theme === "dark"')
        tab.locator('[data-theme-preset="custom"]').click()
        color('foreground', '#080808')
        assert tab.locator('#theme-contrast').is_visible()
        assert all(pair['ratio'] >= 4.5 for pair in measure_contrast(tab))
        color('background', '#ffffff')
        color('foreground', '#fafafa')
        assert all(pair['ratio'] >= 4.5 for pair in measure_contrast(tab))
        assert_brand_follows_theme(tab)
        color('background', '#080808')
        color('foreground', '#f7f7f7')
        assert tab.locator('#theme-contrast').is_hidden()
        assert all(pair['ratio'] >= 4.5 for pair in measure_contrast(tab))
        checks.append('Native color inputs preserve readable BG/FG, save separate light/dark colors, survive reloads and preset changes, sync windows and correct low contrast')

        # Save multiple reusable palettes, including text that must remain literal.
        for name in ('Red studio', '<b>Warm paper</b>'):
            tab.locator('#theme-palette-name').fill(name)
            tab.locator('#theme-palette-save').click()
        assert tab.locator('[data-saved-palette]').count() == 2
        assert tab.locator('[data-saved-palette] b').count() == 0
        tab.reload()
        tab.wait_for_selector('#grid-area .card')
        settings()
        assert tab.locator('[data-saved-palette]').count() == 2
        tab.locator('[data-saved-palette]').first.click()
        tab.wait_for_function("document.querySelector('[data-saved-palette]').getAttribute('aria-pressed')==='true'")
        assert tab.locator('[data-saved-palette]').first.get_attribute('aria-pressed') == 'true'
        tab.locator('#theme-palette-delete').click()
        assert tab.locator('[data-saved-palette]').count() == 1
        assert tab.locator('html').get_attribute('data-palette') == 'studio'
        checks.append('Multiple named custom palettes persist, restore and delete safely; palette names render as literal text')

        # Existing native title text gets themed, including dynamic editor controls.
        for mode in ('light', 'dark'):
            picker.select_option(mode)
            tab.locator('[data-theme-preset="repak"]').click()
            tab.wait_for_function("document.documentElement.dataset.palette==='repak'")
            tab.evaluate("Promise.allSettled(document.getAnimations().filter(animation=>animation.effect?.pseudoElement).map(animation=>animation.finished))")
            help_button = tab.locator('.setup-help-btn')
            tab.keyboard.press('Tab')
            help_button.focus()
            tab.wait_for_selector('#atelier-tooltip:visible')
            assert help_button.get_attribute('aria-describedby') == 'atelier-tooltip'
            assert tab.locator('#atelier-tooltip').inner_text() == 'Help'
            assert tab.locator('#atelier-tooltip').evaluate('(el)=>getComputedStyle(el).color') == tab.locator('body').evaluate('(el)=>getComputedStyle(el).color')
            tab.screenshot(path=str(report / f'appearance-tooltip-{mode}.png'), animations='disabled')
            tab.keyboard.press('Escape')
            # The bubble folds away (P4b.7) and is gone within its 150 ms fold.
            tab.wait_for_selector('#atelier-tooltip', state='hidden', timeout=1000)
            assert help_button.get_attribute('title') == 'Help'
        tab.locator('#setup-close').click()
        for mode in ('light', 'dark'):
            picker.select_option(mode, force=True)
            tab.locator('#menu-btn').click()
            menu = tab.locator('#ctx-menu')
            assert menu.bounding_box()['x'] + menu.bounding_box()['width'] <= tab.viewport_size['width']
            menu.locator('button').nth(1).hover()
            tab.screenshot(path=str(report / f'appearance-menu-{mode}.png'), animations='disabled')
            tab.keyboard.press('Escape')
            assert tab.locator('#menu-btn').evaluate('(el)=>el===document.activeElement')
            tab.screenshot(path=str(report / f'appearance-workspace-{mode}.png'), animations='disabled')
        checks.append('Themed tooltips preserve title/accessibility text and Escape; right-aligned menus remain onscreen and return keyboard focus')

        # First run asks only for what the check couldn't find; appearance lives in Settings.
        setup = context.new_page()
        try:
            setup.route('**/api/setup_status', lambda route: route.fulfill(json={'configured': False}))
            setup.route('**/api/validate_paks?*', lambda route: route.fulfill(json={'status':'ok'}))
            setup.route('**/api/validate_usmap?*', lambda route: route.fulfill(json={'status':'ok'}))
            setup.route('**/AES.json', lambda route: route.abort())
            setup.route('**/api/download_usmap', lambda route: route.fulfill(json={'ok': False}))
            setup.goto(url)
            setup.wait_for_selector('#setup-overlay.active[data-setup-page=first-run]')
            setup.wait_for_function("document.querySelectorAll('#setup-rows [data-state=missing]').length===3")
            setup.locator('#setup-path').fill('Fixture game')
            setup.locator('#setup-aes').fill('0x'+'a'*64)
            setup.locator('#setup-usmap').fill('fixture.usmap')
            setup.wait_for_function("!document.getElementById('setup-save').disabled")
            assert setup.locator('#settings-theme').is_hidden()
            assert 'Appearance and motion are in Settings.' in setup.locator('#setup-page-note').inner_text()
            setup.screenshot(path=str(report / 'appearance-first-run.png'), animations='disabled')
            setup.evaluate('openPaths()')
            setup.wait_for_function("!document.getElementById('setup-loading').classList.contains('active')", timeout=20000)
            setup.locator('#settings-theme').select_option('dark')
            setup.locator('[data-theme-preset="repak"]').click()
            setup.wait_for_function("document.documentElement.dataset.palette==='repak'")
            assert setup.locator('html').get_attribute('data-palette') == 'repak'
        finally:
            setup.close()
        checks.append('First-time configuration leaves appearance to Settings, says so, and Settings applies it before setup is saved')

        # Malformed old preferences and blocked storage must still allow launch/customization.
        for blocked in (False, True):
            fallback = context.new_page()
            try:
                fallback.add_init_script('''Storage.prototype.getItem = key => key === 'atelier.appearance' ? '{broken' : null;''')
                if blocked:
                    fallback.add_init_script('''Storage.prototype.getItem = () => {throw Error('blocked')};
                      Storage.prototype.setItem = () => {throw Error('blocked')};''')
                fallback.goto(url)
                fallback.wait_for_selector('#grid-area .card')
                assert fallback.locator('html').get_attribute('data-palette') == 'studio'
                fallback.locator('#settings-theme').select_option('dark', force=True)
                fallback.locator('[data-theme-preset="repak"]').dispatch_event('click')
                assert fallback.locator('html').get_attribute('data-palette') == 'repak'
            finally:
                fallback.close()
        checks.append('Malformed or unavailable appearance storage falls back safely and allows session changes')
        legacy = context.new_page()
        try:
            from pathlib import Path
            css = (Path(__file__).resolve().parents[1] / 'gui/style.css').read_text(encoding='utf-8')
            legacy.route('**/static/style.css', lambda route: route.fulfill(
                body=css.replace('@supports (appearance: base-select)', '@supports (appearance: unavailable-select)'),
                content_type='text/css'))
            legacy.goto(url)
            legacy.wait_for_selector('#grid-area .card')
            for mode in ('light', 'dark'):
                legacy.locator('#settings-theme').select_option(mode, force=True)
                assert legacy.locator('#library-type').evaluate('(el)=>getComputedStyle(el).appearance') == 'auto'
                assert legacy.locator('#library-type').evaluate('(el)=>getComputedStyle(el).colorScheme') == mode
                assert legacy.locator('#library-type option').first.evaluate('(el)=>getComputedStyle(el).backgroundColor') != 'rgba(0, 0, 0, 0)'
        finally:
            legacy.close()
        checks.append('Unsupported customizable selects retain the native control with themed text/options and the correct OS color scheme')
        assert not failures, failures
    finally:
        tab.locator('[data-theme-preset="studio"]').dispatch_event('click')
        tab.locator('#settings-theme').select_option('dark', force=True)
        tab.close()
