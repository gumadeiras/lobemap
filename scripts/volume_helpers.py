from __future__ import annotations

import numpy as np


class LabelVisibilityFilter:
    def __init__(self, label_ids: np.ndarray | list[int] | set[int]) -> None:
        self.label_ids = {int(label_id) for label_id in label_ids if int(label_id) != 0}
        self.max_label_id = max(self.label_ids, default=0)
        self._lut = np.zeros(self.max_label_id + 1, dtype=np.uint16)
        self._buffers: dict[tuple[tuple[int, ...], str], np.ndarray] = {}

    def _buffer_for(self, labels: np.ndarray) -> np.ndarray:
        key = (tuple(labels.shape), labels.dtype.str)
        buffer = self._buffers.get(key)
        if buffer is None:
            buffer = np.zeros(labels.shape, dtype=np.uint16)
            self._buffers[key] = buffer
        return buffer

    def apply(
        self,
        labels: np.ndarray,
        visible_ids: set[int],
        *,
        always_visible_ids: set[int] | None = None,
    ) -> np.ndarray:
        active_ids = {int(label_id) for label_id in visible_ids}
        if always_visible_ids:
            active_ids.update(int(label_id) for label_id in always_visible_ids)
        active_ids.intersection_update(self.label_ids)

        if active_ids == self.label_ids:
            return labels

        buffer = self._buffer_for(labels)
        if not active_ids:
            buffer.fill(0)
            return buffer

        self._lut.fill(0)
        indices = np.fromiter(active_ids, dtype=np.uint16)
        self._lut[indices] = indices
        np.take(self._lut, labels, out=buffer)
        return buffer


def label_slice_centroids(
    labels: np.ndarray,
    ids: np.ndarray,
    hemisphere_axis: int | None = None,
) -> tuple[np.ndarray, np.ndarray]:
    valid_ids = {int(i) for i in ids if i != 0}
    centroids: list[tuple[float, float, float]] = []
    centroid_ids: list[int] = []
    for z in range(labels.shape[0]):
        ys, xs = np.nonzero(labels[z])
        if len(ys) == 0:
            continue
        values = labels[z, ys, xs].astype(np.int64)
        max_id = int(values.max())
        count = np.bincount(values, minlength=max_id + 1)
        for label_id in np.nonzero(count)[0]:
            if label_id == 0 or label_id not in valid_ids:
                continue
            label_mask = values == label_id
            if hemisphere_axis == 1:
                midline = (labels.shape[1] - 1) / 2.0
                side_masks = (ys[label_mask] <= midline, ys[label_mask] > midline)
            elif hemisphere_axis == 2:
                midline = (labels.shape[2] - 1) / 2.0
                side_masks = (xs[label_mask] <= midline, xs[label_mask] > midline)
            else:
                side_masks = (np.ones(int(count[label_id]), dtype=bool),)

            label_ys = ys[label_mask]
            label_xs = xs[label_mask]
            for side_mask in side_masks:
                if not np.any(side_mask):
                    continue
                centroids.append(
                    (
                        float(z),
                        float(np.mean(label_ys[side_mask])),
                        float(np.mean(label_xs[side_mask])),
                    )
                )
                centroid_ids.append(int(label_id))

    if not centroids:
        return np.empty((0, 3), dtype=float), np.empty((0,), dtype=np.uint16)
    return np.asarray(centroids, dtype=float), np.asarray(centroid_ids, dtype=np.uint16)


def axis_key(axis_order: tuple[int, int, int], reverse_axis: bool = False) -> str:
    suffix = "_r" if reverse_axis else ""
    return "_".join(str(axis) for axis in axis_order) + suffix


def centroid_cache_to_arrays(
    centroids: Mapping[tuple[tuple[int, int, int], bool], tuple[np.ndarray, np.ndarray]]
) -> dict[str, np.ndarray]:
    arrays: dict[str, np.ndarray] = {}
    for (axis_order, reverse_axis), (points, ids) in centroids.items():
        key = axis_key(axis_order, reverse_axis)
        arrays[f"centroid_points_{key}"] = points
        arrays[f"centroid_ids_{key}"] = ids
    return arrays


def load_centroid_cache(
    data,
    axis_orders: list[tuple[int, int, int]],
    *,
    reverse_axes: set[tuple[int, int, int]] | None = None,
) -> dict[tuple[tuple[int, int, int], bool], tuple[np.ndarray, np.ndarray]]:
    reverse_axes = reverse_axes or set()
    centroids: dict[tuple[tuple[int, int, int], bool], tuple[np.ndarray, np.ndarray]] = {}
    for axis_order in axis_orders:
        for reverse_axis in (False, True):
            if reverse_axis and axis_order not in reverse_axes:
                continue
            key = axis_key(axis_order, reverse_axis)
            points_key = f"centroid_points_{key}"
            ids_key = f"centroid_ids_{key}"
            if points_key in data.files and ids_key in data.files:
                centroids[(axis_order, reverse_axis)] = (
                    data[points_key].astype(float, copy=False),
                    data[ids_key].astype(np.uint16, copy=False),
                )
    return centroids
