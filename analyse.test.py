import importlib.util
import unittest
from pathlib import Path
from typing import Any

MODULE_PATH = Path(__file__).resolve().parent / "analyse.py"


def load_module() -> Any:
    spec = importlib.util.spec_from_file_location("analyse", MODULE_PATH)
    assert spec is not None and spec.loader is not None, "no loader for that path"
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


an = load_module()


class CompressedShareTest(unittest.TestCase):
    def test_random_data_counts_as_compressed(self) -> None:
        import os

        share, total, _ = an.compressed_share(os.urandom(65536 * 4))

        self.assertEqual(share, 4)
        self.assertEqual(total, 4)

    def test_flat_data_counts_as_uncompressed(self) -> None:
        share, total, _ = an.compressed_share(b"\x00" * 65536 * 4)

        self.assertEqual(share, 0)
        self.assertEqual(total, 4)

    def test_the_threshold_is_explicit(self) -> None:
        self.assertGreater(an.COMPRESSED_RATIO, 0.8)
        self.assertLess(an.COMPRESSED_RATIO, 1.0)

    def test_the_threshold_catches_seven_bit_grade_entropy(self) -> None:
        import os
        import zlib

        block = bytes(b & 0x7F for b in os.urandom(65536))
        ratio = len(zlib.compress(block, 6)) / len(block)

        self.assertGreater(ratio, an.COMPRESSED_RATIO)


class NoveltyTest(unittest.TestCase):
    def test_identical_builds_have_no_new_data(self) -> None:
        a = bytes(range(256)) * 512

        new, total = an.novelty(a, a)

        self.assertEqual(new, 0)
        self.assertGreater(total, 0)

    def test_a_doubled_build_is_half_new(self) -> None:
        import os

        a = os.urandom(65536)
        b = a + os.urandom(65536)

        new, total = an.novelty(b, a)

        self.assertEqual(total, 128)
        self.assertGreaterEqual(new, 60)


class EstimateTest(unittest.TestCase):
    def test_expansion_scales_the_compressed_region(self) -> None:
        self.assertEqual(an.estimate_expanded(1_000_000, 2_000_000, 2.0), 3_000_000)

    def test_a_ratio_of_one_adds_nothing(self) -> None:
        self.assertEqual(an.estimate_expanded(1_000_000, 2_000_000, 1.0), 2_000_000)

    def test_mbit_conversion_is_exact(self) -> None:
        self.assertEqual(an.mbit(1048576), 8.0)


if __name__ == "__main__":
    unittest.main(verbosity=2)
