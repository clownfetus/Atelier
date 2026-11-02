"""Existing Library suites enter through Projects without changing production startup."""


def enter_library_on_startup(context, *, heroes_open=True):
    # Existing roster/artwork suites exercise an explicitly enabled Heroes view.
    # Preference coverage passes False to exercise the real, folders-first default.
    if heroes_open:
        context.add_init_script("if(localStorage.getItem('atelier.homeHeroesOpen')===null)localStorage.setItem('atelier.homeHeroesOpen','1');")
    context.add_init_script("""document.addEventListener('DOMContentLoaded',()=>{
      const enter=()=>{
        const button=document.getElementById('proj-library-btn');
        if(window.AtelierWorkspace && window.atelierProject?.() && button && !button.hidden && document.getElementById('project-overlay').classList.contains('active')) {
          observer.disconnect();button.click();
        }
      };
      const observer=new MutationObserver(enter);
      observer.observe(document.body,{subtree:true,attributes:true,childList:true});enter();
    });""")
