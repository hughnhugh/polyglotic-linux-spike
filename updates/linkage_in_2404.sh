#!/usr/bin/env bash
# 547: in a clean ubuntu:24.04 container - what the bundle needs from the
# system, which of those Ubuntu 24.04's desktop image installs (its
# manifest), and whether the app starts on xcb without libxcb-cursor0:
# bundled, and with the bundle's copy removed.
#   docker run --rm -e GITHUB_ACTIONS -v "$PWD:/w" -w /w ubuntu:24.04 bash updates/linkage_in_2404.sh
set -uo pipefail
[ "${GITHUB_ACTIONS:-}" = true ] || { echo "runs only on GitHub's runners"; exit 2; }
export DEBIAN_FRONTEND=noninteractive
log=/w/out/linkage_2404.log
exec > >(tee -a "$log") 2>&1
b=/w/build/1.0.0/toy547
grep -E '^PRETTY_NAME=' /etc/os-release
apt-get update -qq
apt-get install -y -qq --no-install-recommends xvfb xauth curl ca-certificates apt-file > /dev/null
echo "== libxcb-cursor0 here? $(dpkg -s libxcb-cursor0 > /dev/null 2>&1 && echo yes || echo no)"

echo "== Ubuntu 24.04 desktop's manifest"
man=/tmp/desktop.manifest
for p in 5 4 3; do
  curl -fsSL "https://releases.ubuntu.com/24.04/ubuntu-24.04.$p-desktop-amd64.manifest" -o "$man" && { echo "read ubuntu-24.04.$p-desktop-amd64.manifest"; break; }
done
for pkg in libxcb-cursor0 libfuse2t64 fuse3 libfuse3-3 libxkbcommon-x11-0 libxcb-icccm4 libegl1; do
  printf '%-22s %s\n' "$pkg" "$(grep -E "^$pkg(:amd64)?\s" "$man" | awk '{print $2}' || true)"
done

echo "== sonames the bundle needs that this container (with Xvfb) lacks"
find "$b" -type f \( -name '*.so*' -o -name toy547 \) -print0 \
  | xargs -0 -n 50 ldd 2>/dev/null | grep 'not found' | awk '{print $1}' | sort -u > /tmp/missing
cat /tmp/missing
apt-file update > /dev/null 2>&1
: > /tmp/pkgs
while read -r so; do
  pkg="$(apt-file search -l "x86_64-linux-gnu/$so" 2>/dev/null | head -1)"
  ondesk="no"
  [ -n "$pkg" ] && grep -q -E "^$pkg(:amd64)?\s" "$man" && ondesk="yes"
  printf '%-34s %-26s on the desktop: %s\n' "$so" "${pkg:-?}" "$ondesk"
  [ "$ondesk" = yes ] && [ "$pkg" != libxcb-cursor0 ] && echo "$pkg" >> /tmp/pkgs
done < /tmp/missing
echo "== installing what the desktop has (never libxcb-cursor0)"
sort -u /tmp/pkgs | tr '\n' ' '; echo
sort -u /tmp/pkgs | xargs -r apt-get install -y -qq --no-install-recommends > /dev/null
echo "libxcb-cursor0 here? $(dpkg -s libxcb-cursor0 > /dev/null 2>&1 && echo yes || echo no)"
echo "still missing:"
find "$b" -type f \( -name '*.so*' -o -name toy547 \) -print0 \
  | xargs -0 -n 50 ldd 2>/dev/null | grep 'not found' | awk '{print $1}' | sort -u

Xvfb :98 -screen 0 1024x768x24 > /dev/null 2>&1 &
sleep 2
export DISPLAY=:98 TOY547_MARKER=/tmp/m.jsonl
echo "== A: the bundle as built (libxcb-cursor bundled: $(find "$b" -name 'libxcb-cursor*' | wc -l) file)"
timeout 30 "$b/toy547" -platform xcb; echo "exit $?"
cp -r "$b" /tmp/nocursor
find /tmp/nocursor -name 'libxcb-cursor*' -print -delete
echo "== B: the same bundle without its libxcb-cursor"
timeout 30 /tmp/nocursor/toy547 -platform xcb; echo "exit $?"
echo "== C: the packed AppImage, no FUSE in a container: APPIMAGE_EXTRACT_AND_RUN=1"
a="$(ls /w/installers/*-1.0.0.AppImage | head -1)"
cp "$a" /tmp/toy.AppImage && chmod +x /tmp/toy.AppImage
timeout 60 /tmp/toy.AppImage -platform xcb; echo "exit (no env) $?"
APPIMAGE_EXTRACT_AND_RUN=1 timeout 60 /tmp/toy.AppImage -platform xcb; echo "exit $?"
echo "== the marker"
cat /tmp/m.jsonl 2>/dev/null || echo "(empty)"
