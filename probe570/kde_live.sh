#!/usr/bin/env bash
# 570: inside fedora:45 - a headless KWin (Plasma 6) and its kglobalaccel,
# then every shortcut it registers, read over the bus (kde_shortcuts.py).
set -uo pipefail
out="${1:?out}"; mkdir -p "$out"
dnf -y -q install --skip-unavailable kwin kglobalacceld kscreenlocker plasma-workspace python3-jeepney dbus-daemon \
  dbus-tools mesa-dri-drivers mesa-libEGL xorg-x11-server-Xwayland > /tmp/dnf.log 2>&1 || tail -5 /tmp/dnf.log
rpm -q kwin kglobalacceld kscreenlocker plasma-workspace > "$out/kde-versions.txt" 2>&1
XDG_RUNTIME_DIR="$(mktemp -d)"; export XDG_RUNTIME_DIR; chmod 700 "$XDG_RUNTIME_DIR"
dbus-run-session -- bash -c '
  KWIN_WAYLAND_NO_PERMISSION_CHECKS=1 kwin_wayland --virtual --xwayland --width=1280 --height=800 \
    --socket=wayland-570 > "'"$out"'/kwin.log" 2>&1 & kwin=$!
  sleep 10
  gdbus call --session --dest org.freedesktop.DBus --object-path /org/freedesktop/DBus \
    --method org.freedesktop.DBus.ListNames > "'"$out"'/kde-names.txt" 2>&1
  if ! grep -q org.kde.kglobalaccel "'"$out"'/kde-names.txt"; then
    for d in /usr/libexec/kglobalacceld /usr/lib64/libexec/kglobalacceld; do
      [ -x "$d" ] && { WAYLAND_DISPLAY=wayland-570 "$d" > "'"$out"'/kglobalacceld.log" 2>&1 & sleep 5; }
    done
  fi
  python3 /w/probe570/kde_shortcuts.py "'"$out"'/kde-shortcuts.txt"
  kill $kwin 2>/dev/null'
cat "$out/kde-versions.txt" "$out/kde-shortcuts.txt" 2>/dev/null
