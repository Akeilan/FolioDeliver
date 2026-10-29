#!/bin/bash
# Folio Show (formerly Folio Deliver) release checks: engine tests, UI tests (source), the rename
# test, debs (folio-show + transitional folio-deliver), the upgrade from folio-deliver 0.8.0 and the
# installed tests on jammy, nolo and noble, Wayland on noble.   XD=<display> release_show.sh
set -u
R=/home/claude/folio-deliver
V=$(sed -n 's/^Version: //p' $R/packaging/DEBIAN/control)
OLDDEB=${OLDDEB:-/home/claude/out/folio-deliver_0.8.0_amd64.deb}
/home/claude/mounts.sh
cp $R/engine/out/deliver_core.so /srv/jammy/tmp/deliver_core.so
rsync -a --delete --exclude target --exclude .git $R/ /srv/jammy/src/fdl/
echo "== engine"
chroot /srv/jammy bash -c "cd /src/fdl; for t in tests/test_engine*.py; do PYTHONPATH=/tmp python3 \$t | grep -E '^FAIL|passed|FAILED'; done"
echo "== ui (source)"
chroot /srv/jammy bash -c "cd /src/fdl; for u in ${UI_TESTS:-ui_basic.py ui_more.py ui_anim.py ui_review.py ui_master.py ui_show2.py ui_objects.py ui_media.py ui_b3.py}; do echo \$u; DISPLAY=:${XD:-99} UI_TIMEOUT=300 sh tests/run_ui.sh \$u 2>&1 | grep -E '^FAIL|UI all|UI FAILED|Traceback'; done"
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
for m in /srv/jammy /srv/nolo /srv/noble; do
  cp /home/claude/out/folio-show_${V}_amd64.deb /home/claude/out/folio-deliver_${V}_all.deb $OLDDEB $m/tmp/
  echo "== upgrade from Folio Deliver 0.8.0 in $m"
  flock /home/claude/.dpkg.lock chroot $m bash -c "export DEBIAN_FRONTEND=noninteractive
    dpkg --force-depends -P folio-show folio-deliver >/dev/null 2>&1
    dpkg -i /tmp/$(basename $OLDDEB) >/dev/null 2>&1 || apt-get -y -f install >/dev/null 2>&1
    echo \"before: \$(dpkg-query -W -f='\${Package} \${Version}' folio-deliver)\"
    apt-get install -y -q /tmp/folio-show_${V}_amd64.deb /tmp/folio-deliver_${V}_all.deb >/tmp/up.log 2>&1 || { echo FAIL upgrade; tail -5 /tmp/up.log; }
    echo \"after: \$(dpkg-query -W -f='\${Package} \${Version} \${Status}\n' folio-show folio-deliver | tr '\n' ';')\"
    [ -d /usr/lib/folio-deliver ] && echo 'FAIL /usr/lib/folio-deliver left behind'
    [ -x /usr/bin/folio-show ] && [ -e /usr/bin/folio-deliver ] || echo 'FAIL commands'
    apt-get -s remove folio-deliver 2>/dev/null | grep -q '^Remv folio-show' && echo 'FAIL removing the transitional package would take folio-show' || echo 'the transitional package can go; folio-show stays'"
  rm -rf $m/tmp/fdltests; mkdir -p $m/tmp/fdltests; cp -r $R/tests/* $m/tmp/fdltests/
  echo "== installed in $m"
  chroot $m bash -c "cd /tmp/fdltests; DISPLAY=:${XD:-99} sh rename_test.sh installed 2>&1 | grep -E '^FAIL|RENAME|Traceback|--version'"
  for u in ${INST_TESTS:-ui_basic.py ui_review.py ui_master.py ui_show2.py ui_objects.py ui_media.py ui_b3.py}; do
    chroot $m bash -c "cd /tmp/fdltests; DISPLAY=:${XD:-99} UI_TIMEOUT=300 sh run_installed.sh /tmp/fdltests/$u 2>&1 | grep -E '^FAIL|UI all|UI FAILED|Traceback'"
  done
  chroot $m bash -c "cd /tmp/fdltests; DISPLAY=:${XD:-99} UI_TIMEOUT=1200 sh theme_run.sh run_installed.sh 2>&1 | grep -E '^-- |^FAIL|UI all|UI FAILED|Traceback'"
done
echo "== Wayland (Weston) on 24.04: rename and desktop themes"
cp /home/claude/folio-suite/tests/wl.sh /srv/noble/tmp/wl.sh
chroot /srv/noble bash -c "cd /tmp/fdltests; DISPLAY=:${XD:-99} /tmp/wl.sh sh rename_test.sh installed 2>&1 | grep -E '^FAIL|RENAME|Traceback'"
chroot /srv/noble bash -c "cd /tmp/fdltests; DISPLAY=:${XD:-99} UI_TIMEOUT=1200 /tmp/wl.sh sh theme_run.sh run_installed.sh 2>&1 | grep -E '^-- |^FAIL|UI all|UI FAILED|checks|Traceback'"
echo "== release done"
