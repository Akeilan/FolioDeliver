#!/bin/sh
# Builds folio-deliver_<version>_amd64.deb from this tree: the Python UI (app/), the Rust
# engine (engine/, built with engine/build-jammy.sh into engine/out/deliver_core.so), the
# template and the icon set (share/).
set -e
HERE="$(cd "$(dirname "$0")" && pwd)"
VERSION="$(sed -n 's/^Version: //p' "$HERE/packaging/DEBIAN/control")"
APPV="$(sed -n 's/^VERSION = "\(.*\)"/\1/p' "$HERE/app/folio_deliver/__init__.py")"
[ "$VERSION" = "$APPV" ] || { echo "version mismatch: control $VERSION, app $APPV"; exit 1; }
OUT="${1:-$HERE}"
STAGE="$(mktemp -d)"
trap 'rm -rf "$STAGE"' EXIT
cp -a "$HERE/packaging/root/." "$STAGE/"
mkdir -p "$STAGE/usr/lib/folio-deliver" "$STAGE/usr/share/folio-deliver"
cp -a "$HERE/app/folio_deliver" "$STAGE/usr/lib/folio-deliver/"
find "$STAGE/usr/lib/folio-deliver" -name '__pycache__' -prune -exec rm -rf {} +
ENGINE="${FOLIO_DELIVER_ENGINE:-$HERE/engine/out/deliver_core.so}"
install -m 644 "$ENGINE" "$STAGE/usr/lib/folio-deliver/deliver_core.so"
cp -a "$HERE/share/templates" "$HERE/share/iconset" "$STAGE/usr/share/folio-deliver/"
mkdir -p "$STAGE/DEBIAN"
cp "$HERE/packaging/DEBIAN/"* "$STAGE/DEBIAN/"
chmod 755 "$STAGE/DEBIAN/postinst" "$STAGE/DEBIAN/prerm" "$STAGE/DEBIAN/postrm"
SIZE="$(du -sk "$STAGE" | cut -f1)"
sed -i "s/^Installed-Size: .*/Installed-Size: $SIZE/" "$STAGE/DEBIAN/control"
dpkg-deb --root-owner-group --build -Zxz "$STAGE" "$OUT/folio-deliver_${VERSION}_amd64.deb"
echo "Built $OUT/folio-deliver_${VERSION}_amd64.deb"
