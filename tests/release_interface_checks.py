"""Release coverage for identity and preferences previously run only by hand."""
from types import SimpleNamespace


def run_release_interface_checks(page, context, browser, url, report, checks):
    from home_layout_checks import run_home_layout_checks
    from catalogue_identity_checks import run_catalogue_identity_checks
    from app_colour_identity_checks import synthetic
    from app_colour_home_checks import run as home

    run_home_layout_checks(page, context, url, report, checks)
    run_catalogue_identity_checks(context, url, report, checks)
    args = SimpleNamespace(base_url=url)
    errors, results = [], []
    for custom in (False, True):
        for theme in ('light', 'dark'):
            synthetic(browser, args, report, results, errors, theme, custom)
            results.append(home(browser, args, report, errors, theme, custom))
    assert not errors, errors
    checks.extend(row['check'] + (' (' + row['palette'] + ')' if 'palette' in row else '')
                  for row in results)
