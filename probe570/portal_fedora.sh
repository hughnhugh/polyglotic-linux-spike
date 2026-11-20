#!/usr/bin/env bash
# 570: GNOME Shell 51, headless, in fedora:45 - the GlobalShortcuts portal
# as an app that isn't a Flatpak reaches it (probe570/portal.py).
set -uo pipefail
out="$(realpath -m "${1:?OUT}")"
if [ -z "${IN_FEDORA_570:-}" ]; then
  mkdir -p "$out"; root="$(cd "$(dirname "$0")/.." && pwd)"
  exec docker run --rm --cap-add SYS_NICE -e GITHUB_ACTIONS=true -e IN_FEDORA_570=1 \
    -v "$root:/w" -v "$out:/out" -v "$(command -v uv):/usr/local/bin/uv:ro" -w /w fedora:45 \
    bash /w/probe570/portal_fedora.sh /out
fi
dnf -y -q install --skip-unavailable gnome-shell mutter xdg-desktop-portal xdg-desktop-portal-gnome \
  xorg-x11-server-Xwayland pipewire wireplumber pipewire-gstreamer gstreamer1 gstreamer1-plugins-base \
  gstreamer1-plugins-good dbus-daemon dbus-tools mesa-dri-drivers mesa-libEGL mesa-libGL \
  xcb-util-cursor xcb-util-wm xcb-util-image xcb-util-keysyms xcb-util-renderutil libxkbcommon-x11 \
  libwayland-client libwayland-cursor libwayland-egl fontconfig google-noto-sans-fonts libXtst \
  procps-ng findutils > /tmp/dnf.log 2>&1 || { tail -30 /tmp/dnf.log; exit 1; }
rpm -q gnome-shell mutter xdg-desktop-portal xdg-desktop-portal-gnome > /out/versions.txt
export UV_PROJECT_ENVIRONMENT=/tmp/venv UV_PYTHON=3.12.15 UV_PYTHON_PREFERENCE=only-managed
uv sync --locked > /out/uv-sync.log 2>&1 || { tail -30 /out/uv-sync.log; exit 1; }
XDG_RUNTIME_DIR="$(mktemp -d)"; chmod 700 "$XDG_RUNTIME_DIR"; export XDG_RUNTIME_DIR
export XDG_DATA_HOME="$(mktemp -d)" XDG_CURRENT_DESKTOP=GNOME XDG_SESSION_TYPE=wayland
mkdir -p "$XDG_DATA_HOME/applications"
printf '[Desktop Entry]\nType=Application\nName=Polyglotic\nExec=polyglotic\n' \
  > "$XDG_DATA_HOME/applications/io.polyglotic.Polyglotic.desktop"
dbus-run-session -- bash -c '
  pipewire > /out/pipewire.log 2>&1 &
  sleep 1; wireplumber > /out/wireplumber.log 2>&1 &
  gnome-shell --headless --wayland --virtual-monitor 1280x800 --wayland-display wayland-570 \
    > /out/gnome-shell.log 2>&1 & shell=$!
  for _ in $(seq 60); do [ -S "$XDG_RUNTIME_DIR/wayland-570" ] && break; sleep 0.5; done
  export WAYLAND_DISPLAY=wayland-570
  sleep 6
  dbus-update-activation-environment WAYLAND_DISPLAY XDG_CURRENT_DESKTOP XDG_SESSION_TYPE \
    XDG_RUNTIME_DIR XDG_DATA_HOME DISPLAY 2>/out/activation.log
  export POLYGLOTIC_DESK_PICTURES=/out/desk; mkdir -p /out/desk
  uv run --no-sync python -m tools.linux_desktop_pictures serve /out/desk gnome > /out/pictures.log 2>&1 &
  timeout 180 uv run --no-sync python probe570/portal.py /out/portal.json > /out/portal.out 2>&1
  touch /out/desk/stop; sleep 1
  kill $shell 2>/dev/null
  pkill -f xdg-desktop-portal 2>/dev/null || true'
cat /out/portal.json 2>/dev/null || tail -30 /out/portal.out
