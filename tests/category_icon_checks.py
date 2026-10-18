"""Real card/category artwork and shared home-shortcut colors in both themes."""
from pathlib import Path
import xml.etree.ElementTree as ET


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
            'Meshes', 'Text', 'Nameplates', 'Plugins', 'Weapons',
            'Animation', 'Audio', 'Maps', 'Lights', 'Blueprints', 'AI', 'AbilitySystem',
            'Chaos', 'Controls', 'Data', 'ArtTools', 'Environment', 'Font', 'Movies',
            'L10N', 'Functions', 'Statistics', 'Pipelines', 'DefaultAssets', 'Marvel_Encrypt',
            'MobileResources', 'VREditor', 'BasicShapes', 'EngineSky', 'Deformers', 'Prototype'];
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
            'animation-folder-icon': ('Animation', 'Animations', 'ANIMATIONS', 'AnimSequences', 'BlendSpaces'),
            'audio-folder-icon': ('Audio', 'AudioBanks', 'Cues', 'SoundCue', 'EngineSounds', 'Wwise'),
            'map-folder-icon': ('Maps', 'MapTemplates', 'OpenWorldTemplate', 'Levels', 'Worlds'),
            'light-folder-icon': ('Lights', 'Lighting', 'EngineLightProfiles'),
            'material-folder-icon': ('EngineMaterials', 'MaterialFunctions'),
            'environment-folder-icon': ('EnvironmentHydraC', 'EditorLandscapeResources', 'SpeedTree9'),
            'movie-folder-icon': ('Movies_Activity', 'Movies_Level', 'MoviesBink'),
            'resources-folder-icon': ('EngineResources', 'EditorResources', 'Marvel_LQ'),
        }
        for expected, names in category_aliases.items():
            for name in names:
                assert icon_page.evaluate('(name)=>folderIconCls(name)', name) == expected, name
        # A category word inside a custom folder/skin name must not steal its identity.
        for name in ('Miscellaneous', 'Unsorted Assets', 'Audio Notes', 'MapsBackup', 'AnimationsOld',
                     'My Weapons', '1015502', '502', 'GODDESS OF THUNDER', '', None):
            assert icon_page.evaluate('(name)=>folderIconCls(name)', name) == 'folder-icon', name
        assert icon_page.evaluate("ICON_CLS_TO_LUCIDE['weapon-folder-icon']") == 'swords'
        weapon = icon_page.locator('#grid-area .card .weapon-folder-icon')
        assert weapon.get_attribute('data-lucide') == 'swords'
        artwork = ET.parse(Path(__file__).resolve().parents[1] / 'gui/motion/category-emblems/weapon-folder-icon-102.svg')
        expected = artwork.find(".//{*}g[@class='k-category-emblem-energy']/{*}path").attrib['d']
        assert weapon.locator('.k-category-emblem-energy path').get_attribute('d') == expected
        assert weapon.get_attribute('aria-hidden') == 'true'
        assert weapon.get_attribute('focusable') == 'false'
        assert weapon.locator('path').count() > 0
        bounds = weapon.evaluate("""el => {
          const b=el.getBoundingClientRect(), thumb=el.closest('.card-thumb').getBoundingClientRect();
          const p=el.getBBox();
          return {slot:b.width, painted:p.width*b.width/el.viewBox.baseVal.width,
            clipped:b.left<thumb.left || b.right>thumb.right || b.top<thumb.top || b.bottom>thumb.bottom};
        }""")
        assert 100 <= bounds['slot'] <= 104 and bounds['painted'] >= 80 and not bounds['clipped'], bounds
        assert icon_page.evaluate("['pin','pin-off'].every(name=>!!AtelierSymbolPaths[name]?.body)")
        checks.append('Category aliases resolve case-insensitively without matching custom folder/skin substrings; weapons retain full-size accessible crossed swords')

        for theme in ('light', 'dark'):
            icon_page.locator('#settings-theme').select_option(theme, force=True)
            measurements = icon_page.evaluate("""() => {
              const lum = rgb => rgb.match(/[\\d.]+/g).slice(0,3).map(Number).map(v=>v/255)
                .map(v=>v<=.04045?v/12.92:((v+.055)/1.055)**2.4)
                .reduce((sum,v,i)=>sum+v*[.2126,.7152,.0722][i],0);
              return [...document.querySelectorAll('#grid-area .card .card-icon')].map(el=>{
                const energy=el.querySelector('.k-category-emblem-energy > *');
                const color=energy?getComputedStyle(energy).fill:getComputedStyle(el).color;
                const bg=getComputedStyle(el.closest('.card-thumb')).backgroundColor;
                const a=lum(color), b=lum(bg), cls=Object.keys(ICON_CLS_TO_LUCIDE).find(c=>el.classList.contains(c));
                const chip=document.querySelector(`#category-icon-chips [data-category="${cls}"] svg`);
                const chipEnergy=chip.querySelector('.k-category-emblem-energy > *');
                return {cls,color,emblem:!!energy,ratio:(Math.max(a,b)+.05)/(Math.min(a,b)+.05),
                  chipColor:chipEnergy?getComputedStyle(chipEnergy).fill:getComputedStyle(chip).color, chipSize:chip.getBoundingClientRect().width,
                  slot:el.getBoundingClientRect().width,
                  cardWidth:el.closest('.card').getBoundingClientRect().width,
                  thumbWidth:el.closest('.card-thumb').getBoundingClientRect().width};
              });
            }""")
            assert len(measurements) == 39, measurements
            assert len({m['color'] for m in measurements}) >= 36, measurements
            assert all(m['ratio'] >= (3 if m['emblem'] else 4.5) for m in measurements), (theme, measurements)
            assert all(100 <= m['slot'] <= 104 and m['cardWidth'] == 156 and m['thumbWidth'] == 134
                       for m in measurements), measurements
            assert all(m['color'] == m['chipColor'] and m['chipSize'] == 18 for m in measurements), measurements
            aliases = icon_page.evaluate("""() => {
              const pairs = [['texture-folder-icon','texture-icon'], ['vfx-folder-icon','vfx-icon'],
                ['material-folder-icon','material-icon'], ['mesh-folder-icon','mesh-icon'], ['text-folder-icon','text-icon']];
              return pairs.map(pair=>pair.map(cls=>{
                const probe=document.createElement('span'); probe.className=`card-icon ${cls}`;
                document.body.append(probe); const color=getComputedStyle(probe).color; probe.remove(); return color;
              }));
            }""")
            assert all(a == b for a, b in aliases), aliases
            icon_page.screenshot(path=str(report / f'category-icons-{theme}.png'), animations='disabled')
        assert not errors, errors
        checks.append('All 39 icon types retain large preview slots; the 36 category emblems reach 3:1 in both themes, and 18px home chips share category colors')
    finally:
        icon_page.close()
