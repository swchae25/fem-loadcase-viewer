"""Render load cases as images: shaded shell mesh, force arrows and supports.

Pure NumPy + Pillow, so it runs anywhere (CI, servers, laptops without a GPU).
"""
from __future__ import annotations

from pathlib import Path

import numpy as np
from PIL import Image, ImageDraw, ImageFont

from .model import Model, Subcase

FORCE_COLOR = (214, 40, 40)
MOMENT_COLOR = (150, 60, 200)
SUPPORT_COLOR = (20, 110, 220)
RIGID_COLOR = (238, 190, 120)


def _font(size: int):
    for name in ("DejaVuSans.ttf", "LiberationSans-Regular.ttf", "arial.ttf"):
        try:
            return ImageFont.truetype(name, size)
        except OSError:
            continue
    return ImageFont.load_default()


def _rotation(yaw_deg: float, pitch_deg: float, up: str) -> np.ndarray:
    """World -> camera rotation. Camera looks along -Z with +Y up on screen."""
    to_y_up = np.eye(3) if up == "Y" else np.array([[1, 0, 0], [0, 0, 1], [0, -1, 0]], float)
    y, p = np.deg2rad(yaw_deg), np.deg2rad(pitch_deg)
    cy, sy, cp, sp = np.cos(y), np.sin(y), np.cos(p), np.sin(p)
    cam = np.array([[cy, 0, sy], [sp * sy, cp, -sp * cy], [-cp * sy, sp, cp * cy]])
    return cam @ to_y_up


class Camera:
    def __init__(self, model: Model, size=(1200, 820), yaw=-35, pitch=20, up="Z", margin=0.1,
                 extra_points: np.ndarray | None = None):
        self.size = size
        self.R = _rotation(yaw, pitch, up)
        ids = sorted(model.nodes)
        self.index = {n: i for i, n in enumerate(ids)}
        pts = np.array([model.nodes[n] for n in ids])
        self.center = (pts.min(0) + pts.max(0)) / 2
        self.extent = float(np.ptp(pts, axis=0).max())
        v = (pts - self.center) @ self.R.T
        # Fit the view to the mesh plus any extra points (e.g. arrow tails) so nothing is clipped.
        fit = v if extra_points is None or not len(extra_points) else np.vstack([v, (extra_points - self.center) @ self.R.T])
        span = np.maximum(np.ptp(fit[:, :2], axis=0), 1e-9)
        w, h = size
        self.scale = min(w * (1 - 2 * margin) / span[0], h * (1 - 2 * margin) / span[1])
        self.offset = np.array([w / 2, h / 2 + 20]) - (fit[:, :2].min(0) + fit[:, :2].max(0)) / 2 * [self.scale, -self.scale]
        self.view = v

    def project(self, xyz: np.ndarray) -> np.ndarray:
        v = (np.atleast_2d(xyz) - self.center) @ self.R.T
        return v[:, :2] * [self.scale, -self.scale] + self.offset


def _base_image(model: Model, cam: Camera) -> Image.Image:
    img = Image.new("RGB", cam.size, "white")
    draw = ImageDraw.Draw(img)
    tris = []
    for shell in model.shells:
        idx = [cam.index[n] for n in shell if n in cam.index]
        if len(idx) == 4:
            tris += [(idx[0], idx[1], idx[2]), (idx[0], idx[2], idx[3])]
        elif len(idx) == 3:
            tris.append(tuple(idx))
    if tris:
        t = np.array(tris)
        q = cam.view[t]
        n = np.cross(q[:, 1] - q[:, 0], q[:, 2] - q[:, 0])
        n /= np.maximum(np.linalg.norm(n, axis=1, keepdims=True), 1e-12)
        shade = 0.55 + 0.45 * np.abs(n @ np.array([0.3, 0.6, 0.74]))
        colors = (np.array([175, 186, 196]) * shade[:, None]).astype(int)
        xy = cam.view[:, :2] * [cam.scale, -cam.scale] + cam.offset
        for i in np.argsort(q[:, :, 2].mean(1)):
            draw.polygon([tuple(xy[k]) for k in t[i]], fill=tuple(colors[i]))
    for a, b in model.rods + model.rigid:
        if a in model.nodes and b in model.nodes:
            p = cam.project(np.array([model.nodes[a], model.nodes[b]]))
            draw.line([tuple(p[0]), tuple(p[1])], fill=RIGID_COLOR, width=1)
    return img


def model_extent(model: Model) -> float:
    pts = np.array(list(model.nodes.values()))
    return float(np.ptp(pts, axis=0).max())


def arrow_segments(model: Model, case: Subcase, arrow_fraction: float = 0.28):
    """(load, tail, head) in model coordinates; arrows end at the loaded node and are
    scaled relative to the largest load in the case."""
    loads = [l for l in case.loads if l.node in model.nodes and np.linalg.norm(l.vector) > 0]
    biggest = max((np.linalg.norm(l.vector) for l in loads), default=1.0)
    extent = model_extent(model)
    out = []
    for load in loads:
        head = model.nodes[load.node]
        length = arrow_fraction * extent * np.linalg.norm(load.vector) / biggest
        out.append((load, head - length * load.vector / np.linalg.norm(load.vector), head))
    return out


def _arrow(draw, start, end, color, width=5):
    draw.line([tuple(start), tuple(end)], fill=color, width=width)
    d = end - start
    length = np.linalg.norm(d)
    if length < 1e-6:
        return
    d /= length
    side = np.array([-d[1], d[0]])
    head = min(22.0, 0.35 * length)
    tip = [tuple(end), tuple(end - head * d + 0.5 * head * side), tuple(end - head * d - 0.5 * head * side)]
    draw.polygon(tip, fill=color)


def render_case(model: Model, case: Subcase, cam: Camera, base: Image.Image | None = None,
                arrow_fraction: float = 0.28, units: str = "N") -> Image.Image:
    img = (base or _base_image(model, cam)).copy()
    draw = ImageDraw.Draw(img)
    loads = [l for l in case.loads if l.node in model.nodes]
    for c in case.constraints:
        if c.node in model.nodes:
            x, y = cam.project(model.nodes[c.node])[0]
            draw.polygon([(x, y), (x - 11, y + 18), (x + 11, y + 18)], fill=SUPPORT_COLOR)
            draw.text((x + 13, y + 4), c.dofs, fill=SUPPORT_COLOR, font=_font(15))
    for load, tail, head in arrow_segments(model, case, arrow_fraction):
        start, end = cam.project(np.array([tail, head]))
        _arrow(draw, start, end, FORCE_COLOR if load.kind == "FORCE" else MOMENT_COLOR)
    force, _ = model.resultant(case)
    title = f"{case.name}"
    detail = (f"{len(loads)} load(s), {len({c.node for c in case.constraints})} supported node(s) | "
              f"net applied force {np.linalg.norm(force):,.0f} {units}  "
              f"[{force[0]:,.0f}, {force[1]:,.0f}, {force[2]:,.0f}]")
    draw.text((24, 18), title, fill="black", font=_font(30))
    draw.text((24, 58), detail, fill=(70, 70, 70), font=_font(17))
    legend_y = img.height - 34
    for i, (text, color) in enumerate([("applied force", FORCE_COLOR), ("support (fixed DOFs)", SUPPORT_COLOR),
                                       ("rigid link / rod", RIGID_COLOR)]):
        x = 24 + i * 250
        draw.rectangle([x, legend_y + 4, x + 18, legend_y + 18], fill=color)
        draw.text((x + 26, legend_y + 1), text, fill=(60, 60, 60), font=_font(16))
    return img


def render_all(model: Model, out_dir: str | Path, yaw=-35, pitch=20, up="Z", units="N",
               size=(1200, 820)) -> list[Path]:
    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    tails = [tail for case in model.subcases for _, tail, _ in arrow_segments(model, case)]
    cam = Camera(model, size=size, yaw=yaw, pitch=pitch, up=up, extra_points=np.array(tails) if tails else None)
    base = _base_image(model, cam)
    paths, images = [], []
    for case in model.subcases:
        img = render_case(model, case, cam, base, units=units)
        safe = "".join(ch if ch.isalnum() or ch in "-_" else "_" for ch in case.name)
        path = out_dir / f"subcase_{case.id:02d}_{safe}.png"
        img.save(path)
        paths.append(path)
        images.append(img)
    if images:
        cols = 2 if len(images) > 1 else 1
        rows = -(-len(images) // cols)
        tw, th = size[0] // 2, size[1] // 2
        sheet = Image.new("RGB", (cols * tw, rows * th), "white")
        for i, img in enumerate(images):
            sheet.paste(img.resize((tw, th), Image.LANCZOS), ((i % cols) * tw, (i // cols) * th))
        atlas = out_dir / "load_case_atlas.png"
        sheet.save(atlas)
        paths.append(atlas)
    return paths
