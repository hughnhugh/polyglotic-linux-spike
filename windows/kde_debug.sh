#!/usr/bin/env bash
# Why doesn't KWin's virtual session last in the container? Starts
# kwin_wayland in the background for 30 s in one mode, maps one X11 window,
# and prints what KWin did: its log, its processes, its sockets.
#   bash windows/kde_debug.sh MODE
# MODE: default | software | qpainter | drm (Fedora 45's KWin 6 with the
# host's virtual DRM devices, vgem and vkms) | plasma5 (Ubuntu 24.04's own
# KWin 5.27 on the runner, QPainter)
set -uo pipefail
[ "${GITHUB_ACTIONS:-}" = true ] || { echo "547's probes run only on GitHub's runners"; exit 1; }
mode="$1"
if [ -z "${IN_CONTAINER_547:-}" ] && [ "$mode" != plasma5 ]; then
  dev=()
  if [ "$mode" = drm ]; then
    sudo apt-get install -y -q "linux-modules-extra-$(uname -r)" > /dev/null 2>&1 || echo "no modules-extra for $(uname -r)"
    sudo modprobe vgem && echo "vgem loaded"; sudo modprobe vkms && echo "vkms loaded"
    ls -la /dev/dri 2>&1
    [ -d /dev/dri ] && dev=(--device /dev/dri)
  fi
  exec docker run --rm --cap-add SYS_NICE "${dev[@]}" -e GITHUB_ACTIONS=true -e IN_CONTAINER_547=1 \
    -v "$(cd "$(dirname "$0")/.." && pwd):/w" fedora:45 bash /w/windows/kde_debug.sh "$mode"
fi
if [ "$mode" = plasma5 ]; then
  sudo apt-get update -q > /dev/null; sudo apt-get install -y -q kwin-wayland xwayland x11-utils dbus > /dev/null 2>&1
  echo "kwin: $(dpkg-query -W -f '${Version}' kwin-wayland)"
  export KWIN_COMPOSE=Q
else
  dnf -y -q install kwin xorg-x11-server-Xwayland mesa-dri-drivers dbus-daemon dbus-tools procps-ng xdpyinfo xeyes \
    > /tmp/dnf.log 2>&1 || dnf -y -q install kwin xorg-x11-server-Xwayland mesa-dri-drivers dbus-daemon dbus-tools \
    procps-ng xdpyinfo >> /tmp/dnf.log 2>&1 || { tail -20 /tmp/dnf.log; exit 1; }
fi
export XDG_RUNTIME_DIR="/tmp/xdg-$(id -u)"; mkdir -p -m 700 "$XDG_RUNTIME_DIR"
export QT_LOGGING_RULES="kwin_*.debug=true" QT_FORCE_STDERR_LOGGING=1
case "$mode" in
  software) export LIBGL_ALWAYS_SOFTWARE=1 GALLIUM_DRIVER=llvmpipe ;;
  qpainter) export KWIN_COMPOSE=Q ;;
esac
log=/tmp/kwin.log
dbus-run-session -- kwin_wayland --virtual --xwayland --width=1280 --height=720 --socket=wayland-547 > "$log" 2>&1 &
pid=$!
sleep 12
DISPLAY=:0 timeout 10 xdpyinfo 2>&1 | grep -E 'vendor string|X.Org version' || echo "no X"
(DISPLAY=:0 timeout 10 xeyes > /dev/null 2>&1 &) ; sleep 8
echo "=== mode $mode, user $(id -un), kwin pid $pid alive: $(kill -0 $pid 2>/dev/null && echo yes || echo no)"
echo "=== processes"; ps -eo pid,ppid,stat,etime,args | grep -E 'kwin|Xwayland' | grep -v grep | cut -c1-160
ls /dev/dri 2>&1
echo "=== log ($(wc -l < "$log") lines)"; grep -v '^\s*$' "$log" | grep -v -E 'xkbcomp|keysym|Using|multiply|X11 cannot|Warning' | cut -c1-200 | head -60
kill "$pid" 2>/dev/null
exit 0
