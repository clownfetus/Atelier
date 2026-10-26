"""Exercise automatic idle fallback, manual choices and cancelled model loads."""


def run_idle_selection_checks(context, url, report, checks):
    tab = context.new_page()
    errors, requests, held = [], [], []
    tab.on('pageerror', lambda error: errors.append(str(error)))
    bad, good = 'Characters/1031/Idle_N', 'Characters/1031/Lobby_Stand_Idle'
    mode = {'value': 'fallback'}
    tab.route('**/idle-selection-fixture', lambda route: route.fulfill(content_type='text/html', body='''
        <script type="importmap">{"imports":{"three":"/static/vendor/three/three.module.min.js"}}</script>
        <button id="viewport-play"></button><select id="viewport-animation"></select>'''))
    tab.route('**/api/idle_animations?*', lambda route: route.fulfill(json={'ok': True, 'animations': [
        {'label': 'Normal idle', 'game_rel': bad}, {'label': 'Lobby idle', 'game_rel': good}]}))

    def decode(route):
        selected = route.request.post_data_json['animation_rel']
        requests.append(selected)
        if mode['value'] == 'hold':
            held.append(route)
        elif selected == bad or mode['value'] == 'fail':
            route.fulfill(json={'ok': False, 'error': 'Animation skeleton is incompatible: fixture'})
        else:
            route.fulfill(json={'ok': True, 'version': 2, 'space': 'atelier-gltf-local', 'name': 'Compatible idle',
                'duration': 1, 'tracks': [{'bone': 'spine', 'times': [0, 1],
                    'positions': [0, 0, 0, 0, 1, 0], 'rotations': [0, 0, 0, 1, 0, 0, 0, 1],
                    'scales': [1, 1, 1, 1, 1, 1]}]})
    tab.route('**/api/idle_animation', decode)
    try:
        tab.goto(url + '/idle-selection-fixture')
        tab.evaluate('''async () => {
            const THREE = await import('three');
            const {createViewportAnimation} = await import('/static/viewport-animation.js');
            const root = new THREE.Group(), bone = new THREE.Bone(); bone.name = 'spine'; root.add(bone);
            window.idleNotices = []; window.idleBone = bone;
            window.idleController = createViewportAnimation({objects:()=>[{root}], frame:()=>{},
                fetch:window.fetch.bind(window), notify:message=>idleNotices.push(message)});
        }''')
        tab.evaluate('void idleController.discover("Characters/1031/Mesh")')
        tab.wait_for_function('document.getElementById("viewport-play").getAttribute("aria-pressed") === "true"')
        assert requests == [bad, good]
        assert tab.locator('#viewport-animation').input_value() == good
        assert tab.evaluate('idleNotices') == []
        tab.evaluate('idleController.update(.5)')
        assert tab.evaluate('idleBone.position.y') > .1
        tab.locator('#viewport-animation').select_option('')
        assert tab.evaluate('idleBone.position.y') == 0
        checks.append('An incompatible preferred idle falls back to a verified full-body clip, animates real Three.js bones and restores the rest pose')

        requests.clear()
        tab.evaluate('idleController.reset(); void idleController.discover("Characters/1031/Mesh")')
        tab.wait_for_function('document.getElementById("viewport-play").getAttribute("aria-pressed") === "true"')
        assert requests == [good]
        checks.append('Reopening a model tries its previously verified idle first, avoiding repeated incompatible decodes')

        requests.clear()
        tab.locator('#viewport-animation').select_option(bad)
        tab.wait_for_function('idleNotices.length === 1')
        assert requests == [bad]
        assert tab.locator('#viewport-animation').input_value() == bad
        checks.append('An explicitly chosen incompatible idle reports its failure without silently changing the selected animation')

        requests.clear()
        tab.evaluate('idleController.reset(); idleNotices.length = 0')
        mode['value'] = 'hold'
        tab.evaluate('void idleController.discover("Characters/1031/OldMesh")')
        tab.wait_for_timeout(100)
        assert len(held) == 1
        tab.evaluate('idleController.reset()')
        held[0].fulfill(json={'ok': False, 'error': 'Animation skeleton is incompatible: old model'})
        tab.wait_for_timeout(100)
        assert requests == [bad]
        assert tab.evaluate('idleNotices') == []
        assert tab.locator('#viewport-animation option').count() == 1
        checks.append('Changing models cancels automatic idle fallback and suppresses stale errors')

        mode['value'] = 'fail'
        requests.clear()
        tab.evaluate('void idleController.discover("Characters/1031/UnsupportedMesh")')
        tab.wait_for_function('idleNotices.length === 1 && !idleController.loading()')
        assert requests == [bad, good]
        assert not errors, errors
        checks.append('If all listed idles are incompatible, playback stops and one clear warning is shown')
    finally:
        tab.close()
