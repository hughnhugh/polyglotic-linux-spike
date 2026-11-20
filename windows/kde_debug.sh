#!/usr/bin/env bash
# Why doesn't KWin's virtual session start in the container? Starts
# kwin_wayland in the background for 40 s in one mode and prints what it
# did: its log, its processes, its sockets.   bash windows/kde_debug.sh MODE
# MODE: default | software | qpainter | user (software, as a normal user)
set -uo pipefail
[ "${GITHUB_ACTIONS:-}" = true ] || { echo "547's probes run only on GitHub's runners"; exit 1; }
mode="$1"
if [ -z "${IN_CONTAINER_547:-}" ]; then
  exec docker run --rm --cap-add SYS_NICE -e GITHUB_ACTIONS=true -e IN_CONTAINER_547=1 \
    -v "$(cd "$(dirname "$0")/.." && pwd):/w" fedora:45 bash /w/windows/kde_debug.sh "$mode"
fi
if [ -z "${AS_USER_547:-}" ]; then
  dnf -y -q install kwin xorg-x11-server-Xwayland mesa-dri-drivers dbus-daemon dbus-tools procps-ng xdpyinfo \
    > /tmp/dnf.log 2>&1 || { tail -20 /tmp/dnf.log; exit 1; }
  if [ "$mode" = user ]; then
    useradd -m u547
    exec su u547 -c "AS_USER_547=1 GITHUB_ACTIONS=true IN_CONTAINER_547=1 bash /w/windows/kde_debug.sh user"
  fi
fi
export XDG_RUNTIME_DIR="/tmp/xdg-$(id -u)"; mkdir -p -m 700 "$XDG_RUNTIME_DIR"
export QT_LOGGING_RULES="kwin_*.debug=true"
case "$mode" in
  software|user) export LIBGL_ALWAYS_SOFTWARE=1 GALLIUM_DRIVER=llvmpipe ;;
  qpainter) export KWIN_COMPOSE=Q ;;
esac
log=/tmp/kwin.log
dbus-run-session -- kwin_wayland --virtual --xwayland --width=1280 --height=720 --socket=wayland-547 > "$log" 2>&1 &
pid=$!
sleep 30
echo "=== mode $mode, user $(id -un), kwin pid $pid alive: $(kill -0 $pid 2>/dev/null && echo yes || echo no)"
echo "=== processes"; ps -eo pid,ppid,stat,etime,args | grep -v -E 'ps -eo|grep' | cut -c1-160
echo "=== sockets"; ls -la "$XDG_RUNTIME_DIR" /tmp/.X11-unix 2>&1
echo "=== log ($(wc -l < "$log") lines)"; grep -v '^\s*$' "$log" | cut -c1-200 | head -60
echo "=== log tail"; tail -15 "$log" | cut -c1-200
xs="$(ls /tmp/.X11-unix 2>/dev/null | head -1)"
if [ -n "$xs" ]; then
  auth="$(ls "$XDG_RUNTIME_DIR"/xauth_* 2>/dev/null | head -1)"
  echo "=== xdpyinfo on :${xs#X} (auth ${auth:-none})"
  DISPLAY=":${xs#X}" XAUTHORITY="$auth" timeout 10 xdpyinfo 2>&1 | head -5
fi
kill "$pid" 2>/dev/null
exit 0
