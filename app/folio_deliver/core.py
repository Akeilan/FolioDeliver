"""The presentation engine (deliver_core, Rust), found next to the app when installed or in the
source tree's build folder when run from there."""
import os
import sys

_HERE = os.path.dirname(os.path.abspath(__file__))
for p in (os.path.join(_HERE, ".."),                                  # /usr/lib/folio-deliver
          os.path.join(_HERE, "..", "..", "engine", "out"),
          os.path.join(_HERE, "..", "..", "engine", "target", "release")):
    p = os.path.abspath(p)
    if os.path.exists(os.path.join(p, "deliver_core.so")) and p not in sys.path:
        sys.path.insert(0, p)

import deliver_core  # noqa: E402

Presentation = deliver_core.Presentation

EMU_PT = 12700.0


def surface_from(w, h, stride, data):
    """An engine image (ARGB32 bytes) as a cairo surface."""
    import cairo
    buf = bytearray(data)
    return cairo.ImageSurface.create_for_data(buf, cairo.FORMAT_ARGB32, w, h, stride)
