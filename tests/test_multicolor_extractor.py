"""CLI contracts for recovering multicolor cells without changing source colors."""

import json
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest

from PIL import Image


SCRIPT = Path(__file__).resolve().parents[1] / "tools" / "extract-multicolor.py"


class MulticolorExtractorTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name)

    def run_extractor(self, source, output, *options):
        return subprocess.run(
            [sys.executable, str(SCRIPT), str(source), "--output-dir", str(output), *options],
            capture_output=True,
            text=True,
            timeout=20,
        )

    def assert_success(self, result):
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)

    def assert_pixels(self, path, expected):
        with Image.open(path) as actual:
            self.assertEqual(actual.size, expected.size)
            self.assertEqual(actual.convert("RGBA").tobytes(), expected.convert("RGBA").tobytes())

    def test_auto_grid_preserves_rgb_and_alpha_with_independent_axis_scales(self):
        for mode, cell in (("RGB", (10, 5)), ("RGBA", (9, 4))):
            with self.subTest(mode=mode, cell=cell):
                logical = Image.new(mode, (13, 11))
                colors = [
                    ((x * 37 + y * 19) % 256, (x * 17 + y * 53) % 256,
                     (x * 61 + y * 23) % 256, (x * 29 + y * 41) % 256)
                    for y in range(11) for x in range(13)
                ]
                logical.putdata([color[:len(mode)] for color in colors])
                source = self.root / f"{mode}.png"
                logical.resize((13 * cell[0], 11 * cell[1]), Image.Resampling.NEAREST).save(source)
                original_bytes = source.read_bytes()
                output = self.root / f"out-{mode}"

                self.assert_success(self.run_extractor(source, output))

                expected = logical.resize((26, 11), Image.Resampling.NEAREST)
                self.assert_pixels(output / source.name, expected)
                self.assertEqual(source.read_bytes(), original_bytes)
                self.assertTrue(json.loads((output / "manifest.json").read_text()))

        # Most edges suggest a doubled cell width. One low-contrast singleton
        # still belongs to the source grid and must retain its own output cell.
        logical = Image.new("RGB", (16, 16))
        logical.putdata([(40 if (x // 2) % 2 else 200, 20 + y * 13, 50 + y * 11)
                         for y in range(16) for x in range(16)])
        red, green, blue = logical.getpixel((5, 7))
        logical.putpixel((5, 7), (red + 1, green, blue))
        source = self.root / "minority-edge.png"
        logical.resize((160, 80), Image.Resampling.NEAREST).save(source)
        output = self.root / "out-minority-edge"

        self.assert_success(self.run_extractor(source, output))

        expected = logical.resize((32, 16), Image.Resampling.NEAREST)
        self.assert_pixels(output / source.name, expected)

    def test_manual_origin_samples_cell_centers_without_averaging(self):
        source_image = Image.new("RGB", (36, 15), (210, 190, 170))
        centers = [(13, 29, 47), (61, 83, 107), (127, 149, 173),
                   (193, 211, 233), (2, 67, 131), (241, 113, 31)]
        for index, color in enumerate(centers):
            source_image.putpixel((2 + (index % 3) * 10 + 5,
                                   3 + (index // 3) * 5 + 2), color)
        source = self.root / "centers.png"
        source_image.save(source)
        output = self.root / "out"

        self.assert_success(self.run_extractor(source, output, "--cell", "10x5", "--origin", "2,3"))

        expected = Image.new("RGB", (6, 2))
        expected.putdata([color for color in centers for _ in range(2)])
        self.assert_pixels(output / source.name, expected)

    def test_crop_selects_source_rectangle_without_rescaling_or_palette_mapping(self):
        source_image = Image.new("RGB", (24, 18), (1, 2, 3))
        colors = [(11, 31, 57), (79, 103, 139), (157, 181, 211), (239, 71, 17)]
        for index, color in enumerate(colors):
            x, y = 4 + (index % 2) * 6, 3 + (index // 2) * 4
            source_image.paste(color, (x, y, x + 6, y + 4))
        source = self.root / "cropped.png"
        source_image.save(source)
        output = self.root / "out"

        self.assert_success(self.run_extractor(source, output, "--cell", "6x4",
                                              "--crop", "4,3,12,8"))

        expected = Image.new("RGB", (4, 2))
        expected.putdata([color for color in colors for _ in range(2)])
        self.assert_pixels(output / source.name, expected)

    def test_flat_source_requires_explicit_grid(self):
        source = self.root / "flat.png"
        Image.new("RGB", (60, 40), (17, 89, 203)).save(source)
        rejected = self.root / "rejected"

        result = self.run_extractor(source, rejected)

        self.assertNotEqual(result.returncode, 0)
        self.assertIn("grid", (result.stdout + result.stderr).lower())
        self.assertFalse((rejected / source.name).exists())
        output = self.root / "explicit"
        self.assert_success(self.run_extractor(source, output, "--cell", "10x5"))
        self.assert_pixels(output / source.name, Image.new("RGB", (12, 8), (17, 89, 203)))

    def test_existing_destination_and_source_are_never_overwritten(self):
        source = self.root / "source.png"
        Image.new("RGB", (12, 10), (23, 97, 199)).save(source)
        original_source = source.read_bytes()
        output = self.root / "out"
        output.mkdir()
        destination = output / source.name
        destination.write_bytes(b"existing output must survive")

        result = self.run_extractor(source, output, "--cell", "6x5")

        self.assertNotEqual(result.returncode, 0)
        self.assertEqual(destination.read_bytes(), b"existing output must survive")
        result = self.run_extractor(source, self.root, "--cell", "6x5")
        self.assertNotEqual(result.returncode, 0)
        self.assertEqual(source.read_bytes(), original_source)


if __name__ == "__main__":
    unittest.main()
