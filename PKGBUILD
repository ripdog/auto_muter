# Maintainer: ripdog
pkgname=auto-muter-git
pkgver=r7.d80cae8
pkgrel=1
pkgdesc="Auto mutes specific applications when they lose focus"
arch=('any')
url="https://github.com/ripdog/auto_muter"
license=('MIT')
depends=('python' 'python-sdbus' 'python-asyncinotify' 'libpulse' 'pyside6')
makedepends=('git')
provides=('auto-muter')
conflicts=('auto-muter')
source=()
sha256sums=()

pkgver() {
  cd "$startdir"
  printf "r%s.%s" "$(git rev-list --count HEAD)" "$(git rev-parse --short HEAD)"
}

package() {
  # Install the Python service script
  install -Dm755 "$startdir/focus_audio_manager.py" "$pkgdir/usr/bin/focus_audio_manager"
  
  # Install the Config GUI
  install -Dm755 "$startdir/config_gui.py" "$pkgdir/usr/bin/auto_muter_config"
  
  # Install the Desktop file and Icon
  install -Dm644 "$startdir/auto-muter.desktop" "$pkgdir/usr/share/applications/auto-muter.desktop"
  install -Dm644 "$startdir/auto-muter.svg" "$pkgdir/usr/share/icons/hicolor/scalable/apps/auto-muter.svg"
  
  # Install the KWin script system-wide
  install -d "$pkgdir/usr/share/kwin/scripts/auto_muter_kwin"
  cp -r "$startdir/auto_muter_kwin"/* "$pkgdir/usr/share/kwin/scripts/auto_muter_kwin/"
  
  # Install the systemd user service
  install -Dm644 "$startdir/focus-audio-manager.service" "$pkgdir/usr/lib/systemd/user/focus-audio-manager.service"
  
  # Install README documentation
  install -Dm644 "$startdir/README.md" "$pkgdir/usr/share/doc/$pkgname/README.md"
}
