"""3-D models on slides (Insert > 3D Models): glTF 2.0 files read here and drawn here, flat
shaded, in any orientation. The model is kept in the .pptx as PowerPoint keeps it (a .glb part)
with a picture of its current view."""
import base64
import io
import json
import math
import os
import struct

import cairo

COMP = {5120: ("b", 1), 5121: ("B", 1), 5122: ("h", 2), 5123: ("H", 2), 5125: ("I", 4), 5126: ("f", 4)}
NCOMP = {"SCALAR": 1, "VEC2": 2, "VEC3": 3, "VEC4": 4, "MAT4": 16}


def _glb(doc, bin_chunk):
    js = json.dumps(doc, separators=(",", ":")).encode()
    js += b" " * ((4 - len(js) % 4) % 4)
    bn = bin_chunk + b"\0" * ((4 - len(bin_chunk) % 4) % 4)
    total = 12 + 8 + len(js) + (8 + len(bn) if bn else 0)
    out = struct.pack("<4sII", b"glTF", 2, total) + struct.pack("<I4s", len(js), b"JSON") + js
    if bn:
        out += struct.pack("<I4s", len(bn), b"BIN\0") + bn
    return out


def load_file(path):
    """(file bytes, GLB bytes): a .gltf with its buffers and pictures packed into one .glb."""
    data = open(path, "rb").read()
    if data[:4] == b"glTF":
        return data, data
    doc = json.loads(data.decode("utf-8"))
    base = os.path.dirname(path)
    blob = bytearray()
    offsets = []
    for b in doc.get("buffers", []):
        uri = b.get("uri", "")
        if uri.startswith("data:"):
            raw = base64.b64decode(uri.split(",", 1)[1])
        else:
            raw = open(os.path.join(base, uri), "rb").read()
        offsets.append(len(blob))
        blob += raw
        while len(blob) % 4:
            blob += b"\0"
    for v in doc.get("bufferViews", []):
        v["byteOffset"] = v.get("byteOffset", 0) + offsets[v.get("buffer", 0)]
        v["buffer"] = 0
    for img in doc.get("images", []):
        uri = img.pop("uri", None)
        if not uri:
            continue
        raw = base64.b64decode(uri.split(",", 1)[1]) if uri.startswith("data:") else open(os.path.join(base, uri), "rb").read()
        img["bufferView"] = len(doc.setdefault("bufferViews", []))
        img.setdefault("mimeType", "image/png" if raw[:4] == b"\x89PNG" else "image/jpeg")
        doc["bufferViews"].append({"buffer": 0, "byteOffset": len(blob), "byteLength": len(raw)})
        blob += raw
        while len(blob) % 4:
            blob += b"\0"
    doc["buffers"] = [{"byteLength": len(blob)}]
    return data, _glb(doc, bytes(blob))


def _mat_mul(a, b):
    return [[sum(a[i][k] * b[k][j] for k in range(4)) for j in range(4)] for i in range(4)]


def _node_matrix(n):
    if "matrix" in n:
        m = n["matrix"]
        return [[m[c * 4 + r] for c in range(4)] for r in range(4)]
    t = n.get("translation", [0, 0, 0])
    q = n.get("rotation", [0, 0, 0, 1])
    s = n.get("scale", [1, 1, 1])
    x, y, z, w = q
    r = [[1 - 2 * (y * y + z * z), 2 * (x * y - z * w), 2 * (x * z + y * w)],
         [2 * (x * y + z * w), 1 - 2 * (x * x + z * z), 2 * (y * z - x * w)],
         [2 * (x * z - y * w), 2 * (y * z + x * w), 1 - 2 * (x * x + y * y)]]
    return [[r[0][0] * s[0], r[0][1] * s[1], r[0][2] * s[2], t[0]],
            [r[1][0] * s[0], r[1][1] * s[1], r[1][2] * s[2], t[1]],
            [r[2][0] * s[0], r[2][1] * s[1], r[2][2] * s[2], t[2]],
            [0, 0, 0, 1]]


class Mesh:
    """The triangles of a glTF model with their colours."""
    def __init__(self, glb):
        if glb[:4] != b"glTF":
            raise ValueError("not a glTF binary")
        _magic, _ver, total = struct.unpack_from("<4sII", glb, 0)
        off = 12
        self.doc, self.bin = None, b""
        while off < min(total, len(glb)):
            ln, typ = struct.unpack_from("<I4s", glb, off)
            chunk = glb[off + 8:off + 8 + ln]
            if typ == b"JSON":
                self.doc = json.loads(chunk.decode("utf-8"))
            elif typ == b"BIN\0":
                self.bin = chunk
            off += 8 + ln
        if self.doc is None:
            raise ValueError("no glTF description")
        self.tris = []          # ((x, y, z) * 3, (r, g, b))
        scene = self.doc.get("scenes", [{}])[self.doc.get("scene", 0)] if self.doc.get("scenes") else {"nodes": list(range(len(self.doc.get("nodes", []))))}
        ident = [[1, 0, 0, 0], [0, 1, 0, 0], [0, 0, 1, 0], [0, 0, 0, 1]]
        for n in scene.get("nodes", []):
            self._walk(n, ident, 0)
        if not self.tris:
            raise ValueError("the model has no triangles")
        xs = [p[0] for t, _c in self.tris for p in t]
        ys = [p[1] for t, _c in self.tris for p in t]
        zs = [p[2] for t, _c in self.tris for p in t]
        self.center = ((min(xs) + max(xs)) / 2, (min(ys) + max(ys)) / 2, (min(zs) + max(zs)) / 2)
        self.radius = max(1e-6, max(math.dist(self.center, p) for t, _c in self.tris for p in t))

    def _accessor(self, k):
        a = self.doc["accessors"][k]
        fmt, size = COMP[a["componentType"]]
        nc = NCOMP[a["type"]]
        v = self.doc["bufferViews"][a["bufferView"]] if "bufferView" in a else None
        if v is None:
            return [(0.0,) * nc] * a["count"]
        base = v.get("byteOffset", 0) + a.get("byteOffset", 0)
        stride = v.get("byteStride") or size * nc
        out = []
        for i in range(a["count"]):
            out.append(struct.unpack_from("<%d%s" % (nc, fmt), self.bin, base + i * stride))
        return out

    def _color(self, prim):
        m = prim.get("material")
        if m is None:
            return (0.75, 0.75, 0.75)
        mat = self.doc.get("materials", [])[m]
        f = mat.get("pbrMetallicRoughness", {}).get("baseColorFactor", [0.8, 0.8, 0.8, 1])
        return tuple(max(0.0, min(1.0, c ** (1 / 2.2))) for c in f[:3])

    def _walk(self, k, parent, depth):
        if depth > 32:
            return
        n = self.doc["nodes"][k]
        m = _mat_mul(parent, _node_matrix(n))
        if "mesh" in n:
            for prim in self.doc["meshes"][n["mesh"]].get("primitives", []):
                if prim.get("mode", 4) != 4 or "POSITION" not in prim.get("attributes", {}):
                    continue
                pos = self._accessor(prim["attributes"]["POSITION"])
                pos = [(m[0][0] * x + m[0][1] * y + m[0][2] * z + m[0][3], m[1][0] * x + m[1][1] * y + m[1][2] * z + m[1][3],
                        m[2][0] * x + m[2][1] * y + m[2][2] * z + m[2][3]) for x, y, z in pos]
                idx = [i[0] for i in self._accessor(prim["indices"])] if "indices" in prim else list(range(len(pos)))
                col = self._color(prim)
                for j in range(0, len(idx) - 2, 3):
                    self.tris.append(((pos[idx[j]], pos[idx[j + 1]], pos[idx[j + 2]]), col))
        for c in n.get("children", []):
            self._walk(c, m, depth + 1)

    def draw(self, cr, w, h, rot):
        """Draw the model fitted into w x h, turned rot = (x, y, z) degrees."""
        ax, ay, az = (math.radians(v) for v in rot)
        cx, cy, cz = self.center
        k = min(w, h) * 0.45 / self.radius
        ca, sa, cb, sb, cc, sc = math.cos(ax), math.sin(ax), math.cos(ay), math.sin(ay), math.cos(az), math.sin(az)

        def tf(p):
            x, y, z = p[0] - cx, p[1] - cy, p[2] - cz
            x, z = x * cb + z * sb, -x * sb + z * cb          # around y
            y, z = y * ca - z * sa, y * sa + z * ca           # around x
            x, y = x * cc - y * sc, x * sc + y * cc           # around z
            return x, y, z
        light = (-0.4, 0.6, 0.7)
        ln = math.sqrt(sum(v * v for v in light))
        light = tuple(v / ln for v in light)
        drawn = []
        for tri, col in self.tris:
            a, b, c = tf(tri[0]), tf(tri[1]), tf(tri[2])
            ux, uy, uz = b[0] - a[0], b[1] - a[1], b[2] - a[2]
            vx, vy, vz = c[0] - a[0], c[1] - a[1], c[2] - a[2]
            nx, ny, nz = uy * vz - uz * vy, uz * vx - ux * vz, ux * vy - uy * vx
            nl = math.sqrt(nx * nx + ny * ny + nz * nz) or 1.0
            nx, ny, nz = nx / nl, ny / nl, nz / nl
            if nz < 0:
                nx, ny, nz = -nx, -ny, -nz
            shade = 0.35 + 0.65 * max(0.0, nx * light[0] + ny * light[1] + nz * light[2])
            drawn.append(((a[2] + b[2] + c[2]) / 3, a, b, c, tuple(v * shade for v in col)))
        drawn.sort(key=lambda d: d[0])
        cr.save()
        cr.translate(w / 2, h / 2)
        cr.set_line_width(0.6)
        cr.set_line_join(cairo.LINE_JOIN_ROUND)
        for _z, a, b, c, col in drawn:
            cr.move_to(a[0] * k, -a[1] * k)
            cr.line_to(b[0] * k, -b[1] * k)
            cr.line_to(c[0] * k, -c[1] * k)
            cr.close_path()
            cr.set_source_rgb(*col)
            cr.fill_preserve()
            cr.stroke()
        cr.restore()

    def png(self, w, h, rot):
        s = cairo.ImageSurface(cairo.FORMAT_ARGB32, max(1, w), max(1, h))
        self.draw(cairo.Context(s), w, h, rot)
        b = io.BytesIO()
        s.write_to_png(b)
        return b.getvalue()


def cube_glb(color=(0.9, 0.45, 0.1, 1.0)):
    """A small test model: a cube (for tests and as a sample)."""
    v = [(-1, -1, -1), (1, -1, -1), (1, 1, -1), (-1, 1, -1), (-1, -1, 1), (1, -1, 1), (1, 1, 1), (-1, 1, 1)]
    f = [0, 1, 2, 0, 2, 3, 4, 6, 5, 4, 7, 6, 0, 4, 5, 0, 5, 1, 1, 5, 6, 1, 6, 2, 2, 6, 7, 2, 7, 3, 3, 7, 4, 3, 4, 0]
    pos = b"".join(struct.pack("<3f", *p) for p in v)
    idx = b"".join(struct.pack("<H", i) for i in f)
    pad = b"\0" * ((4 - len(idx) % 4) % 4)
    doc = {"asset": {"version": "2.0"}, "scene": 0, "scenes": [{"nodes": [0]}], "nodes": [{"mesh": 0}],
           "meshes": [{"primitives": [{"attributes": {"POSITION": 0}, "indices": 1, "material": 0}]}],
           "materials": [{"pbrMetallicRoughness": {"baseColorFactor": list(color)}}],
           "buffers": [{"byteLength": len(pos) + len(idx) + len(pad)}],
           "bufferViews": [{"buffer": 0, "byteOffset": 0, "byteLength": len(pos)},
                           {"buffer": 0, "byteOffset": len(pos), "byteLength": len(idx)}],
           "accessors": [{"bufferView": 0, "componentType": 5126, "count": 8, "type": "VEC3", "min": [-1, -1, -1], "max": [1, 1, 1]},
                         {"bufferView": 1, "componentType": 5123, "count": len(f), "type": "SCALAR"}]}
    return _glb(doc, pos + idx + pad)
