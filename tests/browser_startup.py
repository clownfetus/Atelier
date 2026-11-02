"""Existing Library suites enter through Projects without changing production startup."""


def enter_library_on_startup(context):
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
