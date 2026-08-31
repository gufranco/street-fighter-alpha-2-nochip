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


class MbitTest(unittest.TestCase):
    """Sizes in the unit cartridges are sold in."""

    def test_a_megabyte_is_eight_megabit(self) -> None:
        self.assertEqual(an.mbit(1048576), 8)

    def test_nothing_is_nothing(self) -> None:
        self.assertEqual(an.mbit(0), 0)


class ReportTest(unittest.TestCase):
    """One line about one cartridge."""

    def test_it_names_the_label_it_was_given(self) -> None:
        said: list[str] = []

        an.report("a cartridge", bytes(0x20000), said.append)

        self.assertIn("a cartridge", said[0])

    def test_flat_data_reports_no_compressed_bytes(self) -> None:
        self.assertEqual(an.report("flat", bytes(0x20000), lambda _l: None), 0)

    def test_random_data_reports_every_block_as_compressed(self) -> None:
        import os

        found = an.report("random", os.urandom(0x20000), lambda _l: None)

        self.assertEqual(found, 2 * an.BLOCK)


class CommandTest(unittest.TestCase):
    """The projection, driven without four dumps on the machine."""

    def run_with(self, roms: dict[str, bytes]) -> tuple[int, list[str]]:
        said: list[str] = []
        code = an.main(
            ["an.py", "so_orig", "so_patched", "sfa2_final", "sfa2_proto"],
            read=lambda path: roms[path.name],
            say=said.append,
        )
        return code, said

    @staticmethod
    def four() -> dict[str, bytes]:
        import os

        return {
            "so_orig": bytes(0x40000),
            "so_patched": bytes(0x40000) + os.urandom(0x40000),
            "sfa2_final": os.urandom(0x40000),
            "sfa2_proto": bytes(0x40000),
        }

    def test_a_run_over_four_cartridges_succeeds(self) -> None:
        code, _ = self.run_with(self.four())

        self.assertEqual(code, 0)

    def test_it_reports_the_whole_rom_growth_factor(self) -> None:
        _, said = self.run_with(self.four())

        self.assertIn("whole-ROM growth factor: 2.00x", "\n".join(said))

    def test_it_counts_the_chunks_the_patch_added(self) -> None:
        _, said = self.run_with(self.four())

        self.assertIn("256/512", "\n".join(said))

    def test_it_projects_one_line_per_expansion_ratio(self) -> None:
        _, said = self.run_with(self.four())

        self.assertEqual(len([one for one in said if "fits 128 Mbit" in one]), 3)

    def test_a_projection_that_fits_says_so(self) -> None:
        _, said = self.run_with(self.four())

        self.assertIn("yes", "\n".join(said))

    def test_a_projection_that_does_not_fit_says_no(self) -> None:
        import os

        roms = self.four()
        roms["sfa2_final"] = os.urandom(0x1000000)

        _, said = self.run_with(roms)

        self.assertIn("NO", "\n".join(said))


if __name__ == "__main__":
    unittest.main(verbosity=2)
