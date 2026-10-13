"""Read an image of your own: its channels as (x, y, z) volumes, and what its
file says of its voxel size.

TIFF and NRRD. A TIFF is OME, ImageJ, ScanImage 3 or plain; tifffile names its
axes, and they are read as:

- `Z`, or an unnamed sequence (`I`, `Q`): the stack's planes;
- `C`, or color samples (`S`): channels, each its own volume;
- `T`: time, averaged, so a recording shows as its mean image.

ScanImage 3 names no axes: its pages run through every plane, and within a
plane through each frame saved and each channel saved, as its header says.
A recording of one plane is its frames averaged; a stack of several has its
planes `zStepSize` apart.

A voxel size is taken only from a field that states it, in a unit that is
named: OME's PhysicalSize, ImageJ's spacing and resolution in its unit, a
TIFF resolution in centimeters, ScanImage 3's z step, NRRD's space
directions in its space units. Anything else is unknown, and said so: the
72 dots per inch that many writers leave in a TIFF is no size at all.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from pathlib import Path

import numpy as np

#: The file types read.
SUFFIXES = (".tif", ".tiff", ".nrrd", ".nhdr")

#: Micrometers per unit, by the names files give units.
UNITS_UM = {
    "um": 1.0, "µm": 1.0, "\\u00b5m": 1.0, "micron": 1.0, "microns": 1.0,
    "micrometer": 1.0, "micrometers": 1.0, "micrometre": 1.0, "micrometres": 1.0,
    "nm": 1e-3, "nanometer": 1e-3, "nanometers": 1e-3,
    "mm": 1e3, "millimeter": 1e3, "millimeters": 1e3,
}


@dataclass
class OpenedImage:
    """An image file's channels, and its voxel size where the file states it."""

    path: Path
    #: One (x, y, z) volume per channel, all of one shape.
    channels: list[np.ndarray]
    #: Micrometers per voxel along x, y and z; None where the file says nothing.
    voxel_um: tuple[float | None, float | None, float | None]
    #: What was done to read it, in words: "averaged 600 frames".
    notes: list[str] = field(default_factory=list)

    @property
    def shape(self) -> tuple[int, int, int]:
        return tuple(int(n) for n in self.channels[0].shape)


class UnreadableImage(ValueError):
    """A file that is not an image lobemap can place; the message says why."""


def read_image(path: str | Path) -> OpenedImage:
    """Read `path`; raise UnreadableImage, with the reason, if it cannot be."""
    path = Path(path)
    suffix = path.suffix.lower()
    if suffix not in SUFFIXES:
        raise UnreadableImage(f"{path.name}: lobemap reads TIFF and NRRD images")
    if not path.is_file():
        raise UnreadableImage(f"{path} is not a file")
    try:
        if suffix in (".nrrd", ".nhdr"):
            return _read_nrrd(path)
        return _read_tiff(path)
    except UnreadableImage:
        raise
    except (OSError, ValueError, KeyError, IndexError) as exc:
        raise UnreadableImage(f"{path.name} could not be read: {exc}") from exc


def _count(n: int, thing: str) -> str:
    return f"{n} {thing}" + ("" if n == 1 else "s")


def _um(unit) -> float | None:
    return UNITS_UM.get(str(unit).strip().lower()) if unit is not None else None


# -- TIFF ------------------------------------------------------------------------


def _read_tiff(path: Path) -> OpenedImage:
    import tifffile

    with tifffile.TiffFile(path) as tif:
        description = tif.pages[0].description or ""
        if not description.startswith("state."):
            series = tif.series[0]
            data, axes = series.asarray(), series.axes
            return _assemble(path, data, axes, _tiff_voxel(tif), [])
    # Every page read as it is: tifffile's reading of ScanImage files counts
    # pages from the first page's size, and missed one of a stack whose
    # pages are not all one size.
    with tifffile.TiffFile(path, is_scanimage=False) as tif:
        return _scanimage3(path, tif, description)


def _assemble(path: Path, data: np.ndarray, axes: str, voxel_xyz, notes) -> OpenedImage:
    """Channels of (x, y, z) from an array whose axes tifffile names."""
    axes = axes.upper()
    unknown = set(axes) - set("ZIQCSTYX")
    if unknown:
        raise UnreadableImage(f"{path.name} has axes lobemap cannot place: "
                              f"{''.join(sorted(unknown))} (of {axes})")
    if "Y" not in axes or "X" not in axes:
        raise UnreadableImage(f"{path.name} is not an image: its axes are {axes}")
    if "T" in axes and data.shape[axes.index("T")] > 1:
        notes.append(f"averaged {_count(data.shape[axes.index('T')], 'time point')}")
    if "T" in axes:
        data = data.mean(axis=axes.index("T"), dtype=np.float32)
        axes = axes.replace("T", "")
    planes = [a for a in axes if a in "ZIQ"]
    if len(planes) > 1:
        raise UnreadableImage(f"{path.name} has more than one axis of planes: {axes}")
    if not planes:
        data, axes = data[np.newaxis], "Z" + axes
    else:
        axes = axes.replace(planes[0], "Z")
    colors = [a for a in axes if a in "CS"]
    if not colors:
        data, axes = data[np.newaxis], "C" + axes
    elif len(colors) == 2:
        # Channels of color images: every sample of every channel its own.
        c, s = axes.index("C"), axes.index("S")
        data = np.moveaxis(data, (c, s), (0, 1))
        data = data.reshape((-1,) + data.shape[2:])
        axes = "C" + axes.replace("C", "").replace("S", "")
    else:
        axes = axes.replace(colors[0], "C")
    data = np.transpose(data, [axes.index(a) for a in "CXYZ"])
    channels = [np.ascontiguousarray(channel) for channel in data]
    return OpenedImage(path, channels, voxel_xyz, notes)


def _tiff_voxel(tif) -> tuple[float | None, float | None, float | None]:
    """(x, y, z) micrometers from OME, ImageJ or the resolution tags."""
    if tif.is_ome and tif.ome_metadata:
        return _ome_voxel(tif.ome_metadata)
    x = y = z = None
    ij = tif.imagej_metadata or {}
    unit = _um(ij.get("unit")) if ij else None
    tags = tif.pages[0].tags
    if ij and unit is not None:
        x, y = _per_pixel(tags, "XResolution", unit), _per_pixel(tags, "YResolution", unit)
        if "spacing" in ij:
            z = float(ij["spacing"]) * unit
    elif "ResolutionUnit" in tags and int(tags["ResolutionUnit"].value) == 3:
        # Centimeters; an inch is the default many writers leave unchanged.
        x = _per_pixel(tags, "XResolution", 1e4)
        y = _per_pixel(tags, "YResolution", 1e4)
    return _positive(x), _positive(y), _positive(z)


def _per_pixel(tags, name: str, unit_um: float) -> float | None:
    """Micrometers per pixel from a resolution tag of pixels per unit."""
    if name not in tags:
        return None
    value = tags[name].value
    per_unit = value[0] / value[1] if isinstance(value, tuple) and value[1] else None
    return unit_um / per_unit if per_unit else None


def _positive(value) -> float | None:
    if value is None:
        return None
    value = abs(float(value))
    return value if np.isfinite(value) and value > 0 else None


def _ome_voxel(xml: str) -> tuple[float | None, float | None, float | None]:
    import xml.etree.ElementTree as ET

    root = ET.fromstring(xml)
    pixels = next((e for e in root.iter() if e.tag.endswith("Pixels")), None)
    if pixels is None:
        return (None, None, None)
    out = []
    for axis in "XYZ":
        size = pixels.get(f"PhysicalSize{axis}")
        unit = _um(pixels.get(f"PhysicalSize{axis}Unit", "µm"))
        out.append(_positive(float(size) * unit) if size is not None and unit else None)
    return tuple(out)


#: The ScanImage 3 header fields read.
_SI3 = re.compile(r"state\.acq\.(numberOfChannelsSave|numberOfZSlices|zStepSize)=([^\r\n]*)")


def _scanimage3(path: Path, tif, description: str) -> OpenedImage:
    fields = {k: float(v) for k, v in _SI3.findall(description)}
    channels = int(fields.get("numberOfChannelsSave", 1)) or 1
    planes = int(fields.get("numberOfZSlices", 1)) or 1
    pages = len(tif.pages)
    if pages % (channels * planes):
        raise UnreadableImage(
            f"{path.name}: {pages} pages are not {planes} planes of {channels} "
            "channels, as its ScanImage header says")
    frames = pages // (channels * planes)
    data = tif.asarray(key=range(pages))
    if data.ndim == 2:
        data = data[np.newaxis]
    data = data.reshape(planes, frames, channels, *data.shape[-2:])
    notes = [f"ScanImage 3: {_count(planes, 'plane')}, {_count(channels, 'channel')}"]
    if frames > 1:
        notes.append(f"averaged {_count(frames, 'frame')} per plane")
        data = data.mean(axis=1, dtype=np.float32)
    else:
        data = data[:, 0]
    step = _positive(fields.get("zStepSize")) if planes > 1 else None
    # (z, c, y, x); its x and y size depend on the microscope, not the file.
    return _assemble(path, data, "ZCYX", (None, None, step), notes)


# -- NRRD ------------------------------------------------------------------------


def _read_nrrd(path: Path) -> OpenedImage:
    import nrrd

    data, header = nrrd.read(str(path))         # index order (x, y, z)
    if data.ndim != 3:
        raise UnreadableImage(f"{path.name} is not a 3D volume: its shape is {data.shape}")
    unit = None
    units = header.get("space units")
    if units is not None and len(units) == 3 and len({str(u) for u in units}) == 1:
        unit = _um(units[0])
    sizes: list[float | None] = [None, None, None]
    directions = header.get("space directions")
    if directions is not None and unit is not None:
        directions = np.asarray(directions, float)
        if directions.shape == (3, 3) and np.all(np.isfinite(directions)):
            sizes = [_positive(n * unit) for n in np.linalg.norm(directions, axis=1)]
    elif header.get("spacings") is not None and unit is not None:
        sizes = [_positive(float(s) * unit) for s in header["spacings"]]
    return OpenedImage(path, [np.ascontiguousarray(data)], tuple(sizes), [])


__all__ = ["SUFFIXES", "OpenedImage", "UnreadableImage", "read_image"]
