# Polyglotic on Linux: the spike

Throwaway probes that answer three questions about Linux desktops before
Polyglotic's desktop app is ported to them. Nothing here is the app's code;
every script is a small stand-alone probe. They run only on GitHub's own
Ubuntu runners (each refuses to run anywhere else), on headless desktop
sessions made for the run.

| Folder | Question | Workflow |
|---|---|---|
| `windows/` | Does a frameless, translucent, always-on-top PySide6 window (as an X11 program under XWayland) stay above a focused full-screen window on GNOME's mutter and KDE's KWin? Does click-through work? Does it see the pointer over a Wayland window beneath it? | `windows.yml` (branch `windows`) |
| `capture/` | Can libpulse, called through Python's ctypes, record one app's stream, the default output's monitor and a microphone on PipeWire, and list the apps playing with their names? | `capture.yml` (branch `capture`) |
| `updates/` | Can a small Velopack AppImage, built on Ubuntu 22.04, be installed and then updated in place from a local feed, without `libfuse2`? Must `libxcb-cursor0` be bundled? | `updates.yml` (branch `updates`) |

Each workflow uploads its log and pictures as an artifact kept for one day.
No secrets are used or needed.
