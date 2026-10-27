"""Side-by-side sheet: ours (left) vs reference (right). compare.py ours_dir ref_dir out.png deck[:slides]..."""
import sys, os, glob
from PIL import Image, ImageDraw
ours, ref, out = sys.argv[1:4]
rows = []
for spec in sys.argv[4:]:
    deck, _, sl = spec.partition(":")
    n = len(glob.glob(os.path.join(ours, deck + "_*.png")))
    idx = [int(x) for x in sl.split(",")] if sl else range(n)
    refs = sorted(glob.glob(os.path.join(ref, deck + "-*.png")))
    for i in idx:
        a = Image.open(os.path.join(ours, "%s_%d.png" % (deck, i))).convert("RGB")
        b = Image.open(refs[i]).convert("RGB").resize(a.size) if i < len(refs) else Image.new("RGB", a.size, "gray")
        rows.append((a, b))
W, H = rows[0][0].size
sheet = Image.new("RGB", (W * 2 + 12, (H + 8) * len(rows)), (90, 90, 90))
for k, (a, b) in enumerate(rows):
    sheet.paste(a, (0, k * (H + 8)))
    sheet.paste(b, (W + 12, k * (H + 8)))
sheet.save(out)
