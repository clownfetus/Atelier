"""Material foundation checks run inside browser_smoke's real Bottle/Chromium session."""

import re
from pathlib import Path

GUI = Path(__file__).resolve().parent.parent / 'gui'


def source_files(*patterns):
    for pattern in patterns:
        for path in GUI.rglob(pattern):
            if 'vendor' not in path.relative_to(GUI).parts:
                yield path


def assert_type_system(page):
    # Static scan first: only uppercase labels are tracked, and the retired faces stay gone.
    tracked = re.compile(r'letter-spacing\s*:\s*([^;}]+)')
    for path in source_files('*.css'):
        text = path.read_text(encoding='utf-8')
        for value in tracked.findall(text):
            assert value.strip() in ('var(--studio-label-tracking)', '0'), (path.name, value)
        assert 'font-stretch' not in text and "'wdth'" not in text, path.name
    retired = re.compile(r'\b(Bricolage|Roboto|Instrument Sans)\b')
    for path in source_files('*.css', '*.js', '*.html'):
        assert not retired.search(path.read_text(encoding='utf-8')), path.name

    # One file carries both cuts, so the optical size axis has to follow the text's size.
    fonts = page.evaluate('''async () => {
      await document.fonts.load('400 64px Inter');
      const width = (size, settings) => {
        const probe = document.createElement('span');
        probe.textContent = 'Hamburgefonstiv Atelier 0123';
        probe.style.cssText = `position:absolute;white-space:nowrap;font:400 ${size}px Inter;font-optical-sizing:auto;`
          + (settings ? `font-variation-settings:${settings};` : '');
        document.body.append(probe);
        const result = probe.getBoundingClientRect().width;
        probe.remove();
        return result;
      };
      return {body: getComputedStyle(document.body).fontFamily,
        small: width(14), smallText: width(14, "'opsz' 14"),
        large: width(64), largeText: width(64, "'opsz' 14"), largeDisplay: width(64, "'opsz' 32")};
    }''')
    assert fonts['body'].startswith('Inter'), fonts
    assert abs(fonts['small'] - fonts['smallText']) < .5, fonts
    assert abs(fonts['large'] - fonts['largeDisplay']) < .5, fonts
    assert fonts['largeText'] - fonts['largeDisplay'] > 10, fonts


def measure_contrast(page):
    return page.evaluate('''() => {
      const css = getComputedStyle(document.documentElement);
      const rgb = name => {
        const probe = document.createElement('span'); probe.style.color = `var(${name})`;
        document.body.append(probe);
        const result = getComputedStyle(probe).color.match(/[\\d.]+/g).slice(0,3).map(Number);
        probe.remove(); return result;
      };
      const luminance = name => rgb(name).map(v => v/255).map(v => v<=.04045 ? v/12.92 : ((v+.055)/1.055)**2.4)
        .reduce((sum,v,i) => sum+v*[.2126,.7152,.0722][i],0);
      const ratio = (a,b) => (Math.max(luminance(a),luminance(b))+.05)/(Math.min(luminance(a),luminance(b))+.05);
      const pairs = [['--md-sys-color-on-primary','--md-sys-color-primary'],
        ['--md-sys-color-on-primary-container','--md-sys-color-primary-container'],
        ['--md-sys-color-on-secondary-container','--md-sys-color-secondary-container'],
        ['--md-sys-color-on-error-container','--md-sys-color-error-container']];
      for (const fg of ['--text','--muted','--acc','--green','--yellow','--blue'])
        for (const bg of ['--bg','--bg2','--bg3','--md-sys-color-surface-container-lowest','--md-sys-color-surface-container-highest']) pairs.push([fg,bg]);
      return pairs.map(([a,b])=>({a,b,ratio:ratio(a,b)}));
    }''')


ATELIER_SURFACES = {
    'light': {'--bg': '#F4F6F8', '--bg2': '#FFFFFF', '--bg3': '#E6EAEF', '--text': '#0D151F', '--muted': '#4E5F73',
              '--border': '#DDE3EA', '--acc': '#0D151F', '--md-sys-color-error': '#C5193E'},
    'dark': {'--bg': '#0D151F', '--bg2': '#172331', '--bg3': '#212E3B', '--text': '#F4F6F8', '--muted': '#B4C0CE',
             '--border': '#24323F', '--acc': '#F4F6F8', '--md-sys-color-error': '#EC6A86'},
}
STATUS_BASES = {'light': {'complete': '#419145', 'warning': '#9E7C18', 'error': '#E74165'},
                'dark': {'complete': '#7CC47F', 'warning': '#E6C35C', 'error': '#EC6A86'}}
PIECE_COLOURS = {'--atelier-texture': '#6C98CA', '--atelier-mesh': '#5AAA9A', '--atelier-material': '#DF8F6B'}


def assert_theme_tokens(page, mode, preset):
    """Pieces never change, statuses read on this theme's surfaces and keep their hue, the halo is the surface."""
    colour = lambda *names: page.evaluate("""names => {
      const probe = document.createElement('span'); document.body.append(probe);
      const values = names.map(name => { probe.style.color = `var(${name})`;
        return '#' + getComputedStyle(probe).color.match(/[\\d.]+/g).slice(0,3).map(n => (+n).toString(16).padStart(2,'0')).join('').toUpperCase(); });
      probe.remove(); return values; }""", list(names))
    def rgb(value):
        return [int(value[i:i + 2], 16) / 255 for i in (1, 3, 5)]
    def luminance(value):
        return sum(w * (v / 12.92 if v <= .04045 else ((v + .055) / 1.055) ** 2.4)
                   for v, w in zip(rgb(value), (.2126, .7152, .0722)))
    def ratio(a, b):
        a, b = sorted((luminance(a), luminance(b)), reverse=True)
        return (a + .05) / (b + .05)
    def hue(value):
        r, g, b = rgb(value)
        high, low = max(r, g, b), min(r, g, b)
        if high == low:
            return None
        return ((g - b) / (high - low) % 6 if high == r else (b - r) / (high - low) + 2 if high == g
                else (r - g) / (high - low) + 4) * 60

    assert colour(*PIECE_COLOURS) == list(PIECE_COLOURS.values()), (mode, preset)
    backgrounds = colour('--bg', '--bg2', '--bg3')
    assert colour('--glyph-halo') == [backgrounds[0]], (mode, preset)
    for role, base in STATUS_BASES[mode].items():
        shown, sentence = colour(f'--status-{role}', f'--status-{role}-text')
        assert min(ratio(shown, surface) for surface in backgrounds) >= 3, (mode, preset, role, shown)
        assert min(ratio(sentence, surface) for surface in backgrounds) >= 4.5, (mode, preset, role, sentence)
        turned = abs(hue(shown) - hue(base)) % 360
        assert min(turned, 360 - turned) < 4, (mode, preset, role, shown, base)
    for name in ('--studio-success', '--studio-warning', '--md-sys-color-error'):
        assert min(ratio(colour(name)[0], surface) for surface in backgrounds) >= 4.5, (mode, preset, name)
    for role in ('texture', 'mesh', 'material', 'neutral'):
        assert min(ratio(colour(f'--studio-icon-{role}')[0], surface) for surface in backgrounds) >= 4.5, (mode, preset, role)
    if preset == 'studio':
        names = list(ATELIER_SURFACES[mode])
        assert dict(zip(names, colour(*names))) == ATELIER_SURFACES[mode], mode
    # The identity's surfaces use the same theme.
    roles = page.evaluate("""() => { const host = document.createElement('div'); host.className = 'at-identity'; document.body.append(host);
      const css = getComputedStyle(host), read = name => { host.style.color = `var(${name})`; return css.color; };
      const roles = {text: read('--text'), surface: (host.style.background = 'var(--surface)', css.backgroundColor)};
      host.style.background = 'var(--surface-sunk)'; roles.sunk = css.backgroundColor; host.remove(); return roles; }""")
    assert roles.pop('sunk') != roles['surface'], (mode, preset, 'fields and pending dots need a fill that differs from the surface')
    plain = page.evaluate("""() => { const host = document.createElement('div'); document.body.append(host);
      host.style.color = 'var(--text)'; host.style.background = 'var(--bg)'; const css = getComputedStyle(host);
      const roles = {text: css.color, surface: css.backgroundColor}; host.remove(); return roles; }""")
    assert roles == plain, (mode, preset, roles, plain)


def assert_folder_icon_size(card):
    measurements = card.locator('.card-thumb > .card-icon').evaluate('''icon => {
      const thumb = icon.parentElement, css = getComputedStyle(thumb);
      const box = icon.getBoundingClientRect(), bounds = thumb.getBoundingClientRect();
      return {width: box.width, height: box.height,
        contentWidth: thumb.clientWidth - parseFloat(css.paddingLeft) - parseFloat(css.paddingRight),
        contentHeight: thumb.clientHeight - parseFloat(css.paddingTop) - parseFloat(css.paddingBottom),
        contained: box.left >= bounds.left && box.top >= bounds.top &&
          box.right <= bounds.right && box.bottom <= bounds.bottom};
    }''')
    assert measurements['contained'], measurements
    # Folder artwork fills the preview; toolbar symbols keep their compact control size.
    for dimension in ('width', 'height'):
        content = measurements['content' + dimension.title()]
        assert content > 0 and abs(measurements[dimension] - content * .76) < .5, measurements


def run_design_checks(page, context, url, report, checks):
    picker = page.locator('#settings-theme')
    # Other workflow suites set this hidden preference directly; here exercise Settings.
    def choose(theme):
        # Startup deliberately leaves remote fetches unresolved. Settings uses the
        # key service; complete that fixture after every reload as well.
        page.evaluate('''() => {
          const fetch = window.fetch;
          window.fetch = (url, options) => String(url).startsWith('https://')
            ? Promise.resolve(new Response('{}', {headers:{'Content-Type':'application/json'}}))
            : fetch(url, options);
        }''')
        page.evaluate('openPaths()')
        page.wait_for_function('!document.getElementById("setup-loading").classList.contains("active")')
        picker.select_option(theme)
        page.locator('#setup-close').click()
    page.set_viewport_size({'width': 1400, 'height': 900})
    page.wait_for_function('document.fonts.check("14px Inter")')
    assert_type_system(page)
    checks.append('Inter is the interface face, optical size follows the text, only uppercase labels are tracked')
    page.evaluate("pushNav({path:'Foundation checks'})")
    assert page.evaluate('document.querySelector(".studio-brand img").naturalWidth') > 0
    for theme in ('light', 'dark'):
        choose(theme)
        assert page.locator('html').get_attribute('data-theme') == theme
        assert page.locator('#settings-theme').input_value() == theme
        # The 156px card leaves 130px after 12px padding and a 1px border on each side.
        card = page.locator('#grid-area .card').first
        assert card.bounding_box()['width'] == 156
        assert card.locator('.card-thumb').bounding_box()['width'] == 130
        # Measure actual computed roles, including the brightest container background.
        contrast = measure_contrast(page)
        assert all(pair['ratio'] >= 4.5 for pair in contrast), (theme, contrast)
        for size in (128, 156, 196, 236):
            page.locator('#library-size').select_option(str(size))
            assert card.bounding_box()['width'] == size
            assert_folder_icon_size(card)
        page.locator('#library-size').select_option('156')
        for width, height in ((1024,768), (1280,800), (1400,900), (1920,1080)):
            page.set_viewport_size({'width': width, 'height': height})
            assert page.evaluate('document.documentElement.scrollWidth <= innerWidth')
            assert page.locator('#install-btn').is_visible()
            page.screenshot(path=str(report / f'{theme}-{width}x{height}.png'), animations='disabled')
    checks.append('Light/dark color pairs pass 4.5:1; shell fits four desktop sizes; local font/logo load')
    checks.append('Folder icons fill 76% of their preview and stay contained at all four thumbnail sizes in both themes')

    page.reload()
    page.wait_for_function("document.getElementById('grid-area').getAttribute('aria-busy') === 'false'")
    # Reload opens Home, where category cards can be collapsed. Continue this
    # theme-persistence check in the same folder surface used above.
    page.evaluate("pushNav({path:'Foundation checks'})")
    page.wait_for_selector('#grid-area .card')
    assert page.locator('html').get_attribute('data-theme') == 'dark'
    page.emulate_media(color_scheme='light')
    assert page.locator('html').get_attribute('data-theme') == 'dark'
    choose('system')
    assert page.locator('html').get_attribute('data-theme') == 'light'
    page.emulate_media(color_scheme='dark')
    page.wait_for_function('document.documentElement.dataset.theme === "dark"')
    checks.append('Theme persists across reloads, follows OS in System mode and stays fixed when explicitly selected')

    page.locator('#menu-btn').focus()
    page.keyboard.press('Enter')
    page.wait_for_selector('#ctx-menu.active')
    page.keyboard.press('ArrowDown')
    assert page.evaluate('document.activeElement.textContent.includes("Refresh view")')
    page.keyboard.press('Escape')
    assert page.locator('#menu-btn').evaluate('(el)=>el===document.activeElement')
    page.locator('#grid-area .card').first.focus()
    assert page.locator('#grid-area .card').first.evaluate('(el)=>getComputedStyle(el).outlineStyle') == 'solid'
    card = page.locator('#grid-area .card').first
    assert_folder_icon_size(card)
    assert page.locator('#menu-btn > .studio-icon').evaluate('(el)=>el.getBoundingClientRect().width') == 18
    card.hover()
    page.mouse.down()
    try:
        assert card.evaluate('el=>getComputedStyle(el).transform') == 'none'
    finally:
        page.mouse.move(1, 1)
        page.mouse.up()
    missing = page.evaluate('''() => [...document.querySelectorAll('[data-lucide]')]
      .map(el=>el.dataset.lucide).filter(name=>!AtelierSymbolPaths[name])''')
    assert not missing, missing
    checks.append('Keyboard menu navigation/focus return work; folder symbols fill tiles; all rendered symbols are mapped')

    page.route('**/api/material_params?*', lambda route: route.fulfill(json={
        'ok': True, 'colors': [{'name':'Base Color', 'rgba':[0.25,0.5,0.75,1]},
                                {'name':'Emissive Color', 'rgba':[2,1,0.5,1]}],
        'scalars': [{'name':'Roughness','value':0.35}, {'name':'Metallic','value':0.8}]}))
    page.route('**/api/dye_info?*', lambda route: route.fulfill(json={'dyeable':False}))
    page.set_viewport_size({'width':1400,'height':900})
    page.evaluate("openMaterialEditor({name:'MI_Body', game_rel:'Characters/1029/1029100/Materials/MI_Body'})")
    page.wait_for_selector('#mathx0')
    page.locator('#mathx0').fill('#ab3456')
    page.locator('#mathx0').press('Tab')
    draft = page.evaluate('JSON.stringify(matEditor)')
    # Appearance changes must preserve editor state.
    for theme in ('light','dark'):
        page.locator('#settings-theme').evaluate('(el,v)=>{el.value=v;el.dispatchEvent(new Event("change"));}', theme)
        assert page.evaluate('JSON.stringify(matEditor)') == draft
        page.screenshot(path=str(report / f'material-{theme}.png'), animations='disabled')
    for preset in ('repak', 'darcula', 'studio'):
        page.locator(f'[data-theme-preset="{preset}"]').dispatch_event('click')
        assert page.evaluate('JSON.stringify(matEditor)') == draft
    page.emulate_media(reduced_motion='reduce')
    assert page.locator('#material-overlay .modal').evaluate('(el)=>getComputedStyle(el).animationName') == 'none'
    assert page.locator('#mat-save').evaluate('(el)=>getComputedStyle(el).transitionDuration') == '0s'
    page.locator('#mat-close').click()
    page.emulate_media(reduced_motion='no-preference')
    checks.append('Mode and palette changes preserve a live material draft; reduced motion disables effects')

    isolated = context.new_page()
    isolated.add_init_script("""Storage.prototype.getItem = () => {throw new Error('storage unavailable')};
      Storage.prototype.setItem = () => {throw new Error('storage unavailable')};""")
    isolated.goto(url)
    isolated.wait_for_selector('#grid-area .card')
    isolated.locator('#settings-theme').select_option('light', force=True)
    assert isolated.locator('html').get_attribute('data-theme') == 'light'
    isolated.close()
    checks.append('Blocked localStorage does not prevent launch or in-session theme changes')
