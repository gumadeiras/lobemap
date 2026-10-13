"""The Your data tab: everything for bringing your own data into a brain.

In the left column, after the View tab and napari's layer settings: images
of your own, placed by hand or by landmarks (`your_images`), and neurons
from FlyWire or SWC files (`your_neurons`). Each brain keeps its own: what
you add is in the brain that is open, and switching back to it shows it
again, as it was.

The tab outlives every scene, as the View dock does. The View dock tells it
when a switch has opened another brain (`SpaceSwitcher.switched`), once the
old scene, and your layers with it, are gone (`SceneSession.teardown`); it
then draws that brain's data in the new scene.
"""

from __future__ import annotations

from qtpy.QtWidgets import QFrame, QScrollArea, QVBoxLayout, QWidget

from .chrome import GRID
from .your_images import ImagesBox
from .your_neurons import NeuronsBox

#: The tab's title.
TITLE = "Your data"


class YourData(QScrollArea):
    """The Your data tab: your images, then your neurons, in one scrolling column."""

    def __init__(self, viewer, parent=None) -> None:
        super().__init__(parent)
        self.viewer = viewer
        self.session = None
        self.images = ImagesBox(viewer)
        self.neurons = NeuronsBox(viewer)
        page = QWidget()
        column = QVBoxLayout(page)
        column.setContentsMargins(0, 0, 0, 0)
        column.setSpacing(2 * GRID)
        column.addWidget(self.images)
        column.addWidget(self.neurons)
        column.addStretch(1)
        self.setWidget(page)
        self.setWidgetResizable(True)
        self.setFrameShape(QFrame.Shape.NoFrame)

    def attach(self, session) -> None:
        """Draw the open brain's data in `session`, the scene just opened."""
        if self.session is not None:
            self.detach()
        self.session = session
        self.images.attach(session)
        self.neurons.attach(session)

    def detach(self) -> None:
        """Forget the scene: it is gone, or going."""
        self.images.detach()
        self.neurons.detach()
        self.session = None

    def open_image(self, path) -> None:
        """Open an image into the open brain (`ImagesBox.open_path`)."""
        self.images.open_path(path)

    def add_neuron(self, text: str) -> None:
        """Add a neuron to the open brain (`NeuronsBox.add_neuron`)."""
        self.neurons.add_neuron(text)


__all__ = ["TITLE", "YourData"]
