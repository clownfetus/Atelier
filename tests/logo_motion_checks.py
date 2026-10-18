"""Logo startup/ownership checks. Uses original local PNG; never writes project data."""
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
INSTRUMENT = r"""
window.logoEntrances=0; window.logoAnimationOptions=[];
const nativeAnimate=Element.prototype.animate;
Element.prototype.animate=function(frames, options) {
  if (this.classList.contains('am-logo-entrance-stage')) {
    logoEntrances++; logoAnimationOptions.push({frames,options});
  }
  return nativeAnimate.call(this,frames,options);
};
document.addEventListener('DOMContentLoaded',()=>{
  const label=document.querySelector('.studio-brand > span:not([data-atelier-motion])');
  window.logoInitialLabel=label?.getBoundingClientRect().x;
});
"""


def run_logo_motion_checks(page, context, url, report, checks):
    mark = subprocess.run([sys.executable, str(ROOT / 'scripts/brand_mark.py'), '--check'],
                          capture_output=True, text=True)
    assert mark.returncode == 0, mark.stdout + mark.stderr
    checks.append('The A mark vector, interface PNG and application icons match scripts/brand_mark.py')

    tab = context.new_page()
    errors, pending_config, delayed = [], [], []
    tab.on('pageerror', lambda error: errors.append(str(error)))
    tab.add_init_script(INSTRUMENT)
    # Hold the normal application configuration read: startup artwork must not wait.
    tab.route('**/api/config', lambda route: pending_config.append(route))
    try:
        tab.goto(url)
        tab.wait_for_function('window.AtelierLogoEntranceUI && document.querySelector("[data-atelier-motion=logo-entrance]")?.dataset.amReady === "true"')
        tab.wait_for_function('logoEntrances===1')
        tab.wait_for_function('document.querySelector("[data-atelier-motion=logo-entrance]").dataset.amState==="settled"')
        assert tab.evaluate('logoAnimationOptions[0].options.duration') == 320
        assert tab.evaluate('logoAnimationOptions[0].frames.every(frame=>frame.opacity===1)')
        assert tab.evaluate('logoAnimationOptions[0].frames[0].transform') == 'translateY(1px) scale(1.04, 0.94)'
        assert tab.evaluate('logoAnimationOptions[0].frames[1].offset') == .45
        assert tab.evaluate('logoAnimationOptions[0].options.easing') == 'linear'
        assert tab.locator('.studio-brand > img').evaluate('el=>el.naturalWidth>0 && el.hidden')
        assert tab.locator('.studio-brand [data-atelier-motion=logo-entrance]').evaluate('el=>el.getBoundingClientRect().width===32 && el.getBoundingClientRect().height===32 && !el.getAnimations({subtree:true}).length')
        assert tab.evaluate('document.querySelector(".studio-brand > span:not([data-atelier-motion])").getBoundingClientRect().x === logoInitialLabel')
        assert tab.locator('.studio-brand image').get_attribute('href').endswith('/static/brand/atelier-mark.png')
        tab.evaluate("document.documentElement.dataset.theme='light'; AtelierLogoEntranceUI.start(); document.dispatchEvent(new Event('atelier:navigation')); document.dispatchEvent(new Event('atelier:project-changed'))")
        tab.wait_for_timeout(50)
        assert tab.evaluate('logoEntrances') == 1
        tab.screenshot(path=str(report / 'logo-startup-light.png'))
        tab.evaluate("document.documentElement.dataset.theme='dark'")
        tab.wait_for_timeout(250)
        tab.screenshot(path=str(report / 'logo-startup-dark.png'))
        checks.append('Logo entrance runs once independently of pending startup configuration, preserves the original 32px PNG and wordmark position, then releases its effects')

        tab.evaluate(r"""async () => {
          await document.querySelector('.studio-brand > img').decode();
          document.querySelector('.studio-brand').click();
          window.beforeLaunchEntrances = logoEntrances;
          const splash = document.createElement('div'); splash.id = 'startup-splash';
          splash.style = 'position:fixed;top:80px;left:300px';
          splash.innerHTML = '<progress max="10" value="2"></progress>'; document.body.append(splash);
          AtelierSurfaces.startupProgress({total:10,current:2});
          const logo = document.querySelector('.studio-brand [data-atelier-motion=logo-entrance]');
          if (splash.dataset.launch !== 'true' || splash.querySelector('.k-startup-stage')?.dataset.amMicro === 'true')
            throw Error('Launch did not own the stage');
          if (logo.dataset.amState !== 'settled' || logo.getAnimations({subtree:true}).length)
            throw Error('Launch did not hold the topbar entrance');
          document.querySelector('.studio-brand').click();
          if (logoEntrances !== beforeLaunchEntrances) throw Error('Replay competed with launch');
          AtelierSurfaces.startupDone(); splash.remove();
          if (logoEntrances !== beforeLaunchEntrances + 1 || logo.dataset.amState !== 'entering')
            throw Error('Launch did not hand over to the topbar');
          AtelierSurfaces.startupDone();
          if (logoEntrances !== beforeLaunchEntrances + 1) throw Error('Startup completion replayed twice');
        }""")
        tab.wait_for_function('document.querySelector(".studio-brand [data-atelier-motion=logo-entrance]").dataset.amState === "settled"')
        tab.evaluate(r"""() => {
          const before = logoEntrances;
          AtelierLogoEntranceUI.holdStartup();
          Object.defineProperty(document,'hidden',{configurable:true,get:()=>true});
          document.dispatchEvent(new Event('visibilitychange'));
          delete document.hidden; document.dispatchEvent(new Event('visibilitychange'));
          AtelierSurfaces.startupDone();
          if (logoEntrances !== before) throw Error('Hidden launch queued a later entrance');
        }""")
        checks.append('The latest logo stays fully opaque, yields to the Full launch formation, enters once at completion, and discards hidden startup replays')

        tab.evaluate(r"""() => {
          window.logoHost=document.createElement('div');
          logoHost.style.cssText='position:fixed;left:120px;top:160px'; document.body.append(logoHost);
          window.logoHandle=AtelierMotion.logoEntrance.mount(logoHost,{logoSrc:'/static/brand/atelier-mark.png'});
        }""")
        tab.evaluate('logoHandle.ready')
        tab.evaluate(r"""() => {
          logoHandle.setState('entering'); const first=logoHost.getAnimations({subtree:true})[0];
          if (!first) throw Error('No entrance');
          logoHandle.setState('entering');
          if (logoHost.getAnimations({subtree:true})[0]!==first) throw Error('Repeated entering restarted');
          logoHandle.setState('settled');
          if (logoHost.getAnimations({subtree:true}).length || first.playState!=='idle') throw Error('Settle retained animation');
          logoHandle.replay(); logoHandle.setReducedMotion('reduce');
          if (logoHost.getAnimations({subtree:true}).length) throw Error('Forced reduction did not settle');
          logoHandle.setReducedMotion('system'); logoHandle.replay();
          Object.defineProperty(document,'hidden',{configurable:true,get:()=>true});
          document.dispatchEvent(new Event('visibilitychange'));
          if (logoHost.getAnimations({subtree:true}).length) throw Error('Hidden entrance did not settle');
          delete document.hidden; document.dispatchEvent(new Event('visibilitychange'));
          if (logoHost.getAnimations({subtree:true}).length) throw Error('Visibility replayed entrance');
          const previous=logoHandle;
          logoHandle=AtelierMotion.logoEntrance.mount(logoHost,{logoSrc:'/static/brand/atelier-mark.png'});
          previous.destroy(); previous.replay();
          if (logoHost.querySelectorAll('svg').length!==1) throw Error('Replacement ownership broken');
        }""")
        tab.evaluate('logoHandle.ready')
        tab.emulate_media(reduced_motion='reduce')
        tab.evaluate("logoHandle.setReducedMotion('system'); logoHandle.replay()")
        assert tab.locator('[data-atelier-motion=logo-entrance]').last.evaluate('el=>el.getAnimations({subtree:true}).length') == 0
        tab.emulate_media(reduced_motion='no-preference')
        tab.evaluate(r"""() => {
          const original=Element.prototype.animate;
          try {
            for (const mode of ['missing','throwing','partial']) {
              Element.prototype.animate=mode==='missing' ? undefined : function(...args) {
                if (mode==='throwing') throw Error('Fixture WAAPI failure');
                const animation=original.apply(this,args);
                Object.defineProperty(animation,'finished',{get(){throw Error('Fixture partial WAAPI failure');}});
                return animation;
              };
              logoHandle.replay();
              if (logoHost.getAnimations({subtree:true}).length) throw Error('Failure retained effects');
              if (getComputedStyle(logoHost.querySelector('.am-logo-entrance-stage')).opacity!=='1') throw Error('Failure hid logo');
            }
          } finally { Element.prototype.animate=original; }
          let rejected=false; try {logoHandle.setState('toString');} catch(_) {rejected=true;}
          if (!rejected) throw Error('Inherited state accepted');
          logoHandle.destroy(); logoHandle.destroy(); logoHandle.replay();
          logoHost.textContent='Caller owns this';
          try {AtelierMotion.logoEntrance.mount(logoHost,{logoSrc:'/static/brand/atelier-mark.png'});} catch(_) {}
          if (logoHost.textContent!=='Caller owns this') throw Error('Occupied host erased');
          logoHost.remove();
        }""")
        checks.append('Logo controller deduplicates entrances, interrupts/reduces/settles safely, preserves host ownership and survives missing, throwing and partially failing WAAPI')

        tab.route('**/fixture/logo-missing.png', lambda route: route.abort('failed'))
        tab.evaluate(r"""() => {
          window.failedHost=document.createElement('div');document.body.append(failedHost);
          window.logoLoadErrors=0;
          window.failedLogo=AtelierMotion.logoEntrance.mount(failedHost,{logoSrc:'/fixture/logo-missing.png',onError:()=>logoLoadErrors++});
          window.logoFailure=failedLogo.ready.then(()=>false,()=>true);
        }""")
        assert tab.evaluate('logoFailure')
        assert tab.evaluate('logoLoadErrors') == 1
        assert tab.evaluate('failedHost.querySelectorAll("svg").length') == 0
        tab.route('**/fixture/logo-pending.png', lambda route: delayed.append(route))
        tab.evaluate(r"""() => {
          failedLogo.destroy(); failedHost.remove();
          window.pendingHost=document.createElement('div'); document.body.append(pendingHost);
          window.pendingLogo=AtelierMotion.logoEntrance.mount(pendingHost,{logoSrc:'/fixture/logo-pending.png'});
          window.logoDestroyedReady=pendingLogo.ready.then(()=>false,()=>true);
          pendingLogo.destroy(); pendingHost.remove();
        }""")
        assert tab.evaluate('logoDestroyedReady')
        tab.wait_for_timeout(50)
        for route in delayed:
            route.abort()
        delayed.clear()
        tab.evaluate("AtelierLogoEntranceUI.destroy(); window.dispatchEvent(new Event('pagehide'))")
        assert tab.locator('.studio-brand > img').evaluate('el=>!el.hidden && getComputedStyle(el).display!=="none"')
        assert tab.locator('.studio-brand [data-atelier-motion=logo-entrance]').count() == 0
        assert not errors, errors
        checks.append('Logo load errors reject readiness safely; destroy settles pending readiness and page teardown restores the original fallback without leaked SVG')
    finally:
        for route in pending_config + delayed:
            try:
                route.abort()
            except Exception:
                pass
        tab.unroute_all(behavior='ignoreErrors')
        tab.close()

    for mode in ('hidden', 'reduced', 'missing-waapi', 'missing-controller', 'png-error'):
        quiet = context.new_page()
        quiet.add_init_script(INSTRUMENT)
        if mode == 'hidden':
            quiet.add_init_script("Object.defineProperty(document,'hidden',{configurable:true,get:()=>true});")
        elif mode == 'reduced':
            quiet.emulate_media(reduced_motion='reduce')
        elif mode == 'missing-waapi':
            quiet.add_init_script('Element.prototype.animate=undefined;')
        elif mode == 'missing-controller':
            quiet.route('**/static/motion/logo-entrance.js', lambda route: route.fulfill(body='',content_type='text/javascript'))
        elif mode == 'png-error':
            quiet.route('**/static/brand/atelier-mark.png', lambda route: route.abort('failed'))
        try:
            quiet.goto(url)
            quiet.wait_for_function('window.AtelierLogoEntranceUI')
            quiet.wait_for_timeout(100)
            assert quiet.evaluate('logoEntrances') == 0, mode
            assert quiet.locator('.studio-brand > img').evaluate('el=>!el.hidden && getComputedStyle(el).display!=="none"'), mode
            if mode == 'hidden':
                quiet.evaluate("delete document.hidden; document.dispatchEvent(new Event('visibilitychange')); AtelierLogoEntranceUI.start()")
                assert quiet.evaluate('logoEntrances') == 0
        finally:
            quiet.unroute_all(behavior='ignoreErrors')
            quiet.close()
    checks.append('Hidden/reduced-motion startup, absent animation/controller and PNG failures keep the static fallback and never replay on later visibility')
