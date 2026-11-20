#!/usr/bin/env bash
# 570: the probe on Fedora 45's GNOME or KDE, in a container (from
# tools/linux_in_fedora.sh, 550).
set -euo pipefail
desktop="${1:?gnome or kde}"; out="$(realpath -m "${2:?OUT}")"
if [ -z "${IN_FEDORA_570:-}" ]; then
  mkdir -p "$out"; root="$(cd "$(dirname "$0")/.." && pwd)"; devices=()
  if [ "$desktop" = kde ]; then sudo modprobe vgem && sudo modprobe vkms; devices=(--device /dev/dri); fi
  exec docker run --rm --cap-add SYS_NICE "${devices[@]}" -e GITHUB_ACTIONS=true -e IN_FEDORA_570=1 \
    -v "$root:/w" -v "$out:/out" -v "$(command -v uv):/usr/local/bin/uv:ro" -w /w fedora:45 \
    bash /w/probe570/in_fedora.sh "$desktop" /out
fi
common=(xorg-x11-server-Xwayland pipewire wireplumber pipewire-pulseaudio pulseaudio-utils pipewire-utils
  pulseaudio-libs gnome-keyring dbus-daemon dbus-tools mesa-dri-drivers mesa-libEGL mesa-libGL
  libglvnd-egl xcb-util-cursor xcb-util-wm xcb-util-image xcb-util-keysyms xcb-util-renderutil
  libxkbcommon-x11 libwayland-client libwayland-cursor libwayland-egl fontconfig libXtst
  google-noto-sans-fonts findutils procps-ng plasma-wayland-protocols)
if [ "$desktop" = kde ]; then more=(kwin); else more=(mutter); fi
dnf -y -q install --skip-unavailable "${common[@]}" "${more[@]}" > /tmp/dnf.log 2>&1 || { tail -30 /tmp/dnf.log; exit 1; }
rpm -q mutter kwin xorg-x11-server-Xwayland 2>/dev/null | grep -v "not installed" > /out/versions.txt || true
export UV_PROJECT_ENVIRONMENT=/tmp/venv UV_PYTHON=3.12.15 UV_PYTHON_PREFERENCE=only-managed
uv sync --locked > /out/uv-sync.log 2>&1 || { tail -30 /out/uv-sync.log; exit 1; }
export LINUX_SESSION_SCREEN="$desktop"
dbus-run-session -- bash tools/linux_session.sh /out/session -- bash probe570/run.sh /out
