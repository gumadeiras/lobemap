"""Reading an image of your own: its channels as (x, y, z), and only the voxel
size its file states.

Files are written here, in each format read, with values that name their
own voxel, so a channel, plane or axis read in the wrong place shows.
"""

from __future__ import annotations

import numpy as np
import pytest
import tifffile

from lobemap.core.user_image import UnreadableImage, read_image


def _named(shape) -> np.ndarray:
    """A volume whose every voxel's value is unique, in (z, y, x) order."""
    return np.arange(int(np.prod(shape)), dtype=np.uint16).reshape(shape)


def test_an_imagej_hyperstack_gives_each_channel_in_x_y_z_with_its_voxel(tmp_path):
    zcyx = _named((5, 2, 8, 9))
    path = tmp_path / "stack.tif"
    tifffile.imwrite(path, zcyx, imagej=True, resolution=(1 / 0.4, 1 / 0.4),
                     metadata={"spacing": 1.5, "unit": "um", "axes": "ZCYX"})
    image = read_image(path)
    assert len(image.channels) == 2
    for c, channel in enumerate(image.channels):
        assert channel.shape == (9, 8, 5)
        assert np.array_equal(channel, zcyx[:, c].transpose(2, 1, 0))
    assert image.voxel_um == pytest.approx((0.4, 0.4, 1.5))


def test_an_ome_tiff_gives_its_physical_sizes(tmp_path):
    path = tmp_path / "stack.ome.tif"
    tifffile.imwrite(path, _named((4, 6, 7)), ome=True, metadata={
        "axes": "ZYX", "PhysicalSizeX": 0.3, "PhysicalSizeY": 0.35, "PhysicalSizeZ": 2.0,
        "PhysicalSizeZUnit": "nm"})
    image = read_image(path)
    assert image.shape == (7, 6, 4)
    assert image.voxel_um == pytest.approx((0.3, 0.35, 0.002))


def test_a_resolution_in_inches_is_no_size_and_one_in_centimeters_is(tmp_path):
    inch, cm = tmp_path / "inch.tif", tmp_path / "cm.tif"
    tifffile.imwrite(inch, _named((3, 4, 5)), photometric="minisblack",
                     resolution=(72.0, 72.0), resolutionunit=2)
    tifffile.imwrite(cm, _named((3, 4, 5)), photometric="minisblack",
                     resolution=(1e4 / 0.5, 1e4 / 0.25), resolutionunit=3)
    assert read_image(inch).voxel_um == (None, None, None)
    assert read_image(cm).voxel_um == pytest.approx((0.5, 0.25, None))


def test_a_recording_over_time_is_its_mean_image(tmp_path):
    tzyx = np.stack([np.full((2, 3, 4), t, np.uint16) for t in range(5)])
    path = tmp_path / "recording.tif"
    tifffile.imwrite(path, tzyx, imagej=True, metadata={"axes": "TZYX"})
    image = read_image(path)
    assert image.shape == (4, 3, 2)
    assert np.allclose(image.channels[0], 2.0)
    assert any("5 time points" in note for note in image.notes)


def _scanimage3(path, data, planes, frames, channels, step) -> None:
    """Pages as ScanImage 3 saves them: per plane, per frame, each channel."""
    header = (f"state.acq.numberOfZSlices={planes}\r"
              f"state.acq.numberOfChannelsSave={channels}\r"
              f"state.acq.zStepSize={step}\rstate.acq.zoomFactor=3\r")
    pages = data.reshape(-1, *data.shape[-2:])
    with tifffile.TiffWriter(path) as tif:
        for page in pages:
            tif.write(page, description=header, metadata=None, contiguous=False)


def test_a_scanimage_3_stack_splits_its_channels_and_averages_its_frames(tmp_path):
    planes, frames, channels = 3, 2, 2
    data = np.zeros((planes, frames, channels, 4, 5), np.uint16)
    for z in range(planes):
        for f in range(frames):
            for c in range(channels):
                data[z, f, c] = 100 * c + 10 * z + 2 * f
    path = tmp_path / "zStack001.tif"
    _scanimage3(path, data, planes, frames, channels, -2)
    image = read_image(path)
    assert len(image.channels) == 2
    for c, channel in enumerate(image.channels):
        assert channel.shape == (5, 4, 3)
        # Frames 0 and 2 averaged: 1 over the plane's own value.
        for z in range(planes):
            assert np.allclose(channel[:, :, z], 100 * c + 10 * z + 1)
    # Only z: ScanImage's pixel size depends on the microscope.
    assert image.voxel_um == (None, None, 2.0)


def test_a_scanimage_3_recording_of_one_plane_is_its_mean(tmp_path):
    data = np.arange(6, dtype=np.uint16)[:, None, None, None, None] * np.ones((6, 1, 1, 3, 4),
                                                                              np.uint16)
    path = tmp_path / "recording.tif"
    _scanimage3(path, data.reshape(1, 6, 1, 3, 4), 1, 6, 1, 0)
    image = read_image(path)
    assert image.shape == (4, 3, 1)
    assert np.allclose(image.channels[0], 2.5)
    assert image.voxel_um == (None, None, None)


def test_an_nrrd_gives_its_space_directions_in_its_units(tmp_path):
    xyz = _named((6, 5, 4)).astype("<f4")
    path = tmp_path / "brain.nrrd"
    header = ("NRRD0004\ntype: float\ndimension: 3\nspace: right-anterior-superior\n"
              "sizes: 6 5 4\nspace directions: (0.5,0,0) (0,0.6,0) (0,0,2)\n"
              'space units: "microns" "microns" "microns"\nendian: little\n'
              "encoding: raw\n\n")
    path.write_bytes(header.encode() + xyz.ravel(order="F").tobytes())
    image = read_image(path)
    assert np.array_equal(image.channels[0], xyz)
    assert image.voxel_um == pytest.approx((0.5, 0.6, 2.0))


@pytest.mark.parametrize("name, words", [
    ("stack.png", "TIFF and NRRD"),
    ("missing.tif", "not a file"),
])
def test_what_cannot_be_read_says_why(tmp_path, name, words):
    with pytest.raises(UnreadableImage, match=words):
        read_image(tmp_path / name)
