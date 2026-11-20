#!/usr/bin/env bash
# A headless GNOME window manager session (mutter, with XWayland and
# PipeWire for its screen streams) on GitHub's Ubuntu 24.04 runner, then
# 547's window scenarios inside it.   bash windows/run_gnome.sh OUT_DIR
set -euo pipefail
[ "${GITHUB_ACTIONS:-}" = true ] || { echo "547's probes run only on GitHub's runners"; exit 1; }
out="$(realpath -m "$1")"; mkdir -p "$out"
if [ -z "${IN_SESSION_547:-}" ]; then
  XDG_RUNTIME_DIR="$(mktemp -d)"; chmod 700 "$XDG_RUNTIME_DIR"
  export XDG_RUNTIME_DIR GSETTINGS_BACKEND=memory IN_SESSION_547=1
  exec dbus-run-session -- bash "$0" "$out"
fi
here="$(cd "$(dirname "$0")" && pwd)"
py=/tmp/venv/bin/python
{
  echo "os: $(. /etc/os-release; echo "$PRETTY_NAME")"
  echo "mutter: $(mutter --version 2>&1 | head -1)"
  echo "xwayland: $(dpkg-query -W -f '${Version}' xwayland)"
  echo "pipewire: $(pipewire --version | tail -1)"
  echo "pyside6: $($py -c 'import PySide6; print(PySide6.__version__)')"
} | tee "$out/versions.txt"
pipewire > "$out/pipewire.log" 2>&1 & pw=$!
sleep 1
wireplumber > "$out/wireplumber.log" 2>&1 & wp=$!
sleep 1
before="$(ls /tmp/.X11-unix 2>/dev/null || true)"
mutter --wayland --headless --virtual-monitor 1280x720 --wayland-display wayland-547 > "$out/mutter.log" 2>&1 & mu=$!
cleanup() { kill "$mu" "$wp" "$pw" 2>/dev/null || true; }
trap cleanup EXIT
for _ in $(seq 60); do
  [ -S "$XDG_RUNTIME_DIR/wayland-547" ] && break
  sleep 0.5
done
[ -S "$XDG_RUNTIME_DIR/wayland-547" ] || { echo "mutter didn't start"; cat "$out/mutter.log"; exit 1; }
xs=""
for _ in $(seq 60); do
  xs="$(comm -13 <(echo "$before" | sort) <(ls /tmp/.X11-unix 2>/dev/null | sort) | head -1)"
  [ -n "$xs" ] && break
  sleep 0.5
done
[ -n "$xs" ] || { echo "no XWayland socket"; cat "$out/mutter.log"; exit 1; }
export WAYLAND_DISPLAY=wayland-547 DISPLAY=":${xs#X}"
auth="$(ls "$XDG_RUNTIME_DIR"/.mutter-Xwaylandauth.* 2>/dev/null | head -1 || true)"
[ -n "$auth" ] && export XAUTHORITY="$auth"
echo "DISPLAY=$DISPLAY WAYLAND_DISPLAY=$WAYLAND_DISPLAY XAUTHORITY=${XAUTHORITY:-none}" | tee -a "$out/versions.txt"
sleep 2
xdpyinfo 2>&1 | grep -E 'vendor string|version number|dimensions' | tee -a "$out/versions.txt" || true
cd "$here"
"$py" harness.py gnome "$out" 2>&1 | tee "$out/harness.log"
