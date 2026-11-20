#!/usr/bin/env bash
# 547: linkage only - does the AppImage built on Ubuntu 22.04 start in a
# Fedora container (no FUSE there: APPIMAGE_EXTRACT_AND_RUN=1)?
#   docker run --rm -e GITHUB_ACTIONS -v "$PWD:/w" -w /w fedora:latest bash updates/fedora.sh
set -uo pipefail
[ "${GITHUB_ACTIONS:-}" = true ] || { echo "runs only on GitHub's runners"; exit 2; }
log=/w/out/fedora.log
exec > >(tee -a "$log") 2>&1
grep -E '^PRETTY_NAME=' /etc/os-release
ldd --version | head -1
dnf -y -q install xorg-x11-server-Xvfb findutils libxkbcommon-x11 xcb-util-wm xcb-util-image \
  xcb-util-keysyms xcb-util-renderutil libglvnd-egl libglvnd-glx fontconfig dbus-libs > /dev/null 2>&1
echo "xcb-util-cursor here? $(rpm -q xcb-util-cursor > /dev/null 2>&1 && echo yes || echo no)"
b=/w/build/1.0.0/toy547
echo "== sonames still missing for the bundle"
find "$b" -type f \( -name '*.so*' -o -name toy547 \) -print0 \
  | xargs -0 -n 50 ldd 2>/dev/null | grep 'not found' | awk '{print $1}' | sort -u
Xvfb :97 -screen 0 1024x768x24 > /dev/null 2>&1 &
sleep 2
export DISPLAY=:97 TOY547_MARKER=/tmp/m.jsonl
a="$(ls /w/installers/*-1.0.0.AppImage | head -1)"
cp "$a" /tmp/toy.AppImage && chmod +x /tmp/toy.AppImage
APPIMAGE_EXTRACT_AND_RUN=1 timeout 60 /tmp/toy.AppImage -platform xcb; echo "exit $?"
cat /tmp/m.jsonl 2>/dev/null || echo "(empty)"
