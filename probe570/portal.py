"""570: the GlobalShortcuts portal from an app that isn't a Flatpak, on a
headless GNOME Shell the job made: the host Registry's Register first,
then CreateSession, BindShortcuts (Ctrl+Alt+Shift+L preferred), the
shell's own box answered with Enter through its RemoteDesktop, the keys
pressed through it, and the Activated signals heard.

    python probe570/portal.py OUT.json
"""

from __future__ import annotations

import json
import os
import sys
import threading
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from jeepney import DBusAddress, MatchRule, Properties, message_bus, new_method_call  # noqa: E402
from jeepney.io.blocking import open_dbus_connection  # noqa: E402
from jeepney.wrappers import unwrap_msg  # noqa: E402

OUT = Path(sys.argv[1])
RESULTS: dict[str, object] = {}
DESKTOP = "org.freedesktop.portal.Desktop"
PATH = "/org/freedesktop/portal/desktop"
GS = "org.freedesktop.portal.GlobalShortcuts"
APP_ID = "io.polyglotic.Polyglotic"


def note(key: str, value: object) -> None:
    RESULTS[key] = value
    print(key, value, flush=True)
    OUT.write_text(json.dumps(RESULTS, indent=1, default=str))


def call(bus, path, name, iface, method, sig=None, body=()):  # type: ignore[no-untyped-def]
    msg = new_method_call(DBusAddress(path, bus_name=name, interface=iface), method, sig, body)
    return unwrap_msg(bus.send_and_get_reply(msg, timeout=20))


def request(bus, token: str, method: str, sig: str, body: tuple, wait: float = 30.0):  # type: ignore[no-untyped-def]
    sender = bus.unique_name[1:].replace(".", "_")
    path = f"{PATH}/request/{sender}/{token}"
    rule = MatchRule(type="signal", interface="org.freedesktop.portal.Request",
                     member="Response", path=path)
    unwrap_msg(bus.send_and_get_reply(message_bus.AddMatch(rule), timeout=10))
    with bus.filter(rule) as queue:
        call(bus, PATH, DESKTOP, GS, method, sig, body)
        try:
            msg = bus.recv_until_filtered(queue, timeout=wait)
        except TimeoutError:
            return None
    return msg.body


def main() -> int:
    from tools.linux_input import Input

    bus = open_dbus_connection(bus="SESSION")
    try:
        names = call(bus, "/org/freedesktop/DBus", "org.freedesktop.DBus",
                     "org.freedesktop.DBus", "ListActivatableNames")[0]
        note("portal_activatable", DESKTOP in names)
        version = unwrap_msg(bus.send_and_get_reply(
            Properties(DBusAddress(PATH, bus_name=DESKTOP, interface=GS)).get("version"), timeout=20))
        note("global_shortcuts_version", version)
    except Exception as error:  # noqa: BLE001
        note("global_shortcuts_version", f"none: {error}")
        return 0
    try:  # first on this connection
        call(bus, PATH, DESKTOP, "org.freedesktop.host.portal.Registry", "Register",
             "sa{sv}", (APP_ID, {}))
        note("registered", True)
    except Exception as error:  # noqa: BLE001
        note("registered", f"no: {error}")
    created = request(bus, "pg570a", "CreateSession", "a{sv}",
                      ({"handle_token": ("s", "pg570a"), "session_handle_token": ("s", "pg570s")},))
    note("create_session", created)
    if not created or created[0] != 0:
        return 0
    session = created[1]["session_handle"][1]
    shortcuts = [
        ("lock", {"description": ("s", "Lock or unlock the caption windows"),
                  "preferred_trigger": ("s", "CTRL+ALT+SHIFT+l")}),
        ("pause", {"description": ("s", "Pause or resume captions"),
                   "preferred_trigger": ("s", "CTRL+ALT+SHIFT+p")}),
    ]
    heard: list[str] = []
    rule = MatchRule(type="signal", interface=GS, member="Activated")
    unwrap_msg(bus.send_and_get_reply(message_bus.AddMatch(rule), timeout=10))
    inp = Input.make("gnome")
    answered: dict[str, object] = {}

    def bind() -> None:
        answered["bind"] = request(bus, "pg570b", "BindShortcuts", "oa(sa{sv})sa{sv}",
                                   (session, shortcuts, "", {"handle_token": ("s", "pg570b")}), 40)

    worker = threading.Thread(target=bind)
    worker.start()
    time.sleep(4)  # the shell's box, if it shows one
    pictures = os.environ.get("POLYGLOTIC_DESK_PICTURES")
    if pictures:
        Path(pictures, "portal-box.want").write_text("")
        time.sleep(6)
    inp.press("enter")  # its default button
    worker.join(45)
    note("bind_shortcuts", answered.get("bind"))
    with bus.filter(rule) as queue:
        time.sleep(1)
        inp.press("ctrl", "alt", "shift", "l")
        end = time.time() + 5
        while time.time() < end:
            try:
                msg = bus.recv_until_filtered(queue, timeout=max(0.1, end - time.time()))
            except TimeoutError:
                break
            heard.append(str(msg.body[1]))
    note("activated", heard)
    return 0


if __name__ == "__main__":
    sys.exit(main())
