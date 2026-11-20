#!/usr/bin/env bash
# The desktop's manners on a Linux desktop (polyglotic-hq 571): the tray and
# its menu where the desktop has one, the window back from the launcher where
# it has none (tools/linux_manners_check.py), on GitHub's runners only.
#
#   bash tools/linux_manners.sh gnome|xfce|kde OUT
#
# - gnome: GNOME's own window manager (mutter, headless, with XWayland), and
#   no tray - as Fedora's GNOME is, and Ubuntu's without its extension;
# - xfce: Xfce's window manager and panel, its status tray in it, on an X
#   screen (Xvfb);
# - kde: KDE's KWin (headless, with XWayland) in a fedora:45 container, KDE's
#   StatusNotifierWatcher (kded6's) and Plasma's shell where it starts there.
#   Without Plasma's shell a stand-in host registers with KDE's watcher - the
#   app's side is the same either way: its menu read over D-Bus.
#
# Pictures: OUT/<desktop>/*.png by the app's own windows' grab(), and the
# virtual screen of the runner (never a person's) as desk-*.png.
set -uo pipefail
if [ "${GITHUB_ACTIONS:-}" != true ] || [ "$(uname -s)" != Linux ]; then
  echo "571: this runs only on GitHub's Linux runners"; exit 2
fi
desktop="${1:?gnome, xfce or kde}"; out="$(realpath -m "${2:?OUT}")"
root="$(cd "$(dirname "$0")/.." && pwd)"
mkdir -p "$out"

if [ "$desktop" = kde ] && [ -z "${IN_FEDORA_571:-}" ]; then
  sudo modprobe vgem && sudo modprobe vkms  # KWin needs a render device (547)
  exec docker run --rm --cap-add SYS_NICE --device /dev/dri \
    -e GITHUB_ACTIONS=true -e IN_FEDORA_571=1 \
    -v "$root:/w" -v "$out:/out" -v "$(command -v uv):/usr/local/bin/uv:ro" \
    -w /w fedora:45 bash /w/tools/linux_manners.sh kde /out
fi

if [ -n "${IN_FEDORA_571:-}" ]; then
  dnf -y -q install --skip-unavailable kwin plasma-workspace kf6-kded xorg-x11-server-Xwayland \
    pipewire wireplumber pipewire-pulseaudio pulseaudio-utils pipewire-utils gnome-keyring \
    dbus-daemon dbus-tools mesa-dri-drivers mesa-libEGL mesa-libGL libglvnd-egl xcb-util-cursor \
    xcb-util-wm xcb-util-image xcb-util-keysyms xcb-util-renderutil libxkbcommon-x11 \
    libwayland-client libwayland-cursor libwayland-egl fontconfig google-noto-sans-fonts \
    google-noto-sans-cjk-vf-fonts findutils procps-ng glib2 > /tmp/dnf.log 2>&1 \
    || { tail -30 /tmp/dnf.log; exit 1; }
  rpm -q kwin plasma-workspace kf6-kded 2>/dev/null | tee "$out/versions.txt"
  export UV_PROJECT_ENVIRONMENT=/tmp/venv UV_PYTHON=3.12.15 UV_PYTHON_PREFERENCE=only-managed
  uv sync --locked > "$out/uv-sync.log" 2>&1 || { tail -30 "$out/uv-sync.log"; exit 1; }
  uv run --no-sync python -m tools.i18n build > /dev/null
  export LINUX_SESSION_SCREEN=kde IN_SESSION_571=1
  exec dbus-run-session -- bash tools/linux_session.sh "$out/session" -- \
    bash tools/linux_manners.sh kde "$out"
fi

if [ -z "${IN_SESSION_571:-}" ]; then  # the runner's own session, then here again
  case "$desktop" in gnome) export LINUX_SESSION_SCREEN=gnome ;; *) export LINUX_SESSION_SCREEN=xvfb ;; esac
  export IN_SESSION_571=1
  exec dbus-run-session -- bash tools/linux_session.sh "$out/session" -- \
    bash tools/linux_manners.sh "$desktop" "$out"
fi

started=()
tray=no
case "$desktop" in
xfce)
  export XDG_CURRENT_DESKTOP=XFCE XDG_SESSION_TYPE=x11
  conf="$HOME/.config/xfce4/xfconf/xfce-perchannel-xml"
  mkdir -p "$conf"
  # the panel's own default (with its status tray), never its first-run question
  cp /etc/xdg/xfce4/panel/default.xml "$conf/xfce4-panel.xml" 2>/dev/null || true
  xfwm4 > "$out/xfwm4.log" 2>&1 & started+=($!)
  xfce4-panel > "$out/xfce4-panel.log" 2>&1 & started+=($!)
  tray=yes
  ;;
kde)
  export XDG_CURRENT_DESKTOP=KDE XDG_SESSION_TYPE=wayland KDE_FULL_SESSION=true
  kded6 > "$out/kded6.log" 2>&1 & started+=($!)
  sleep 3
  QT_QPA_PLATFORM=wayland plasmashell > "$out/plasmashell.log" 2>&1 & started+=($!)
  tray=yes
  ;;
gnome)
  export XDG_CURRENT_DESKTOP=GNOME XDG_SESSION_TYPE=wayland
  ;;
esac
sleep 10
if [ "$tray" = yes ]; then  # a host for KDE's watcher where Plasma's shell didn't start
  uv run --no-sync python -m tools.linux_tray_menu "$out/tray-host.json" --host \
    > "$out/tray-host.log" 2>&1 & started+=($!)
  sleep 3
fi
QT_QPA_PLATFORM=xcb uv run --no-sync python -m tools.linux_manners_check "$out/$desktop" \
  --tray "$tray"
code=$?
for pid in "${started[@]}"; do kill "$pid" 2>/dev/null; done
exit "$code"
