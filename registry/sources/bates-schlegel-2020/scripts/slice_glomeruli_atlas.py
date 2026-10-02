import argparse
import json
from collections import defaultdict
from pathlib import Path

import matplotlib.pyplot as plt
import numpy as np
from matplotlib.patches import Polygon


PROJECT_DIR = Path(__file__).resolve().parents[1]
DEFAULT_HTML = PROJECT_DIR / "data/source/glomeruli_atlas_interactive.html"
DEFAULT_OUT = PROJECT_DIR / "slices"
AXIS_INDEX = {"x": 0, "y": 1, "z": 2}
VIEWS = {
    "anterior-posterior": {
        "cut_axis": "z",
        "project_axes": ("x", "y"),
        "invert_vertical": True,
    },
    "dorsal-ventral": {
        "cut_axis": "y",
        "project_axes": ("x", "z"),
        "invert_vertical": True,
    },
    "lateral-medial": {
        "cut_axis": "x",
        "project_axes": ("y", "z"),
        "invert_vertical": True,
    },
}


plt.rcParams["pdf.fonttype"] = 42
plt.rcParams["ps.fonttype"] = 42


def extract_plotly_data(html_path):
    text = Path(html_path).read_text()
    start = text.index("Plotly.newPlot(")
    data_start = text.index("[", start)

    depth = 0
    in_string = False
    escaped = False
    for pos in range(data_start, len(text)):
        ch = text[pos]
        if in_string:
            if escaped:
                escaped = False
            elif ch == "\\":
                escaped = True
            elif ch == '"':
                in_string = False
            continue
        if ch == '"':
            in_string = True
        elif ch == "[":
            depth += 1
        elif ch == "]":
            depth -= 1
            if depth == 0:
                return json.loads(text[data_start : pos + 1])

    raise ValueError(f"Could not find Plotly data array in {html_path}")


def load_meshes(html_path, include_neuropil=False):
    data = extract_plotly_data(html_path)
    meshes = []
    for trace in data:
        if trace.get("type") != "mesh3d":
            continue
        if trace.get("name") == "neuropil" and not include_neuropil:
            continue
        meshes.append(
            {
                "name": trace["name"],
                "x": np.asarray(trace["x"], dtype=float),
                "y": np.asarray(trace["y"], dtype=float),
                "z": np.asarray(trace["z"], dtype=float),
                "i": np.asarray(trace["i"], dtype=int),
                "j": np.asarray(trace["j"], dtype=int),
                "k": np.asarray(trace["k"], dtype=int),
            }
        )
    return meshes


def mesh_center(meshes):
    center = []
    for axis in ("x", "y", "z"):
        vals = np.concatenate([m[axis] for m in meshes])
        center.append(0.5 * (np.min(vals) + np.max(vals)))
    return np.asarray(
        center,
        dtype=float,
    )


def rotation_matrix(axis, degrees):
    theta = np.deg2rad(degrees)
    c = np.cos(theta)
    s = np.sin(theta)
    if axis == "x":
        return np.asarray([[1, 0, 0], [0, c, -s], [0, s, c]], dtype=float)
    if axis == "y":
        return np.asarray([[c, 0, s], [0, 1, 0], [-s, 0, c]], dtype=float)
    if axis == "z":
        return np.asarray([[c, -s, 0], [s, c, 0], [0, 0, 1]], dtype=float)
    raise ValueError(f"Unknown rotation axis: {axis}")


def rotate_meshes(meshes, axis, degrees):
    if degrees == 0:
        return meshes

    center = mesh_center(meshes)
    rot = rotation_matrix(axis, degrees)
    rotated = []
    for mesh in meshes:
        pts = np.column_stack([mesh["x"], mesh["y"], mesh["z"]])
        pts = (pts - center) @ rot.T + center
        rotated.append(
            {
                **mesh,
                "x": pts[:, 0],
                "y": pts[:, 1],
                "z": pts[:, 2],
            }
        )
    return rotated


def plane_levels(meshes, axis, count, margin=0.02):
    vals = np.concatenate([m[axis] for m in meshes])
    lo = float(np.nanmin(vals))
    hi = float(np.nanmax(vals))
    pad = (hi - lo) * margin
    return np.linspace(lo + pad, hi - pad, int(count))


def edge_intersection(p0, p1, v0, v1, eps):
    if abs(v0) <= eps and abs(v1) <= eps:
        return None
    if abs(v0) <= eps:
        return p0
    if abs(v1) <= eps:
        return p1
    if (v0 < 0 and v1 > 0) or (v0 > 0 and v1 < 0):
        t = v0 / (v0 - v1)
        return p0 + t * (p1 - p0)
    return None


def triangle_segments(mesh, level, cut_axis, project_axes, eps=1e-6):
    pts = np.column_stack([mesh["x"], mesh["y"], mesh["z"]])
    cut_idx = AXIS_INDEX[cut_axis]
    project_idx = [AXIS_INDEX[a] for a in project_axes]
    segs = []
    seen = set()

    for a, b, c in zip(mesh["i"], mesh["j"], mesh["k"]):
        tri = pts[[a, b, c]]
        vals = tri[:, cut_idx] - level
        if np.all(vals > eps) or np.all(vals < -eps):
            continue

        intersections = []
        for u, v in ((0, 1), (1, 2), (2, 0)):
            p = edge_intersection(tri[u], tri[v], vals[u], vals[v], eps)
            if p is not None:
                intersections.append(p[project_idx])

        if len(intersections) < 2:
            continue

        uniq = []
        keys = set()
        for p in intersections:
            key = tuple(np.round(p, 6))
            if key not in keys:
                keys.add(key)
                uniq.append(p)

        if len(uniq) != 2:
            continue

        akey = tuple(np.round(uniq[0], 6))
        bkey = tuple(np.round(uniq[1], 6))
        skey = tuple(sorted((akey, bkey)))
        if akey == bkey or skey in seen:
            continue
        seen.add(skey)
        segs.append((np.asarray(uniq[0]), np.asarray(uniq[1])))

    return segs


def segments_to_loops(segments, quant=1e-3):
    def key(p):
        return tuple(np.round(np.asarray(p) / quant).astype(int))

    points = {}
    edges = set()
    adj = defaultdict(set)
    for a, b in segments:
        ka = key(a)
        kb = key(b)
        if ka == kb:
            continue
        points.setdefault(ka, np.asarray(a, dtype=float))
        points.setdefault(kb, np.asarray(b, dtype=float))
        edge = tuple(sorted((ka, kb)))
        if edge in edges:
            continue
        edges.add(edge)
        adj[ka].add(kb)
        adj[kb].add(ka)

    loops = []
    used = set()
    for edge in list(edges):
        if edge in used:
            continue

        start, nxt = edge
        loop = [start]
        prev = start
        cur = nxt
        used.add(edge)

        while True:
            loop.append(cur)
            candidates = [n for n in adj[cur] if n != prev]
            if not candidates:
                break
            if start in candidates:
                used.add(tuple(sorted((cur, start))))
                loop.append(start)
                break

            unused = [n for n in candidates if tuple(sorted((cur, n))) not in used]
            if not unused:
                break
            nxt = unused[0]
            used.add(tuple(sorted((cur, nxt))))
            prev, cur = cur, nxt

        if len(loop) >= 4 and loop[0] == loop[-1]:
            arr = np.vstack([points[k] for k in loop[:-1]])
            if polygon_area(arr) > 1:
                loops.append(arr)

    return loops


def polygon_area(points):
    x = points[:, 0]
    y = points[:, 1]
    return abs(0.5 * np.sum(x * np.roll(y, -1) - np.roll(x, -1) * y))


def slice_meshes(meshes, level, cut_axis, project_axes):
    out = []
    for mesh in meshes:
        segments = triangle_segments(mesh, level, cut_axis, project_axes)
        loops = segments_to_loops(segments)
        if loops:
            out.append((mesh["name"], loops))
    return out


def mesh_bounds(meshes, project_axes):
    x = np.concatenate([m[project_axes[0]] for m in meshes])
    y = np.concatenate([m[project_axes[1]] for m in meshes])
    return float(np.min(x)), float(np.max(x)), float(np.min(y)), float(np.max(y))


def draw_plane(ax, plane, bounds, label=False, invert_vertical=False):
    xmin, xmax, ymin, ymax = bounds
    dx = xmax - xmin
    dy = ymax - ymin

    for name, loops in plane:
        for loop in loops:
            patch = Polygon(
                loop,
                closed=True,
                facecolor="#bdbdbd",
                edgecolor="#ffffff",
                linewidth=0.35,
                joinstyle="round",
                zorder=1,
            )
            ax.add_patch(patch)
        if label:
            all_pts = np.vstack(loops)
            ax.text(
                float(np.mean(all_pts[:, 0])),
                float(np.mean(all_pts[:, 1])),
                name,
                ha="center",
                va="center",
                fontsize=4,
                color="#303030",
                zorder=20,
            )

    ax.set_xlim(xmin - 0.03 * dx, xmax + 0.03 * dx)
    ax.set_ylim(ymin - 0.03 * dy, ymax + 0.03 * dy)
    ax.set_aspect("equal")
    if invert_vertical:
        ax.invert_yaxis()
    ax.axis("off")


def save_plane(path, plane, bounds, label=False, invert_vertical=False):
    fig, ax = plt.subplots(figsize=(1.8, 1.8))
    fig.patch.set_facecolor("white")
    draw_plane(ax, plane, bounds, label=label, invert_vertical=invert_vertical)
    fig.savefig(path, bbox_inches="tight", pad_inches=0.01)
    plt.close(fig)


def save_contact_sheet(path, planes, levels, bounds, label=False, invert_vertical=False):
    n = len(planes)
    cols = int(np.ceil(np.sqrt(n)))
    rows = int(np.ceil(n / cols))
    fig, axes = plt.subplots(rows, cols, figsize=(cols * 1.45, rows * 1.45))
    axes = np.atleast_1d(axes).ravel()
    fig.patch.set_facecolor("white")

    for ax, plane, z0 in zip(axes, planes, levels):
        draw_plane(ax, plane, bounds, label=label, invert_vertical=invert_vertical)
        ax.set_title(f"{z0:.0f}", fontsize=5, pad=1)

    for ax in axes[n:]:
        ax.axis("off")

    fig.savefig(path, bbox_inches="tight", pad_inches=0.02)
    plt.close(fig)


def write_view(out_dir, meshes, view_name, view_config, count):
    view_dir = Path(out_dir) / view_name
    plain_dir = view_dir / "plain"
    labeled_dir = view_dir / "labeled"
    plain_dir.mkdir(parents=True, exist_ok=True)
    labeled_dir.mkdir(parents=True, exist_ok=True)

    cut_axis = view_config["cut_axis"]
    project_axes = view_config["project_axes"]
    invert_vertical = view_config["invert_vertical"]
    levels = plane_levels(meshes, cut_axis, count)
    bounds = mesh_bounds(meshes, project_axes)
    planes = [
        slice_meshes(meshes, level, cut_axis=cut_axis, project_axes=project_axes)
        for level in levels
    ]

    for idx, (plane, level) in enumerate(zip(planes, levels), start=1):
        stem = f"plane_{idx:02d}_{cut_axis}{level:.0f}"
        save_plane(
            plain_dir / f"{stem}_plain.pdf",
            plane,
            bounds,
            label=False,
            invert_vertical=invert_vertical,
        )
        save_plane(
            labeled_dir / f"{stem}_labeled.pdf",
            plane,
            bounds,
            label=True,
            invert_vertical=invert_vertical,
        )

    save_contact_sheet(
        plain_dir / "contact_sheet_plain.pdf",
        planes,
        levels,
        bounds,
        label=False,
        invert_vertical=invert_vertical,
    )
    save_contact_sheet(
        labeled_dir / "contact_sheet_labeled.pdf",
        planes,
        levels,
        bounds,
        label=True,
        invert_vertical=invert_vertical,
    )
    return levels


def main():
    parser = argparse.ArgumentParser(
        description="Slice the Plotly glomerulus atlas mesh into plane maps."
    )
    parser.add_argument("--html", type=Path, default=DEFAULT_HTML, help="Atlas HTML to slice")
    parser.add_argument("--out", type=Path, default=DEFAULT_OUT)
    parser.add_argument("--planes", type=int, default=16)
    parser.add_argument(
        "--rotate-axis",
        choices=sorted(AXIS_INDEX),
        help="Rotate meshes around this 3D axis before slicing",
    )
    parser.add_argument(
        "--rotate-deg",
        type=float,
        default=0,
        help="Degrees to rotate meshes before slicing",
    )
    parser.add_argument(
        "--views",
        nargs="+",
        choices=sorted(VIEWS),
        default=sorted(VIEWS),
        help="View folders to generate",
    )
    parser.add_argument("--include-neuropil", action="store_true")
    args = parser.parse_args()

    out_dir = args.out.expanduser()
    out_dir.mkdir(parents=True, exist_ok=True)

    html_path = args.html.expanduser()
    if not html_path.exists():
        raise FileNotFoundError(f"Atlas HTML not found: {html_path}")
    meshes = load_meshes(html_path, include_neuropil=args.include_neuropil)
    if args.rotate_deg != 0:
        if not args.rotate_axis:
            parser.error("--rotate-axis is required when --rotate-deg is nonzero")
        meshes = rotate_meshes(meshes, args.rotate_axis, args.rotate_deg)
        print(f"rotated meshes {args.rotate_deg:g} deg around {args.rotate_axis}")
    for view_name in args.views:
        levels = write_view(out_dir, meshes, view_name, VIEWS[view_name], args.planes)
        print(
            f"{view_name}: wrote {len(levels)} planes "
            f"({levels[0]:.1f} .. {levels[-1]:.1f})"
        )

    print(f"loaded {len(meshes)} meshes")
    print(f"wrote PDFs to {out_dir}")
    print(f"source HTML: {html_path}")


if __name__ == "__main__":
    main()
