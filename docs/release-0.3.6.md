# Atelier 0.3.6 release preparation

This update includes the contextual Model Studio, original/edited texture loading,
looping idle playback, mesh replacement import with default-on skeleton, weight
and morph preservation, texture mip repair and the requested library polish.

Local verification: 22 backend suites; final focused mesh/morph/packaging checks;
packaged WebView2 import controls; native preservation enabled and disabled;
independently extracted cooked mod with all 38 original morph identities and both
available LODs; independent CUE4Parse decoding; actual Three.js morph deformation.
Earlier browser regression and native material/idle results remain applicable.
In-game animation quality on substantially changed faces requires manual review.

The release-candidate workflow builds the committed source on native Windows and
Linux runners. Tool seeds are hash pinned and contain no keys, mappings, projects
or game packages. Windows installer checks run only on disposable Windows 2022
and 2025 runners and cover installation, running upgrade, reinstall and uninstall.
The Linux job builds an AppImage and checks its native startup with isolated data.
Linux's Wine-dependent modding tools still require the dependencies in LINUX.md.

The 0.3.6 release remains a draft during preparation. Build artifacts and workflow
results must pass before updating main. Publishing the draft to the stable update
channel is a separate action; this workflow does not publish releases or move main.
