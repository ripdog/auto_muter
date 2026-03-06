# Maintainer: ripdog
pkgname=auto-muter-git
pkgver=r1.4e95938
pkgrel=1
pkgdesc="Auto mutes specific applications when they lose focus"
arch=('any')
url="https://github.com/ripdog/auto_muter"
license=('MIT')
depends=('uv' 'pulseaudio-utils')
makedepends=('git')
provides=('auto-muter')
conflicts=('auto-muter')
source=("auto_muter::git+https://github.com/ripdog/auto_muter.git")
sha256sums=('SKIP')

pkgver() {
  cd auto_muter
  printf "r%s.%s" "$(git rev-list --count HEAD)" "$(git rev-parse --short HEAD)"
}

package() {
  cd auto_muter
  
  # Install the Python service script
  install -Dm755 focus_audio_manager.py "$pkgdir/usr/bin/focus_audio_manager"
  
  # Install the KWin script system-wide
  install -d "$pkgdir/usr/share/kwin/scripts/auto_muter_kwin"
  cp -r auto_muter_kwin/* "$pkgdir/usr/share/kwin/scripts/auto_muter_kwin/"
  
  # Install the systemd user service
  install -Dm644 focus-audio-manager.service "$pkgdir/usr/lib/systemd/user/focus-audio-manager.service"
  
  # Install README documentation
  install -Dm644 README.md "$pkgdir/usr/share/doc/$pkgname/README.md"
}