"""Pictures and pointer input for a headless mutter (GNOME) session.

Pictures: mutter's own ScreenCast D-Bus API (a stream of the virtual
monitor through PipeWire) and one frame taken by GStreamer's pipewiresrc.
Pointer: mutter's RemoteDesktop D-Bus API - real compositor input, so a
click goes wherever mutter sends it (a Wayland or an X11 window).
Only on GitHub's runner, against the session the job made.
"""

from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

if os.environ.get("GITHUB_ACTIONS") != "true" or not sys.platform.startswith("linux"):
    sys.exit("547's probes run only on GitHub's Linux runners")

from jeepney import DBusAddress, MatchRule, Properties, message_bus, new_method_call
from jeepney.io.blocking import open_dbus_connection
from jeepney.wrappers import unwrap_msg

SC = "org.gnome.Mutter.ScreenCast"
RD = "org.gnome.Mutter.RemoteDesktop"
BTN_LEFT = 0x110


class Mutter:
    def __init__(self) -> None:
        self.conn = open_dbus_connection(bus="SESSION")
        self.rd_session = ""
        self.rd_stream = ""

    def call(self, path: str, bus: str, iface: str, method: str, sig: str | None = None, body: tuple = ()) -> tuple:
        addr = DBusAddress(path, bus_name=bus, interface=iface)
        return unwrap_msg(self.conn.send_and_get_reply(new_method_call(addr, method, sig, body), timeout=15))

    def _stream(self, sc_session: str, start: tuple[str, str, str]) -> tuple[str, int]:
        (stream,) = self.call(sc_session, SC, SC + ".Session", "RecordMonitor", "sa{sv}", ("", {"cursor-mode": ("u", 1)}))
        rule = MatchRule(type="signal", interface=SC + ".Stream", member="PipeWireStreamAdded", path=stream)
        unwrap_msg(self.conn.send_and_get_reply(message_bus.AddMatch(rule), timeout=10))
        with self.conn.filter(rule) as queue:
            self.call(start[0], start[1], start[2], "Start")
            msg = self.conn.recv_until_filtered(queue, timeout=15)
        return stream, int(msg.body[0])

    def start_pointer(self) -> None:
        (self.rd_session,) = self.call("/org/gnome/Mutter/RemoteDesktop", RD, RD, "CreateSession")
        props = Properties(DBusAddress(self.rd_session, bus_name=RD, interface=RD + ".Session"))
        ((_, sid),) = unwrap_msg(self.conn.send_and_get_reply(props.get("SessionId"), timeout=10))
        (sc_session,) = self.call(
            "/org/gnome/Mutter/ScreenCast", SC, SC, "CreateSession", "a{sv}", ({"remote-desktop-session-id": ("s", sid)},)
        )
        self.rd_stream, _ = self._stream(sc_session, (self.rd_session, RD, RD + ".Session"))

    def move(self, x: float, y: float) -> None:
        self.call(self.rd_session, RD, RD + ".Session", "NotifyPointerMotionAbsolute", "sdd", (self.rd_stream, float(x), float(y)))

    def click(self, x: float, y: float) -> None:
        self.move(x, y)
        self.call(self.rd_session, RD, RD + ".Session", "NotifyPointerButton", "ib", (BTN_LEFT, True))
        self.call(self.rd_session, RD, RD + ".Session", "NotifyPointerButton", "ib", (BTN_LEFT, False))

    def picture(self, path: Path) -> None:
        (session,) = self.call("/org/gnome/Mutter/ScreenCast", SC, SC, "CreateSession", "a{sv}", ({},))
        try:
            _, node = self._stream(session, (session, SC, SC + ".Session"))
            subprocess.run(
                ["gst-launch-1.0", "-q", "-e", "pipewiresrc", f"path={node}", "num-buffers=3", "!", "videoconvert",
                 "!", "pngenc", "snapshot=true", "!", "filesink", f"location={path}"],
                check=True, timeout=20, stdout=subprocess.DEVNULL,
            )
        finally:
            self.call(session, SC, SC + ".Session", "Stop")
