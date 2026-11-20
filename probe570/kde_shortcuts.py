"""570: KWin's own global shortcuts as it registers them, with their
defaults - read from kglobalaccel over the session bus, inside a headless
KWin session (tools/linux_session.sh with LINUX_SESSION_SCREEN=kde).
Prints each shortcut whose default (or current) keys use Ctrl+Alt,
Meta+Alt, Ctrl+Meta or Ctrl+Alt+Shift with L, P or H - and how many
shortcuts there are in all.

    python probe570/kde_shortcuts.py OUT.txt
"""

import sys
import time

from jeepney import DBusAddress, new_method_call
from jeepney.io.blocking import open_dbus_connection
from jeepney.wrappers import unwrap_msg

SHIFT, CTRL, ALT, META = 0x02000000, 0x04000000, 0x08000000, 0x10000000
MODS = SHIFT | CTRL | ALT | META
KEYS = {0x4C: "L", 0x50: "P", 0x48: "H"}


def words(combo: int) -> str:
    parts = [n for f, n in ((META, "Meta"), (CTRL, "Ctrl"), (ALT, "Alt"), (SHIFT, "Shift")) if combo & f]
    key = combo & ~MODS
    parts.append(KEYS.get(key, chr(key) if 0x20 < key < 0x7F else hex(key)))
    return "+".join(parts)


def main() -> None:
    out = open(sys.argv[1], "w")
    bus = open_dbus_connection(bus="SESSION")
    root = DBusAddress("/kglobalaccel", "org.kde.kglobalaccel", "org.kde.KGlobalAccel")
    comps: list = []
    for _ in range(30):
        try:
            comps = unwrap_msg(bus.send_and_get_reply(new_method_call(root, "allMainComponents")))[0]
            if comps:
                break
        except Exception as e:  # not there yet
            print("waiting:", e, file=out)
        time.sleep(1)
    total = 0
    for comp in comps:
        unique = comp[0]
        path = "/component/" + "".join(c if c.isalnum() else "_" for c in unique)
        addr = DBusAddress(path, "org.kde.kglobalaccel", "org.kde.kglobalaccel.Component")
        try:
            infos = unwrap_msg(bus.send_and_get_reply(new_method_call(addr, "allShortcutInfos")))[0]
        except Exception as e:
            print(f"{unique}: {e}", file=out)
            continue
        for info in infos:
            total += 1
            action, friendly, keys, defaults = info[4], info[5], info[6], info[7]
            for kind, combos in (("default", defaults), ("now", keys)):
                for combo in combos:
                    mods = combo & MODS
                    if combo & ~MODS in KEYS and mods & (CTRL | ALT | META) and bin(mods).count("1") >= 2:
                        print(f"{unique} / {action} ({friendly}): {kind} {words(combo)}", file=out)
                    elif mods == CTRL | ALT:
                        print(f"  (Ctrl+Alt, other key) {unique} / {action}: {kind} {words(combo)}", file=out)
    print(f"components: {[c[0] for c in comps]}; shortcuts: {total}", file=out)
    out.close()


if __name__ == "__main__":
    main()
