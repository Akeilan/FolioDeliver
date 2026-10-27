"""Render every slide of the given decks to PNGs (engine check): render_all.py out_dir deck..."""
import os, sys, time
import deliver_core as d
out = sys.argv[1]
os.makedirs(out, exist_ok=True)
for f in sys.argv[2:]:
    p = d.Presentation.open(f)
    stem = os.path.splitext(os.path.basename(f))[0]
    t = time.time()
    for i in range(p.slide_count()):
        p.export_png(i, os.path.join(out, "%s_%d.png" % (stem, i)), 640)
    print(stem, p.slide_count(), "slides", round(time.time() - t, 3), "s")
