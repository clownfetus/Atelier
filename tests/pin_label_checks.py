"""Nested shortcut context, old-profile migration and custom-label preservation."""


def run_pin_label_checks(page, context, url, report, checks):
    pin_page = context.new_page()
    key = 'atelier.homePins.v1'
    prior = None
    try:
        pin_page.goto(url)
        pin_page.wait_for_function('Boolean(window.AtelierLibraryPins)')
        prior = pin_page.evaluate('key => localStorage.getItem(key)', key)
        pin_page.evaluate("""key => {
          localStorage.setItem(key, JSON.stringify({version: 1, pins: [
            {path: 'Characters/1015/1015502/Textures', label: 'Textures'},
            {path: 'Characters/1029/1029100/Materials', label: 'Magik materials'}
          ]}));
        }""", key)
        pin_page.reload()
        pin_page.wait_for_function('Boolean(window.AtelierLibraryPins)')
        result = pin_page.evaluate("""() => {
          const labels = {
            'Characters/1015': '1015 — Storm',
            'Characters/1015/1015502': '502 — GODDESS OF THUNDER',
            'Characters/1015/1015502/Textures': 'Textures',
            'Characters/1029': '1029 — Magik',
            'Characters/1029/1029100': '100 — Default'
          };
          AtelierLibraryPins.updateLabels(labels);
          return {
            label: AtelierLibraryPins.makePinLabel('Characters/1015/1015502/Textures', labels),
            fallback: AtelierLibraryPins.makePinLabel('Characters/1015/1015999/Textures', labels),
            map: AtelierLibraryPins.makePinLabel('Maps/Tokyo/Lighting'),
            unsafe: AtelierLibraryPins.makePinLabel('Characters/%2e%2e/Textures'),
            pins: AtelierLibraryPins.list()
          };
        }""")
        expected = 'Storm · GODDESS OF THUNDER · Textures'
        assert result['label'] == expected
        assert result['fallback'] == 'Storm · 1015999 · Textures'
        assert result['map'] == 'Maps · Tokyo · Lighting'
        assert result['unsafe'] == ''
        assert result['pins'][0]['label'] == expected
        assert result['pins'][1]['label'] == 'Magik materials'
        pin_page.reload()
        pin_page.wait_for_function('Boolean(window.AtelierLibraryPins)')
        # Learning an unrelated branch cannot discard a saved pin's ancestry.
        pin_page.evaluate("AtelierLibraryPins.updateLabels({'Maps': 'Maps', 'Characters/1015': '1015 — Storm'})")
        saved = pin_page.evaluate('AtelierLibraryPins.list()')
        assert saved[0]['label'] == expected
        assert saved[1]['label'] == 'Magik materials'
        assert pin_page.evaluate('key => JSON.parse(localStorage.getItem(key)).version', key) == 1
        assert saved[0]['path'] == 'Characters/1015/1015502/Textures'
        checks.append('Nested pins retain hero/skin context across reload and partial metadata; old generic labels migrate, custom labels and v1 paths remain intact')
    finally:
        if not pin_page.is_closed():
            pin_page.evaluate('(args) => args.raw === null ? localStorage.removeItem(args.key) : localStorage.setItem(args.key, args.raw)', {'key': key, 'raw': prior})
            pin_page.close()
