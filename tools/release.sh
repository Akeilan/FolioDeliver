#!/bin/bash
# Folio Show (formerly Folio Deliver) release checks: engine tests, UI tests (source), the rename
# test, debs (folio-show + transitional folio-deliver), the upgrade from the published Show and the
# installed tests on jammy, nolo and noble, Wayland on noble.   XD=<display> release_show.sh
set -u
R=$(cd "$(dirname "$0")/.." && pwd)
V=$(sed -n 's/^Version: //p' $R/packaging/DEBIAN/control)
# the upgrade is checked from the Show people have now: the one in the published package source
if [ -z "${OLDDEB:-}" ]; then
  PUB=$(mktemp -d)
  git clone -q --depth 1 --branch gh-pages https://github.com/Akeilan/FolioStudio "$PUB" >/dev/null 2>&1
  OLDDEB=$(ls "$PUB"/folio-show_*.deb 2>/dev/null | head -1)
  [ -n "$OLDDEB" ] || { echo "FAIL no published Folio Show to upgrade from"; exit 1; }
fi
/home/claude/mounts.sh
cp $R/engine/out/deliver_core.so /srv/jammy/tmp/deliver_core.so
rsync -a --delete --exclude target --exclude .git $R/ /srv/jammy/src/fdl/
echo "== engine"
chroot /srv/jammy bash -c "cd /src/fdl; for t in tests/test_engine*.py; do PYTHONPATH=/tmp python3 \$t | grep -E '^FAIL|passed|FAILED'; done"
echo "== ui (source)"
chroot /srv/jammy bash -c "cd /src/fdl; for u in ${UI_TESTS:-ui_basic.py ui_more.py ui_anim.py ui_review.py ui_master.py ui_show2.py ui_objects.py ui_media.py ui_b3.py ui_ink_replay.py ui_backlog12.py}; do echo \$u; DISPLAY=:${XD:-99} UI_TIMEOUT=300 sh tests/run_ui.sh \$u 2>&1 | grep -E '^FAIL|UI all|UI FAILED|Traceback'; done"
echo "== rename (source)"
chroot /srv/jammy bash -c "cd /src/fdl; DISPLAY=:${XD:-99} PYTHONPATH=/tmp sh tests/rename_test.sh 2>&1 | grep -E '^FAIL|RENAME|Traceback'"
echo "== themes (X2-01)"
chroot /srv/jammy bash -c "cd /src/fdl; DISPLAY=:${XD:-99} UI_TIMEOUT=1200 sh tests/theme_run.sh 2>&1 | grep -E '^-- |^FAIL|UI all|UI FAILED|Traceback'"
echo "== walk"
chroot /srv/jammy bash -c "cd /src/fdl; DISPLAY=:${XD:-99} UI_TIMEOUT=900 timeout 950 sh tests/run_ui.sh command_walk.py 2>&1 | grep -E 'WALK|Traceback|^  - '"
cp /srv/jammy/tmp/deliver-command-walk.tsv $R/docs/command-walk.tsv 2>/dev/null
echo "not available: $(grep -c NOT_YET $R/docs/command-walk.tsv)"
echo "== debs"
sh $R/build-deb.sh /home/claude/out >/dev/null && ls -la /home/claude/out/folio-show_${V}_amd64.deb /home/claude/out/folio-deliver_${V}_all.deb
echo "== X4-05: against the app it replaces"
bash /home/claude/folio-suite/tools/compare-release.sh folio-show /home/claude/folio-deliver /home/claude/out/folio-show_${V}_amd64.deb || \
  echo "X4-05 FAILED: this candidate shows less than the app it replaces"
for m in /srv/jammy /srv/nolo /srv/noble; do
  cp /home/claude/out/folio-show_${V}_amd64.deb /home/claude/out/folio-deliver_${V}_all.deb $OLDDEB $m/tmp/
  echo "== upgrade from $(basename $OLDDEB) in $m"
  flock /home/claude/.dpkg.lock chroot $m bash -c "export DEBIAN_FRONTEND=noninteractive
    dpkg --force-depends -P folio-show folio-deliver >/dev/null 2>&1
    dpkg -i /tmp/$(basename $OLDDEB) >/dev/null 2>&1 || apt-get -y -f install >/dev/null 2>&1
    echo \"before: \$(dpkg-query -W -f='\${Package} \${Version} ' folio-show folio-deliver 2>/dev/null)\"
    apt-get install -y -q /tmp/folio-show_${V}_amd64.deb /tmp/folio-deliver_${V}_all.deb >/tmp/up.log 2>&1 || { echo FAIL upgrade; tail -5 /tmp/up.log; }
    echo \"after: \$(dpkg-query -W -f='\${Package} \${Version} \${Status}\n' folio-show folio-deliver | tr '\n' ';')\"
    [ -d /usr/lib/folio-deliver ] && echo 'FAIL /usr/lib/folio-deliver left behind'
    [ -x /usr/bin/folio-show ] && [ -e /usr/bin/folio-deliver ] || echo 'FAIL commands'
    apt-get -s remove folio-deliver 2>/dev/null | grep -q '^Remv folio-show' && echo 'FAIL removing the transitional package would take folio-show' || echo 'the transitional package can go; folio-show stays'"
  rm -rf $m/tmp/fdltests; mkdir -p $m/tmp/fdltests; cp -r $R/tests/* $m/tmp/fdltests/
  echo "== installed in $m"
  chroot $m bash -c "cd /tmp/fdltests; DISPLAY=:${XD:-99} sh rename_test.sh installed 2>&1 | grep -E '^FAIL|RENAME|Traceback|--version'"
  for u in ${INST_TESTS:-ui_basic.py ui_review.py ui_master.py ui_show2.py ui_objects.py ui_media.py ui_b3.py ui_backlog12.py}; do
    chroot $m bash -c "cd /tmp/fdltests; DISPLAY=:${XD:-99} UI_TIMEOUT=300 sh run_installed.sh /tmp/fdltests/$u 2>&1 | grep -E '^FAIL|UI all|UI FAILED|Traceback'"
  done
  chroot $m bash -c "cd /tmp/fdltests; DISPLAY=:${XD:-99} UI_TIMEOUT=1200 sh theme_run.sh run_installed.sh 2>&1 | grep -E '^-- |^FAIL|UI all|UI FAILED|Traceback'"
done
echo "== Wayland (Weston) on 24.04: rename and desktop themes"
cp /home/claude/folio-suite/tests/wl.sh /srv/noble/tmp/wl.sh
chroot /srv/noble bash -c "cd /tmp/fdltests; DISPLAY=:${XD:-99} /tmp/wl.sh sh rename_test.sh installed 2>&1 | grep -E '^FAIL|RENAME|Traceback'"
chroot /srv/noble bash -c "cd /tmp/fdltests; DISPLAY=:${XD:-99} UI_TIMEOUT=600 /tmp/wl.sh sh run_installed.sh /tmp/fdltests/ui_backlog12.py 2>&1 | grep -E '^FAIL|UI all|UI FAILED|Traceback'"
chroot /srv/noble bash -c "cd /tmp/fdltests; DISPLAY=:${XD:-99} UI_TIMEOUT=1200 /tmp/wl.sh sh theme_run.sh run_installed.sh 2>&1 | grep -E '^-- |^FAIL|UI all|UI FAILED|checks|Traceback'"
echo "== release done"
