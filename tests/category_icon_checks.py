"""Real card/category artwork and shared home-shortcut colors in both themes."""
from pathlib import Path
import xml.etree.ElementTree as ET

ROOT = Path(__file__).resolve().parents[1]


def run_category_icon_checks(page, context, url, report, checks):
    icon_page = context.new_page()
    errors = []
    icon_page.on('pageerror', lambda error: errors.append(str(error)))
    try:
        icon_page.goto(url)
        icon_page.wait_for_selector('#grid-area .card')
        icon_page.set_viewport_size({'width': 1575, 'height': 884})
        icon_page.evaluate("""() => {
          nav = {path: 'Icon checks'};
          document.getElementById('search-input').value = '';
          const folders = ['Miscellaneous', 'Characters', 'UI', 'Textures', 'VFX', 'Materials',
            'Meshes', 'Text', 'Nameplates', 'Plugins', 'Weapons', 'Maps', 'Blueprints', 'AbilitySystem',
            'Data', 'Environment', 'L10N'];
          const cards = folders.map(name => _makeCard({type:'folder', name, rel_path:`Icon checks/${name}`}));
          cards.push(_makeCard({type:'asset', name:'Curves', file_type:'curve', game_rel:'Icon checks/Curve'}));
          cards.push(_makeCard({type:'asset', name:'Other', file_type:'other', game_rel:'Icon checks/Other'}));
          buildGrid(cards);
          // Shortcuts use these same production classes, independent of thumbnail layout.
          const chips = document.createElement('div');
          chips.id = 'category-icon-chips';
          for (const card of cards) {
            const chip = document.createElement('button');
            chip.className = 'library-pin-open'; chip.dataset.category = card.iconCls;
            const glyph = makeIcon(card); glyph.setAttribute('size', '18');
            chip.append(glyph); chips.append(chip);
          }
          document.getElementById('grid-area').append(chips);
          lucide.createIcons({nodes:[chips]});
        }""")
        for name in ('Weapon', 'Weapons', 'WEAPONS'):
            assert icon_page.evaluate('(name)=>folderIconCls(name)', name) == 'weapon-folder-icon'
        category_aliases = {
            'char-icon': ('Characters', 'NPC', 'NPCS'),
            'ui-folder-icon': ('UI', 'Icon', 'ICONS'),
            'texture-folder-icon': ('Texture', 'TEXTURES'),
            'material-folder-icon': ('Material', 'MATERIALS'),
            'mesh-folder-icon': ('Mesh', 'MESHES'),
            'vfx-folder-icon': ('VFX', 'Effect', 'Effects'),
            'ability-folder-icon': ('Abilities', 'Ability', 'AbilitySystem'),
            'environment-folder-icon': ('Environment', 'Landscape', 'Landscapes', 'Foliage'),
            'blueprint-folder-icon': ('Blueprint', 'Blueprints'),
            'plugin-folder-icon': ('Plugin', 'Plugins'),
            'nameplate-folder-icon': ('Nameplate', 'Nameplates'),
            'data-folder-icon': ('Data',),
            'text-folder-icon': ('Text', 'StringTable', 'StringTables'),
            'language-folder-icon': ('L10N', 'Localization', 'Localisation'),
            'map-folder-icon': ('Map', 'Maps'),
        }
        for expected, names in category_aliases.items():
            for name in names:
                assert icon_page.evaluate('(name)=>folderIconCls(name)', name) == expected, name
        # A category word inside a custom folder/skin name must not steal its identity.
        # So must a name the modder has no reason to open (D9): these earn the plain folder.
        for name in ('Miscellaneous', 'Unsorted Assets', 'Audio Notes', 'MapsBackup', 'AnimationsOld',
                     'My Weapons', '1015502', '502', 'GODDESS OF THUNDER', '', None,
                     'Audio', 'Wwise', 'Animation', 'Lights', 'Controls', 'Physics', 'AI', 'Fonts', 'Movies',
                     'Functions', 'Statistics', 'Pipelines', 'Resources', 'Marvel_Encrypt', 'MobileResources',
                     'VREditor', 'Shapes', 'Sky', 'Deformers', 'Prototypes', 'Tools', 'EngineMaterials',
                     'MaterialFunctions', 'Levels', 'Worlds', 'DataTable', 'EngineMeshes', 'SpeedTree9'):
            assert icon_page.evaluate('(name)=>folderIconCls(name)', name) == 'folder-icon', name
        assert icon_page.evaluate("ICON_CLS_TO_LUCIDE['weapon-folder-icon']") == 'swords'
        weapon = icon_page.locator('#grid-area .card .weapon-folder-icon')
        assert weapon.get_attribute('data-lucide') == 'swords'
        artwork = ET.parse(ROOT / 'gui/brand/emblems/weapon-folder-icon-master.svg')
        expected = [path.attrib['d'] for path in artwork.findall('.//{*}path')]
        assert weapon.evaluate("el=>[...el.querySelectorAll('path')].map(path=>path.getAttribute('d'))") == expected
        assert weapon.get_attribute('aria-hidden') == 'true'
        assert weapon.get_attribute('focusable') == 'false'
        assert weapon.locator('path').count() > 0
        bounds = weapon.evaluate("""el => {
          const b=el.getBoundingClientRect(), thumb=el.closest('.card-thumb').getBoundingClientRect();
          const p=el.getBBox();
          return {painted:p.width*b.width/el.viewBox.baseVal.width,
            clipped:b.left<thumb.left || b.right>thumb.right || b.top<thumb.top || b.bottom>thumb.bottom};
        }""")
        assert bounds['painted'] >= 80 and not bounds['clipped'], bounds
        assert icon_page.evaluate("['pin','pin-off'].every(name=>!!AtelierSymbolPaths[name]?.body)")
        # Compare what ships with the approved SVGs. Regenerating curved paths depends on platform math.
        approved = ROOT / 'docs/motion-v2/assets/emblems'
        drawings = sorted(approved.glob('*.svg'))
        assert len(drawings) == 34, drawings
        for path in drawings:
            svg = path.read_text(encoding='utf-8')
            assert (ROOT / 'gui/brand/emblems' / path.name).read_text(encoding='utf-8') == svg, path.name
            name, variant = path.stem.rsplit('-', 1)
            size = 32 if variant == 'master' else 18
            markup = icon_page.evaluate('([name, size]) => AtelierFolderEmblems.markup(name, size)', [name, size])
            assert markup == svg.split('>', 1)[1].rsplit('</svg>', 1)[0], path.name
        plain_folder = ET.parse(approved / 'folder-icon-master.svg')
        plain_paths = [path.attrib['d'] for path in plain_folder.findall('.//{*}path')]
        assert icon_page.locator('#folder-plain-template').evaluate(
            "template => [...template.content.querySelectorAll('path')].map(path => path.getAttribute('d'))"
        ) == plain_paths
        checks.append('Folder rules match whole names case-insensitively and give dropped categories the plain folder; packaged and inline icons match the approved drawings and stay accessible')

        for theme in ('light', 'dark'):
            icon_page.locator('#settings-theme').select_option(theme, force=True)
            measurements = icon_page.evaluate("""() => {
              const lum = rgb => rgb.match(/[\\d.]+/g).slice(0,3).map(Number).map(v=>v/255)
                .map(v=>v<=.04045?v/12.92:((v+.055)/1.055)**2.4)
                .reduce((sum,v,i)=>sum+v*[.2126,.7152,.0722][i],0);
              return [...document.querySelectorAll('#grid-area .card .card-icon')].map(el=>{
                const emblem=el.matches('[data-emblem],svg.folder-icon');
                const style=getComputedStyle(el);
                const color=style.color;
                const bg=getComputedStyle(el.closest('.card-thumb')).backgroundColor;
                const a=lum(color), b=lum(bg), cls=Object.keys(ICON_CLS_TO_LUCIDE).find(c=>el.classList.contains(c));
                const chip=document.querySelector(`#category-icon-chips [data-category="${cls}"] svg`);
                return {cls,color,emblem,ratio:(Math.max(a,b)+.05)/(Math.min(a,b)+.05),
                  chipColor:getComputedStyle(chip).color, chipEmblem:chip.getAttribute('data-emblem'), chipSize:chip.getBoundingClientRect().width,
                  slot:el.getBoundingClientRect().width, plate:style.backgroundColor,
                  glyphWidth:el.getBoundingClientRect().width-parseFloat(style.paddingLeft)-parseFloat(style.paddingRight),
                  cardWidth:el.closest('.card').getBoundingClientRect().width,
                  thumbWidth:el.closest('.card-thumb').getBoundingClientRect().width};
              });
            }""")
            assert len(measurements) == 19, measurements
            # Only texture, mesh and material carry colour; the other fourteen emblems share one neutral (D2).
            colours = {m['cls']: m['color'] for m in measurements if m['emblem']}
            coloured = {cls: colours.pop(cls) for cls in ('texture-folder-icon', 'mesh-folder-icon', 'material-folder-icon')}
            assert len(colours) == 14 and len(set(colours.values())) == 1, colours
            assert len({*coloured.values(), *colours.values()}) == 4, (coloured, colours)
            assert all(m['chipEmblem'] == m['cls'] for m in measurements if m['emblem']), measurements
            assert all(m['ratio'] >= (3 if m['emblem'] else 4.5) for m in measurements), (theme, measurements)
            # File outlines have a smaller tonal plate. Folder artwork fills 76% of the thumbnail.
            file_types = {'curve-icon', 'unhandled-icon'}
            assert all(abs(m['slot'] - m['thumbWidth'] * (.64 if m['cls'] in file_types else .76)) < .02
                       and m['cardWidth'] == 156 and m['thumbWidth'] == 130 for m in measurements), measurements
            assert all(m['glyphWidth'] >= 32 and m['plate'] not in {'transparent', 'rgba(0, 0, 0, 0)'}
                       for m in measurements if m['cls'] in file_types), measurements
            assert all(m['color'] == m['chipColor'] and m['chipSize'] == 18 for m in measurements), measurements
            # File glyphs are thin, so on light themes they take a deeper value than the solid emblem.
            glyphs = icon_page.evaluate("""() => {
              const paint = (cls, token) => {
                const probe = document.createElement('span'); probe.className = `card-icon ${cls}`;
                const expected = document.createElement('span'); expected.style.color = `var(${token})`;
                document.body.append(probe, expected);
                const result = [getComputedStyle(probe).color, getComputedStyle(expected).color];
                probe.remove(); expected.remove(); return result;
              };
              return [paint('texture-icon', '--studio-icon-texture'), paint('mesh-icon', '--studio-icon-mesh'),
                paint('material-icon', '--studio-icon-material'), paint('vfx-icon', '--studio-icon-neutral'),
                paint('curve-icon', '--studio-icon-neutral'), paint('text-icon', '--studio-icon-neutral')];
            }""")
            assert all(a == b for a, b in glyphs), glyphs
            icon_page.screenshot(path=str(report / f'category-icons-{theme}.png'), animations='disabled')
        assert not errors, errors
        checks.append('All 17 folder icons and the file glyphs read on their plates in both themes; only texture, mesh and material carry colour, and 18px home chips use the small drawing in the same colour')
    finally:
        icon_page.close()
