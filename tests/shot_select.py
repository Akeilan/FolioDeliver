# for shot_app.py: select an object so the contextual tab shows, and put the font in the boxes
win.go_slide(2)
win.canvas._surface()
ids = [s["id"] for s in win.canvas.shapes if s["ph"] is None]
win.canvas.select(ids[:1])
