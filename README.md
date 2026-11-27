# Folio Show

A presentation program with a ribbon, for Zorin OS and Ubuntu. Part of Folio Studio. It was
called Folio Deliver until 0.9; the old name still installs this one.

`.pptx` is its own format, read and written by its own engine, and kept lossless: anything Show
doesn't understand is saved back untouched. It also opens `.ppt`, `.odp` and `.pps`, and exports
PDF, pictures and video.

## What it does

- **The PowerPoint ribbon**, with KeyTips, ScreenTips and a File view; its own light and dark
  themes whatever the desktop is set to.
- **Slides**: layouts, the Slide Master, Notes and Handout masters, sections, themes and variants,
  Designer-free design tools, Reuse Slides, Compare.
- **Objects**: shapes, text boxes, tables, charts, SmartArt, pictures with background removal,
  icons, 3-D models (turned with a handle on the slide), ink, equations, embedded documents,
  Cameo, and Cork diagrams that stay editable.
- **Movement**: animations with triggers and motion paths, Morph, Zoom, transitions.
- **Presenting**: Slide Show, Presenter View, custom shows, rehearsed timings, recorded
  narration, a pointer and ink during the show.
- **Media**: video and audio with trimming, poster frames, playback options; Compress Media;
  Record Sound; export the whole show to video.
- **Sharing**: PDF, pictures, embedded fonts (only the characters used), password protection,
  and copy and paste with the rest of Folio Studio.
- **Package into a folder** (P4-02): Export > Package into a Folder puts the presentation and the
  files it links to in one folder, with the links pointing at the copies, so the lot can be carried
  on a stick and opened on another computer.

## What's new in 0.13

- Runs on Windows as part of Folio Studio's MSI: mail through the default mail program, screen recording through ffmpeg's desktop capture, light or dark as Windows is set.

## What's new in 0.12

- AutoRecover: unsaved work is copied every 10 minutes (Options > Save) and offered back after a crash.
- Text pasted from other programs no longer makes files PowerPoint calls damaged.
- A deck started from a .potx template, or a .pptm saved as .pptx, is saved as a real .pptx; the
  macros are left out, and Show says so.
- Slides cut or copied in one presentation paste into another.
- Save As .ppsx and .potx keep the password; a save that fails says why; saving over a file another
  program changed asks first.
- A damaged slide is named when the file opens, and the saved file is whole again.
- Shapes drag from anywhere inside them. Japanese, Chinese and Korean input methods work on slides.
- A picture inserted twice is stored once; long saves show "Saving…".
- Plain messages for damaged files; opening a .ppt without LibreOffice Impress names the package.
- Ctrl+Z and Ctrl+Y work in the Notes pane.

## Layout

| Folder | What's in it |
| --- | --- |
| `app/folio_deliver` | the interface, in Python with GTK 3 |
| `engine` | the presentation engine, in Rust (about 10,000 lines): the model, layout, rendering and the .pptx reader and writer |
| `share` | templates, themes, icons, fonts |
| `tests` | the test suites (see below) |
| `tools` | build and release scripts |

## Building and testing

```sh
cd engine && cargo build --release      # the engine
sh build-deb.sh out/                    # the package
sh tests/run_ui.sh ui_basic.py          # one UI test, on an X display
sh tests/theme_run.sh                   # desktop themes (X2-01)
python3 tests/test_engine.py            # the engine's own tests
XD=99 bash ~/release_show.sh            # everything, on the three test machines
```

Needs python3-gi, GTK 3, Cairo, GStreamer (base, good, libav) and Poppler.
