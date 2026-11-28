"""The isolated Mac tester preview's identity, checked before its build in
the disposable hosted Mac checkout (polyglotic-hq 1045, RULES #7).

The app's own modules, in a copy stamped as the preview, must read only
the preview's bundle ID and names, data folder, keychain entry, locks and
caches folder; no application updates (its feed is its own program
folder, which holds none, unsigned); and the dictionary packs from https,
signed. macos_preview_qa.sh then builds the preview flavour itself.
"""

from __future__ import annotations

import json
import os
import sys
import tempfile
from pathlib import Path
from unittest import mock

from polyglotic_desktop.core.releases import identity
from tools.macos_ui_lab import hosted_mac
from tools.package import stamp


def prepare(out: Path) -> None:
    if not hosted_mac():
        raise RuntimeError("Prepare only the disposable hosted Mac checkout")
    if os.environ.get(stamp.FLAVOUR_ENV) != "preview":
        raise RuntimeError(f"preview QA requires {stamp.FLAVOUR_ENV}=preview")
    preview, release = identity.flavour("preview"), identity.flavour("release")
    with (
        tempfile.TemporaryDirectory(prefix="preview-stamp-") as folder,
        mock.patch.object(identity, "files", lambda _name: Path(folder)),
    ):  # this process reads a preview's stamp, as the packed preview does
        (Path(folder) / identity.STAMP).write_text(
            stamp.stamp("0.1.10", "macos-arm64-alpha", flavour="preview"),
            encoding="utf-8",
        )
        identity.current.cache_clear()
        assert identity.current() == preview
        from polyglotic_desktop import main
        from polyglotic_desktop.platform.macos import keychain, system
        from polyglotic_desktop.platform.macos.one_copy import locks_folder
        from tools.package.build import info_plist

        plist = info_plist("0.1.10", identity.current())
        assert plist["CFBundleIdentifier"] == preview.bundle_id != release.bundle_id
        assert plist["CFBundleDisplayName"] == preview.title != release.title
        assert system.data_folder().name == preview.data_folder != release.data_folder
        assert keychain.SERVICE == preview.credential != release.credential
        assert locks_folder().parent == system.data_folder()
        caches = main.verified_feed_folder("/tmp/P.app/Contents/MacOS/Polyglotic")
        assert caches.parent.name == preview.data_folder
        program = Path(sys.executable).resolve().parent
        assert str(program) == main.UPDATES and main.FEED_KEYS == ()
        assert not list(program.glob("releases.*.json"))  # no application updates
        assert main.PACKS.startswith("https://") and main.pack_storage("", (), True)[1]
    out.mkdir(parents=True, exist_ok=True)
    (out / "identity.json").write_text(
        json.dumps(
            {
                "bundle": preview.bundle_id,
                "name": preview.title,
                "data_folder": preview.data_folder,
                "keychain": preview.credential,
                "locks_in_preview_data": True,
                "update_feed": "its own program folder, which holds no feed",
                "signed_dictionary_feed": True,
            },
            indent=2,
        ),
        encoding="utf-8",
    )


if __name__ == "__main__":
    prepare(Path(sys.argv[1]))
