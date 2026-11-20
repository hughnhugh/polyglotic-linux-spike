#!/usr/bin/env bash
# 570: which desktops already use the app's hotkey candidates, and which
# have the GlobalShortcuts portal - read from each distribution's own
# packages (their default settings), on GitHub's runner or in a container.
#
#   bash probe570/shortcuts.sh NAME OUT     (NAME: ubuntu2404, ubuntu2604, fedora45, debian13, arch)
set -uo pipefail
name="${1:?name}"; out="${2:?out}"; mkdir -p "$out"; log="$out/$name.txt"
exec > >(tee "$log") 2>&1
. /etc/os-release; echo "== $PRETTY_NAME"
sudo_() { if [ "$(id -u)" = 0 ]; then "$@"; else sudo "$@"; fi; }
case "$name" in
ubuntu*|debian*)
  export DEBIAN_FRONTEND=noninteractive
  sudo_ apt-get update -q > /dev/null
  base="libglib2.0-bin gsettings-desktop-schemas gnome-settings-daemon-common mutter-common gnome-shell-common xdg-desktop-portal xdg-desktop-portal-gnome xdg-desktop-portal-kde"
  more="cinnamon-desktop-data muffin-common mate-settings-daemon-common marco-common xfce4-settings xfwm4 ubuntu-settings kwin-common plasma-workspace kscreenlocker"
  sudo_ apt-get install -y -q --no-install-recommends $base > /dev/null 2>&1 || echo "(some base packages missing)"
  for p in $more; do sudo_ apt-get install -y -q --no-install-recommends "$p" > /dev/null 2>&1 || echo "(no $p here)"; done
  echo "== versions"; dpkg-query -W -f='${Package} ${Version}\n' xdg-desktop-portal xdg-desktop-portal-gnome xdg-desktop-portal-kde gnome-shell-common mutter-common cinnamon-desktop-data mate-settings-daemon-common xfce4-settings kwin-common kscreenlocker 2>/dev/null
  ;;
fedora*)
  dnf -y -q install --skip-unavailable glib2 gsettings-desktop-schemas gnome-settings-daemon mutter gnome-shell \
    xdg-desktop-portal xdg-desktop-portal-gnome xdg-desktop-portal-kde kwin kscreenlocker plasma-workspace \
    cinnamon-desktop mate-settings-daemon xfce4-settings > /dev/null 2>&1 || echo "(dnf said something)"
  echo "== versions"; rpm -q xdg-desktop-portal xdg-desktop-portal-gnome xdg-desktop-portal-kde gnome-shell mutter kwin kscreenlocker cinnamon-desktop mate-settings-daemon xfce4-settings 2>/dev/null
  ;;
arch*)
  pacman -Sy --noconfirm --needed glib2 gsettings-desktop-schemas gnome-settings-daemon mutter gnome-shell \
    xdg-desktop-portal xdg-desktop-portal-gnome xdg-desktop-portal-kde kwin kscreenlocker > /dev/null 2>&1 || echo "(pacman said something)"
  echo "== versions"; pacman -Q xdg-desktop-portal xdg-desktop-portal-gnome xdg-desktop-portal-kde gnome-shell kwin 2>/dev/null
  ;;
esac
echo "== portals: each backend's interfaces"
for f in /usr/share/xdg-desktop-portal/portals/*.portal; do
  [ -f "$f" ] && echo "$(basename "$f"): $(grep -E '^(Interfaces|UseIn)=' "$f" | tr '\n' ' ')"
done
echo "== the host Registry (xdg-desktop-portal 1.19.4+)"
for b in /usr/libexec/xdg-desktop-portal /usr/lib/xdg-desktop-portal; do
  [ -x "$b" ] && { grep -c "org.freedesktop.host.portal.Registry" "$b" | sed "s/^/$b mentions Registry: /"; }
done
echo "== GSettings keybindings with Ctrl+Alt, Super+Alt or Ctrl+Super and L, P or H (every schema installed)"
glib-compile-schemas /usr/share/glib-2.0/schemas 2>/dev/null
GSETTINGS_BACKEND=memory gsettings list-recursively 2>/dev/null \
  | grep -iE "<(control|primary|ctrl)>|<super>|<alt>" \
  | grep -iE "((<(control|primary|ctrl)>|<alt>|<shift>|<super>)+)[lph]['\"]" | sort -u
echo "== every GSettings binding with both Ctrl and Alt (any key)"
GSETTINGS_BACKEND=memory gsettings list-recursively 2>/dev/null \
  | grep -iE "<(control|primary|ctrl)><alt>|<alt><(control|primary|ctrl)>" | sort -u
echo "== Xfce's defaults"
for f in /etc/xdg/xfce4/xfconf/xfce-perchannel-xml/xfce4-keyboard-shortcuts.xml; do
  [ -f "$f" ] && grep -iE '<(primary|control)>.*<alt>|<alt>.*<(primary|control)>|<super>' "$f" | sed 's/^ *//'
done
echo "== KDE's kglobalaccel files mentioning Ctrl+Alt"
grep -rhiE "Ctrl\+Alt|Alt\+Ctrl|Meta\+Alt|Meta\+Ctrl" /usr/share/kglobalaccel 2>/dev/null | sort -u | head -40
echo "== KWin: what X11 apps hear while a Wayland app has the keyboard (XwaylandEavesdrops)"
for f in /usr/share/config.kcfg/kwin.kcfg; do
  [ -f "$f" ] && grep -A12 -i 'XwaylandEavesdrops' "$f" | head -16
done
echo "== KDE's screen locker binary: its default keys (strings)"
for b in /usr/lib*/libKScreenLocker.so* /usr/lib/*/libKScreenLocker.so* ; do
  [ -f "$b" ] && strings "$b" | grep -iE "^(Lock Session|Screensaver)$" | head -3
done
echo "== done"
