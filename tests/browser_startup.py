"""Library suites use production startup with an optional Heroes preference."""


def enter_library_on_startup(context, *, heroes_open=True):
    # Existing roster/artwork suites exercise an explicitly enabled Heroes view.
    # Preference coverage passes False to exercise the real, folders-first default.
    if heroes_open:
        context.add_init_script("if(localStorage.getItem('atelier.homeHeroesOpen')===null)localStorage.setItem('atelier.homeHeroesOpen','1');")
