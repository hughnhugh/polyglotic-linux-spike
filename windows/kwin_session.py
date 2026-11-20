"""Pictures, pointer input and the stacking order for a headless KWin session.

Pictures: KWin's ScreenShot2 D-Bus API (the job starts KWin with
KWIN_SCREENSHOT_NO_PERMISSION_CHECKS=1). Pointer: KDE's fake-input Wayland
protocol, spoken directly over the Wayland socket (KWin started with
KWIN_WAYLAND_NO_PERMISSION_CHECKS=1) - real compositor input. Stacking: a
KWin script printing workspace.stackingOrder into KWin's log.
Only on GitHub's runner, against the session the job made.
"""

from __future__ import annotations

import os
import socket
import struct
import sys
import time
import xml.etree.ElementTree as ET
from pathlib import Path

if os.environ.get("GITHUB_ACTIONS") != "true" or not sys.platform.startswith("linux"):
    sys.exit("547's probes run only on GitHub's Linux runners")

from jeepney import DBusAddress, new_method_call
from jeepney.io.blocking import open_dbus_connection
from jeepney.wrappers import unwrap_msg

BTN_LEFT = 0x110
FAKE_INPUT_XML = Path("/usr/share/plasma-wayland-protocols/fake-input.xml")


def _wl_string(s: str) -> bytes:
    raw = s.encode() + b"\0"
    return struct.pack("<I", len(raw)) + raw + b"\0" * (-len(raw) % 4)


class FakeInput:
    """The few Wayland messages needed to send pointer events through KWin."""

    def __init__(self) -> None:
        path = os.path.join(os.environ["XDG_RUNTIME_DIR"], os.environ["WAYLAND_DISPLAY"])
        self.sock = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
        self.sock.connect(path)
        self.buf = b""
        self.next_id = 2
        self.ops = self._opcodes()
        registry = self._new_id()
        self._send(1, 1, struct.pack("<I", registry))  # wl_display.get_registry
        globals_ = {}
        for obj, op, body in self._roundtrip():
            if obj == registry and op == 0:
                name = struct.unpack_from("<I", body)[0]
                n = struct.unpack_from("<I", body, 4)[0]
                iface = body[8 : 8 + n - 1].decode()
                version = struct.unpack_from("<I", body, 8 + n + (-n % 4))[0]
                globals_[iface] = (name, version)
        if "org_kde_kwin_fake_input" not in globals_:
            raise RuntimeError(f"no fake input global; have {sorted(globals_)}")
        name, version = globals_["org_kde_kwin_fake_input"]
        self.version = min(version, 4)
        self.fake = self._new_id()
        self._send(registry, 0, struct.pack("<I", name) + _wl_string("org_kde_kwin_fake_input")
                   + struct.pack("<II", self.version, self.fake))  # wl_registry.bind
        self._send(self.fake, self.ops["authenticate"], _wl_string("polyglotic-547") + _wl_string("spike"))
        self._roundtrip()

    @staticmethod
    def _opcodes() -> dict[str, int]:
        if FAKE_INPUT_XML.exists():
            iface = ET.parse(FAKE_INPUT_XML).getroot().find("interface")
            assert iface is not None
            return {r.get("name", ""): i for i, r in enumerate(iface.findall("request"))}
        return {"authenticate": 0, "pointer_motion": 1, "button": 2, "pointer_motion_absolute": 9}

    def _new_id(self) -> int:
        self.next_id += 1
        return self.next_id

    def _send(self, obj: int, op: int, body: bytes) -> None:
        self.sock.sendall(struct.pack("<II", obj, ((8 + len(body)) << 16) | op) + body)

    def _roundtrip(self) -> list[tuple[int, int, bytes]]:
        cb = self._new_id()
        self._send(1, 0, struct.pack("<I", cb))  # wl_display.sync
        events = []
        self.sock.settimeout(10)
        while True:
            while len(self.buf) < 8:
                chunk = self.sock.recv(65536)
                if not chunk:
                    raise RuntimeError("the compositor closed the connection")
                self.buf += chunk
            obj, word = struct.unpack_from("<II", self.buf)
            size, op = word >> 16, word & 0xFFFF
            while len(self.buf) < size:
                self.buf += self.sock.recv(65536)
            body, self.buf = self.buf[8:size], self.buf[size:]
            if obj == 1 and op == 0:
                raise RuntimeError(f"wayland error: {body!r}")
            if obj == cb and op == 0:
                return events
            events.append((obj, op, body))

    @staticmethod
    def _fixed(v: float) -> bytes:
        return struct.pack("<i", int(round(v * 256)))

    def move(self, x: float, y: float) -> None:
        self._send(self.fake, self.ops["pointer_motion_absolute"], self._fixed(x) + self._fixed(y))
        self._roundtrip()

    def click(self, x: float, y: float) -> None:
        self.move(x, y)
        self._send(self.fake, self.ops["button"], struct.pack("<II", BTN_LEFT, 1))
        self._roundtrip()
        self._send(self.fake, self.ops["button"], struct.pack("<II", BTN_LEFT, 0))
        self._roundtrip()


STACK_SCRIPT = r"""
var list = workspace.stackingOrder;
var out = [];
for (var i = 0; i < list.length; i++) {
    var w = list[i];
    var d = {};
    var keys = ["caption", "resourceClass", "keepAbove", "fullScreen", "active", "layer", "x11DesktopIds",
                "normalWindow", "specialWindow", "popupWindow", "outline", "managed", "deleted", "windowType"];
    for (var k = 0; k < keys.length; k++) { try { d[keys[k]] = w[keys[k]]; } catch (e) {} }
    try { d.x11 = (w.windowId !== undefined); } catch (e) {}
    out.push(JSON.stringify(d));
}
var act = workspace.activeWindow;
print("STACK547 " + TAG + " active=" + (act ? act.caption : "none") + " bottom-to-top=[" + out.join(", ") + "]");
"""


class KWin:
    def __init__(self, log_path: Path, work: Path) -> None:
        self.conn = open_dbus_connection(bus="SESSION", enable_fds=True)
        self.log_path = log_path
        self.work = work
        self.n = 0
        self.fake = FakeInput()

    def call(self, path: str, bus: str, iface: str, method: str, sig: str | None = None, body: tuple = ()) -> tuple:
        addr = DBusAddress(path, bus_name=bus, interface=iface)
        return unwrap_msg(self.conn.send_and_get_reply(new_method_call(addr, method, sig, body), timeout=15))

    def move(self, x: float, y: float) -> None:
        self.fake.move(x, y)

    def click(self, x: float, y: float) -> None:
        self.fake.click(x, y)

    def picture(self, path: Path) -> None:
        from PySide6.QtGui import QImage

        r, w = os.pipe()
        try:
            (meta,) = self.call("/org/kde/KWin/ScreenShot2", "org.kde.KWin.ScreenShot2", "org.kde.KWin.ScreenShot2",
                                "CaptureWorkspace", "a{sv}h", ({"include-cursor": ("b", True)}, w))
        finally:
            os.close(w)
        data = b""
        while chunk := os.read(r, 1 << 20):
            data += chunk
        os.close(r)
        m = {k: v[1] for k, v in meta.items()}
        img = QImage(data, m["width"], m["height"], m["stride"], QImage.Format(m["format"]))
        img.copy().save(str(path))

    def stacking(self, tag: str) -> str:
        self.n += 1
        script = self.work / f"stack{self.n}.js"
        script.write_text(f"var TAG = {tag!r};\n" + STACK_SCRIPT)
        name = f"stack547_{self.n}"
        before = self.log_path.read_text(errors="replace") if self.log_path.exists() else ""
        (sid,) = self.call("/Scripting", "org.kde.KWin", "org.kde.kwin.Scripting", "loadScript", "ss", (str(script), name))
        self.call("/Scripting", "org.kde.KWin", "org.kde.kwin.Scripting", "start")
        line = ""
        for _ in range(40):
            time.sleep(0.1)
            text = self.log_path.read_text(errors="replace")[len(before):]
            hits = [x for x in text.splitlines() if "STACK547 " + tag in x]
            if hits:
                line = hits[-1]
                break
        self.call("/Scripting", "org.kde.KWin", "org.kde.kwin.Scripting", "unloadScript", "s", (name,))
        return line or f"(no stacking line for {tag}; script id {sid})"
