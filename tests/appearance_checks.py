"""Exercise appearance through Settings and first-run setup in real Chromium."""
from design_checks import measure_contrast


def run_appearance_checks(page, context, url, report, checks):
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
            for preset in ('studio', 'darcula', 'repak'):
                button = tab.locator(f'[data-theme-preset="{preset}"]')
                button.click()
                tab.wait_for_function("([mode,preset])=>document.documentElement.dataset.theme===mode && document.documentElement.dataset.palette===preset", arg=[mode,preset])
                assert button.get_attribute('aria-pressed') == 'true'
                assert button.locator('.theme-swatches i').count() == 4
                assert all(pair['ratio'] >= 4.5 for pair in measure_contrast(tab)), (mode, preset)
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
                brand = tab.locator('.studio-brand')
                assert brand.evaluate('(el)=>getComputedStyle(el).color') == ('rgb(255, 255, 255)' if mode == 'dark' else 'rgb(0, 0, 0)')
                mark = brand.locator(':scope > img, :scope > [data-atelier-motion="logo-entrance"]').last
                assert 'brightness(0)' in mark.evaluate('(el)=>getComputedStyle(el).filter')
                tab.screenshot(path=str(report / f'appearance-{preset}-{mode}.png'), animations='disabled')
        checks.append('Settings presets show four swatches; six palettes pass contrast checks; native selects/options and monochrome brand follow the theme')

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
        assert tab.locator('.studio-brand').evaluate('(el)=>getComputedStyle(el).color') == 'rgb(0, 0, 0)'
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
            help_button.focus()
            tab.wait_for_selector('#atelier-tooltip:visible')
            assert help_button.get_attribute('aria-describedby') == 'atelier-tooltip'
            assert tab.locator('#atelier-tooltip').inner_text() == 'Help'
            assert tab.locator('#atelier-tooltip').evaluate('(el)=>getComputedStyle(el).color') == tab.locator('body').evaluate('(el)=>getComputedStyle(el).color')
            tab.screenshot(path=str(report / f'appearance-tooltip-{mode}.png'), animations='disabled')
            tab.keyboard.press('Escape')
            assert tab.locator('#atelier-tooltip').is_hidden()
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

        # Appearance is available in the actual unconfigured startup, too.
        setup = context.new_page()
        try:
            setup.route('**/api/setup_status', lambda route: route.fulfill(json={'configured': False}))
            setup.goto(url)
            setup.wait_for_function('document.getElementById("setup-overlay").classList.contains("active") && !document.getElementById("setup-loading").classList.contains("active")')
            assert setup.locator('#setup-title').inner_text() == 'Initial Configuration'
            setup.locator('#settings-theme').select_option('dark')
            setup.locator('[data-theme-preset="repak"]').click()
            setup.wait_for_function("document.documentElement.dataset.palette==='repak'")
            assert setup.locator('html').get_attribute('data-palette') == 'repak'
            setup.screenshot(path=str(report / 'appearance-first-run.png'), animations='disabled')
        finally:
            setup.close()
        checks.append('First-time configuration includes the same appearance controls without a header selector')

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
