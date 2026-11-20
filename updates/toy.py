"""547: a toy app for Velopack's AppImage round trip. Not Polyglotic's code.

Runs Velopack's hooks first, notes where it runs from (the AppImage, its
mount and the mount's type, the processes that started it) as one JSON line
in a marker file, then either:
- `--update FEED`: looks in the local folder FEED, downloads and applies the
  update, restarting into it (Velopack's own apply-and-restart);
- `--check FEED`: only looks; or
- shows a small Qt window for about a second and quits.
"""

from __future__ import annotations

import json
import os
import platform
import sys
import time
import traceback
from pathlib import Path

import velopack

from toy_version import VERSION

MARKER = Path(
    os.environ.get("TOY547_MARKER", str(Path.home() / "toy547" / "marker.jsonl"))
)


def note(event: str, **kw: object) -> None:
    MARKER.parent.mkdir(parents=True, exist_ok=True)
    record = {"t": round(time.time(), 3), "pid": os.getpid(), "version": VERSION, "event": event, **kw}
    line = json.dumps(record)
    with MARKER.open("a") as f:
        f.write(line + "\n")
    print("toy547", line, flush=True)


def mount_of(path: str) -> dict[str, str]:
    """The mount `path` is on: its mount point, type and source."""
    best = {"point": "", "type": "", "source": ""}
    try:
        with open("/proc/self/mountinfo") as f:
            for line in f:
                parts = line.split()
                point = parts[4]
                sep = parts.index("-")
                inside = path == point or path.startswith(point.rstrip("/") + "/")
                if inside and len(point) >= len(best["point"]):
                    best = {"point": point, "type": parts[sep + 1], "source": parts[sep + 2]}
    except (OSError, ValueError, IndexError):
        pass
    return best


def cmdline(pid: int) -> str:
    try:
        return Path(f"/proc/{pid}/cmdline").read_bytes().replace(b"\0", b" ").decode(errors="replace").strip()
    except OSError:
        return ""


def parent_of(pid: int) -> int:
    try:
        stat = Path(f"/proc/{pid}/stat").read_text()
        return int(stat.rsplit(")", 1)[1].split()[1])
    except (OSError, ValueError, IndexError):
        return 0


def ancestry() -> list[str]:
    out, pid = [], os.getppid()
    for _ in range(4):
        if pid <= 1:
            break
        out.append(f"{pid}: {cmdline(pid)[:200]}")
        pid = parent_of(pid)
    return out


def own_packages() -> velopack.VelopackLocatorConfig:
    """Velopack's own paths for this AppImage, but the downloaded packages in
    this user's cache instead of the shared /var/tmp/velopack/<id>/packages."""
    appdir = os.environ["APPDIR"]
    cache = Path(os.environ.get("XDG_CACHE_HOME", str(Path.home() / ".cache"))) / "toy547" / "packages"
    cache.mkdir(parents=True, exist_ok=True)
    return velopack.VelopackLocatorConfig(
        RootAppDir=os.environ["APPIMAGE"],
        UpdateExePath=f"{appdir}/usr/bin/UpdateNix",
        PackagesDir=str(cache),
        ManifestPath=f"{appdir}/usr/bin/sq.version",
        CurrentBinaryDir=f"{appdir}/usr/bin",
        IsPortable=False,
    )


def manager(feed: str) -> velopack.UpdateManager:
    if "--own-packages" in sys.argv:
        locator = own_packages()
        note("locator", packages=str(locator.PackagesDir))
        return velopack.UpdateManager(feed, None, locator)
    try:
        return velopack.UpdateManager(feed)
    except TypeError:
        return velopack.UpdateManager(feed, velopack.UpdateOptions(
            AllowVersionDowngrade=False, MaximumDeltasBeforeFallback=10, ExplicitChannel=None))


def update(feed: str, check_only: bool = False) -> int:
    try:
        um = manager(feed)
        try:
            current = str(um.get_current_version())
        except Exception as e:  # noqa: BLE001 - only noted
            current = f"? {e!r}"
        note("manager", current=current)
        info = um.check_for_updates()
        if not info:
            note("no-update")
            return 0
        note("found", info=repr(info)[:600])
        if check_only:
            return 0
        um.download_updates(info)
        note("downloaded")
        note("applying")
        um.apply_updates_and_restart(info)
        time.sleep(5)
        note("still-running-after-apply")
        return 4
    except Exception as e:  # noqa: BLE001 - the probe reports it
        note("error", error=repr(e), tb=traceback.format_exc()[-1500:])
        return 3


def window() -> int:
    from PySide6.QtCore import QTimer
    from PySide6.QtGui import QFontDatabase, QFontInfo
    from PySide6.QtWidgets import QApplication, QLabel

    app = QApplication(sys.argv)
    label = QLabel(f"toy547 {VERSION}")
    label.resize(240, 60)
    label.show()
    QTimer.singleShot(1200, app.quit)
    app.exec()
    note(
        "window",
        platform=app.platformName(),
        font=QFontInfo(app.font()).family(),
        font_families=len(QFontDatabase.families()),
    )
    return 0


def main() -> int:
    velopack.App().run()  # Velopack's hooks: exits when it was one
    note(
        "start",
        argv=sys.argv,
        appimage=os.environ.get("APPIMAGE"),
        appdir=os.environ.get("APPDIR"),
        exe=sys.executable,
        mount=mount_of(sys.executable),
        qpa=os.environ.get("QT_QPA_PLATFORM"),
        extract_and_run=os.environ.get("APPIMAGE_EXTRACT_AND_RUN"),
        glibc=platform.libc_ver(),
        parents=ancestry(),
    )
    args = sys.argv[1:]
    if "--update" in args:
        return update(args[args.index("--update") + 1])
    if "--check" in args:
        return update(args[args.index("--check") + 1], check_only=True)
    return window()


if __name__ == "__main__":
    sys.exit(main())
