#!/bin/sh
# Folio Deliver reuses Folio Writer's engine crate for packages, XML, fonts, shapes, pictures,
# effects and charts. This copies its source in (the Writer repo is the place to change it).
set -e
HERE="$(cd "$(dirname "$0")/.." && pwd)"
SRC="${WRITER_CORE:-$HERE/../folio-writer/core}"
rm -rf "$HERE/vendor/folio_core"
mkdir -p "$HERE/vendor/folio_core"
cp -r "$SRC/src" "$HERE/vendor/folio_core/"
sed -e 's/crate-type = \["cdylib", "rlib"\]/crate-type = ["rlib"]/' "$SRC/Cargo.toml" > "$HERE/vendor/folio_core/Cargo.toml"
python3 - "$HERE/vendor/folio_core/Cargo.toml" <<'PY'
import re, sys
p = sys.argv[1]
s = open(p).read()
s = re.sub(r"\n\[profile\.[^\]]*\][^\[]*", "\n", s)
open(p, "w").write(s)
PY
# Show relies on the escaper leaving out characters XML can't hold (S12-02)
grep -q "fn xml_char_ok" "$HERE/vendor/folio_core/src/xml.rs" || {
  echo "the new folio_core writes control characters into XML: put xml_char_ok back into xml.rs (S12-02)" >&2; exit 1; }
echo "vendored folio_core from $SRC"
