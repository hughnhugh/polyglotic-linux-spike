#!/usr/bin/env bash
# A headless KDE Plasma 6 window manager session (KWin's virtual backend,
# with XWayland) in a Fedora container on GitHub's runner, then 547's window
# scenarios inside it.   bash windows/run_kde.sh OUT_DIR [FEDORA_TAG]
set -euo pipefail
[ "${GITHUB_ACTIONS:-}" = true ] || { echo "547's probes run only on GitHub's runners"; exit 1; }
if [ -z "${IN_CONTAINER_547:-}" ]; then
  out="$(realpath -m "$1")"; mkdir -p "$out"
  tag="${2:-latest}"
  root="$(cd "$(dirname "$0")/.." && pwd)"
  exec docker run --rm --cap-add SYS_NICE -e GITHUB_ACTIONS=true -e IN_CONTAINER_547=1 -v "$root:/w" -v "$out:/out" \
    "fedora:$tag" bash /w/windows/run_kde.sh /out
fi
if [ -z "${IN_SESSION_547:-}" ]; then
  dnf -y -q install --skip-unavailable kwin xorg-x11-server-Xwayland mesa-dri-drivers mesa-libEGL \
    mesa-libGL libglvnd-egl dbus-daemon dbus-tools python3 xcb-util-cursor xcb-util-wm xcb-util-image \
    xcb-util-keysyms xcb-util-renderutil libxkbcommon-x11 fontconfig dejavu-sans-fonts \
    plasma-wayland-protocols-devel plasma-wayland-protocols xprop xwininfo xdpyinfo > /tmp/dnf.log 2>&1 \
    || { tail -30 /tmp/dnf.log; exit 1; }
  python3 -m venv /venv
  /venv/bin/pip install -q PySide6-Essentials==6.12.0 jeepney==0.9.0
  export XDG_RUNTIME_DIR=/tmp/xdg; mkdir -p -m 700 "$XDG_RUNTIME_DIR"
  export KWIN_SCREENSHOT_NO_PERMISSION_CHECKS=1 KWIN_WAYLAND_NO_PERMISSION_CHECKS=1
  export QT_LOGGING_RULES="kwin_scripting.debug=true;js.debug=true;qml.debug=true;kwin_xwl.debug=true"
  export IN_SESSION_547=1 OUT_547=/out QT_FORCE_STDERR_LOGGING=1
  {
    echo "os: $(. /etc/os-release; echo "$PRETTY_NAME")"
    echo "kwin: $(rpm -q kwin)"
    echo "xwayland: $(rpm -q xorg-x11-server-Xwayland)"
    echo "pyside6: $(/venv/bin/python -c 'import PySide6; print(PySide6.__version__)')"
  } | tee /out/versions.txt
  exec dbus-run-session -- bash /w/windows/run_kde.sh /out
fi
# inside the session's D-Bus: KWin in the background (its --exit-with-session
# never started the session program here: XWayland starts on demand, 547 run 5)
export KWIN_LOG=/out/kwin.log
kwin_wayland --virtual --xwayland --width=1280 --height=720 --socket=wayland-547 > "$KWIN_LOG" 2>&1 &
kw=$!
trap 'kill "$kw" 2>/dev/null || true' EXIT
for _ in $(seq 60); do [ -S "$XDG_RUNTIME_DIR/wayland-547" ] && break; sleep 0.5; done
[ -S "$XDG_RUNTIME_DIR/wayland-547" ] || { echo "KWin didn't start"; tail -20 "$KWIN_LOG"; exit 1; }
export WAYLAND_DISPLAY=wayland-547 DISPLAY=:0
auth="$(ls "$XDG_RUNTIME_DIR"/xauth_* 2>/dev/null | head -1 || true)"
[ -n "$auth" ] && export XAUTHORITY="$auth"
echo "DISPLAY=${DISPLAY:-} WAYLAND_DISPLAY=${WAYLAND_DISPLAY:-} XAUTHORITY=${XAUTHORITY:-none}" >> "$OUT_547/versions.txt"
sleep 2
xdpyinfo 2>&1 | grep -E 'vendor string|version number|dimensions' >> "$OUT_547/versions.txt" || true
cd /w/windows
timeout 480 /venv/bin/python -u harness.py kde "$OUT_547" 2>&1 | tee "$OUT_547/harness.log" | grep -E "^---|^\|" || true
echo "kwin log: $(wc -l < "$KWIN_LOG") lines"; grep -c STACK547 "$KWIN_LOG" || true
