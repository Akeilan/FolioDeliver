#!/bin/sh
# Builds folio-show_<version>_amd64.deb from this tree: the Python UI (app/), the Rust
# engine (engine/, built with engine/build-jammy.sh into engine/out/deliver_core.so), the
# template and the icon set (share/). Also folio-deliver_<version>_all.deb, the transitional
# package that moves Folio Deliver's users over to Folio Show (the app's name before 0.9.0).
set -e
HERE="$(cd "$(dirname "$0")" && pwd)"
VERSION="$(sed -n 's/^Version: //p' "$HERE/packaging/DEBIAN/control")"
APPV="$(sed -n 's/^VERSION = "\(.*\)"/\1/p' "$HERE/app/folio_deliver/__init__.py")"
[ "$VERSION" = "$APPV" ] || { echo "version mismatch: control $VERSION, app $APPV"; exit 1; }
OUT="${1:-$HERE}"
STAGE="$(mktemp -d)"
OLD="$(mktemp -d)"
trap 'rm -rf "$STAGE" "$OLD"' EXIT
cp -a "$HERE/packaging/root/." "$STAGE/"
mkdir -p "$STAGE/usr/lib/folio-show" "$STAGE/usr/share/folio-show"
cp -a "$HERE/app/folio_deliver" "$STAGE/usr/lib/folio-show/"
find "$STAGE/usr/lib/folio-show" -name '__pycache__' -prune -exec rm -rf {} +
ENGINE="${FOLIO_DELIVER_ENGINE:-$HERE/engine/out/deliver_core.so}"
install -m 644 "$ENGINE" "$STAGE/usr/lib/folio-show/deliver_core.so"
cp -a "$HERE/share/templates" "$HERE/share/iconset" "$STAGE/usr/share/folio-show/"
# the old names keep working: the command, and the icon (dock pins, file-type icons)
ln -s folio-show "$STAGE/usr/bin/folio-deliver"
for d in "$STAGE"/usr/share/icons/hicolor/*/apps; do
  for f in "$d"/folio-show.*; do ln -s "$(basename "$f")" "$d/folio-deliver.${f##*.}"; done
done
mkdir -p "$STAGE/DEBIAN"
cp "$HERE/packaging/DEBIAN/"* "$STAGE/DEBIAN/"
chmod 755 "$STAGE/DEBIAN/postinst" "$STAGE/DEBIAN/prerm" "$STAGE/DEBIAN/postrm"
SIZE="$(du -sk "$STAGE" | cut -f1)"
sed -i "s/^Installed-Size: .*/Installed-Size: $SIZE/" "$STAGE/DEBIAN/control"
dpkg-deb --root-owner-group --build -Zxz "$STAGE" "$OUT/folio-show_${VERSION}_amd64.deb"
echo "Built $OUT/folio-show_${VERSION}_amd64.deb"

# ---- transitional folio-deliver
mkdir -p "$OLD/DEBIAN" "$OLD/usr/share/doc/folio-deliver"
cat > "$OLD/usr/share/doc/folio-deliver/README" <<TXT
Folio Deliver is now called Folio Show. This package only brings in folio-show
and can be removed; the folio-deliver command keeps working.
TXT
cat > "$OLD/DEBIAN/control" <<CTL
Package: folio-deliver
Version: $VERSION
Section: oldlibs
Priority: optional
Architecture: all
Depends: folio-show (>= $VERSION)
Maintainer: Ron Shillings <ron.shillings@gmail.com>
Description: transitional package for Folio Show
 Folio Deliver has been renamed Folio Show. This package moves existing
 installations over to folio-show and can be removed afterwards.
CTL
dpkg-deb --root-owner-group --build -Zxz "$OLD" "$OUT/folio-deliver_${VERSION}_all.deb"
echo "Built $OUT/folio-deliver_${VERSION}_all.deb"
