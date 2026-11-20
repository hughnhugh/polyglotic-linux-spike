#!/usr/bin/env bash
# 547: linkage only - the AppImage built on Ubuntu 22.04 in an ubuntu:26.04
# container (no FUSE there: APPIMAGE_EXTRACT_AND_RUN=1), with the libraries
# the bundle needs from the system; then without its bundled fontconfig and
# freetype.
#   docker run --rm -e GITHUB_ACTIONS -v "$PWD:/w" -w /w ubuntu:26.04 bash updates/ubuntu2604.sh
set -uo pipefail
[ "${GITHUB_ACTIONS:-}" = true ] || { echo "runs only on GitHub's runners"; exit 2; }
export DEBIAN_FRONTEND=noninteractive
log=/w/out/ubuntu2604.log
exec > >(tee -a "$log") 2>&1
grep -E '^PRETTY_NAME=' /etc/os-release
ldd --version | sed -n 1p
apt-get update -qq
apt-get install -y -qq --no-install-recommends xvfb xauth fonts-dejavu-core libegl1 libxkbcommon-x11-0 \
  libxcb-icccm4 libxcb-image0 libxcb-keysyms1 libxcb-render-util0 libxcb-shape0 libxcb-xkb1 \
  libfontconfig1 libdbus-1-3 > /dev/null
echo "libxcb-cursor0 here? $(dpkg -s libxcb-cursor0 > /dev/null 2>&1 && echo yes || echo no); fontconfig: $(dpkg-query -W -f '${Version}' libfontconfig1)"
Xvfb :96 -screen 0 1024x768x24 > /dev/null 2>&1 &
sleep 2
export DISPLAY=:96 TOY547_MARKER=/tmp/m.jsonl
a="$(ls /w/installers/*-1.0.0.AppImage | head -1)"
cp "$a" /tmp/toy.AppImage && chmod +x /tmp/toy.AppImage
echo "== A: as packed"
APPIMAGE_EXTRACT_AND_RUN=1 timeout 60 /tmp/toy.AppImage -platform xcb > /tmp/a.txt 2>&1; echo "exit $?"
echo "fontconfig complaints: $(grep -c Fontconfig /tmp/a.txt)"; grep -v Fontconfig /tmp/a.txt | grep -v -E 'locale|UTF-8|reconfigure|manual' | cut -c1-200
echo "== B: without the bundled libfontconfig and libfreetype"
cd /tmp && /tmp/toy.AppImage --appimage-extract > /dev/null && cd - > /dev/null
find /tmp/squashfs-root \( -name 'libfontconfig.so*' -o -name 'libfreetype.so*' \) -delete
timeout 60 /tmp/squashfs-root/usr/bin/toy547 -platform xcb > /tmp/b.txt 2>&1; echo "exit $?"
echo "fontconfig complaints: $(grep -c Fontconfig /tmp/b.txt)"; grep -v Fontconfig /tmp/b.txt | grep -v -E 'locale|UTF-8|reconfigure|manual|VelopackApp' | cut -c1-200
