from PIL import Image as PILImage
from textual_image._geometry import CellSize

from magi.tui import screens


def test_logo_fit():
    source = PILImage.open(screens.LOGO)
    for cell in (CellSize(8, 17), CellSize(10, 20), CellSize(9, 21)):
        image, columns = screens.logo_image(2, cell)
        box = columns * cell.width / (2 * cell.height)
        assert abs(image.width / image.height - box) < 0.02, \
            f"logo fills a whole {columns}x2 box of {cell.width}x{cell.height} cells without stretching"
        assert image.height == source.height, f"logo fills a whole {columns}x2 box of {cell.width}x{cell.height} cells without stretching"
        assert image.width >= source.width, f"logo fills a whole {columns}x2 box of {cell.width}x{cell.height} cells without stretching"
