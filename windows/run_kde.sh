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
  exec docker run --rm -e GITHUB_ACTIONS=true -e IN_CONTAINER_547=1 -v "$root:/w" -v "$out:/out" \
    "fedora:$tag" bash /w/windows/run_kde.sh /out
fi
if [ -z "${IN_SESSION_547:-}" ]; then
  dnf -y -q install --skip-unavailable kwin-wayland xorg-x11-server-Xwayland mesa-dri-drivers mesa-libEGL \
    mesa-libGL libglvnd-egl dbus-daemon dbus-tools python3 xcb-util-cursor xcb-util-wm xcb-util-image \
    xcb-util-keysyms xcb-util-renderutil libxkbcommon-x11 fontconfig dejavu-sans-fonts \
    plasma-wayland-protocols-devel plasma-wayland-protocols xprop xwininfo xdpyinfo > /tmp/dnf.log 2>&1 \
    || { tail -30 /tmp/dnf.log; exit 1; }
  python3 -m venv /venv
  /venv/bin/pip install -q PySide6-Essentials==6.12.0 jeepney==0.9.0
  export XDG_RUNTIME_DIR=/tmp/xdg; mkdir -p -m 700 "$XDG_RUNTIME_DIR"
  export KWIN_SCREENSHOT_NO_PERMISSION_CHECKS=1 KWIN_WAYLAND_NO_PERMISSION_CHECKS=1
  export QT_LOGGING_RULES="kwin_scripting.debug=true;js.debug=true;qml.debug=true"
  export KWIN_LOG=/out/kwin.log IN_SESSION_547=1 OUT_547=/out
  {
    echo "os: $(. /etc/os-release; echo "$PRETTY_NAME")"
    echo "kwin: $(rpm -q kwin-wayland)"
    echo "xwayland: $(rpm -q xorg-x11-server-Xwayland)"
    echo "pyside6: $(/venv/bin/python -c 'import PySide6; print(PySide6.__version__)')"
    ls /usr/share/plasma-wayland-protocols/ 2>/dev/null | tr '\n' ' '; echo
  } | tee /out/versions.txt
  status=0
  timeout 900 dbus-run-session -- kwin_wayland --virtual --xwayland --width=1280 --height=720 \
    --socket=wayland-547 --exit-with-session=/w/windows/run_kde.sh > "$KWIN_LOG" 2>&1 || status=$?
  echo "kwin ended: $status"
  cat /out/harness.log 2>/dev/null | tail -5 || true
  exit "$status"
fi
# here inside KWin's session: KWin set DISPLAY, WAYLAND_DISPLAY and XAUTHORITY
echo "DISPLAY=${DISPLAY:-} WAYLAND_DISPLAY=${WAYLAND_DISPLAY:-} XAUTHORITY=${XAUTHORITY:-none}" >> "$OUT_547/versions.txt"
sleep 2
xdpyinfo 2>&1 | grep -E 'vendor string|version number|dimensions' >> "$OUT_547/versions.txt" || true
cd /w/windows
/venv/bin/python harness.py kde "$OUT_547" > "$OUT_547/harness.log" 2>&1
