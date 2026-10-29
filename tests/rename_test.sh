#!/bin/sh
# X3-09: Folio Show under its new name, its old command, and settings carried over from Folio Deliver.
#   rename_test.sh            the source tree        rename_test.sh installed   the installed package
HERE="$(cd "$(dirname "$0")" && pwd)"
rc=0
CFG="$(mktemp -d)"
mkdir -p "$CFG/folio-deliver"
echo '{"recent": [], "author": "Rena Testa"}' > "$CFG/folio-deliver/settings.json"
export XDG_CONFIG_HOME="$CFG" RENAME_EXPECT_AUTHOR="Rena Testa" FOLIO_TEST_SCRIPT="$HERE/ui_rename.py" FOLIO_TEST_DELAY=1500
if [ "$1" = installed ]; then
  v=$(folio-show --version); echo "folio-show --version: $v"; echo "$v" | grep -q "^Folio Show " || rc=1
  v=$(folio-deliver --version); echo "folio-deliver --version: $v"; echo "$v" | grep -q "^Folio Show " || rc=1
  ( cd / && timeout ${UI_TIMEOUT:-200} folio-deliver ) || rc=1          # the old command, as old scripts call it
  rm -rf "$CFG/folio-show"
  ( cd / && timeout ${UI_TIMEOUT:-200} folio-show ) || rc=1
  test -f /usr/share/applications/org.folio.Show.desktop && grep -q '^Name=Folio Show' /usr/share/applications/org.folio.Show.desktop || { echo "FAIL desktop file"; rc=1; }
  grep -q '^NoDisplay=true' /usr/share/applications/org.folio.Deliver.desktop || { echo "FAIL old desktop id kept hidden"; rc=1; }
  test -e /usr/share/icons/hicolor/48x48/apps/folio-deliver.png || { echo "FAIL old icon name"; rc=1; }
else
  export FOLIO_SHOW_SHARE="$HERE/../share"
  ( cd "$HERE/../app" && timeout ${UI_TIMEOUT:-200} python3 -m folio_deliver ) || rc=1
fi
rm -rf "$CFG"
[ $rc = 0 ] && echo "RENAME all passed" || echo "RENAME FAILED"
exit $rc
