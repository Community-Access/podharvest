"""Teach accessible_output2 where PyInstaller 6 actually puts its data.

Without this, spoken announcements fail in exactly the way that is hardest
to notice: `accessible_output2` imports cleanly, every output class is
present, and then nothing is ever said, because the screen reader client
DLL it wants to load is not where it looked.

The mismatch is a version difference. `accessible_output2.load_library`
asks `platform_utils.paths.embedded_data_path()` for the data folder, and
that function returns *the executable's directory* -- which was right for
py2exe and for PyInstaller 5, where bundled data sat beside the exe.
PyInstaller 6 moved it: onedir builds now put everything in an `_internal`
subfolder, and `sys._MEIPASS` points there. So the loader looks in
`podharvest/accessible_output2/lib/` while the file is in
`podharvest/_internal/accessible_output2/lib/`, and `ctypes.windll[...]`
raises on a path that does not exist.

Verified against the built app before this hook existed: the folder simply
was not beside the exe.

A runtime hook is the right place for the correction because it runs before
any application code, so the patched function is in place no matter which
import first reaches for a library. Failure here is swallowed on purpose --
this is a fix-up for one optional feature, and it must never stop podHarvest
starting.
"""

import os
import sys


def _point_at_the_bundle() -> None:
    data_dir = getattr(sys, "_MEIPASS", None)
    if not data_dir:
        return
    try:
        from platform_utils import paths
    except Exception:      # noqa: BLE001 - announcements simply stay silent
        return
    # Only redirect when the library really is in the bundle, so a build
    # that did not ship it keeps whatever behaviour it had.
    if not os.path.isdir(os.path.join(data_dir, "accessible_output2", "lib")):
        return
    paths.embedded_data_path = lambda: data_dir


_point_at_the_bundle()
