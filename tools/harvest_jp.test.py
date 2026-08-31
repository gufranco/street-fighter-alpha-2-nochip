import importlib.util
import sys
import unittest
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))


def load_module(name: str, path: Path) -> Any:
    spec = importlib.util.spec_from_file_location(name, path)
    assert spec is not None and spec.loader is not None, "no loader for that path"
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


harvest_jp = load_module("harvest_jp", ROOT / "tools" / "harvest_jp.py")

BUDGET = harvest_jp.SCAN_BUDGET
BASE = harvest_jp.WINDOW_BASE


def _scan(address, channels):
    parts = " ".join(
        f"ch{name}={bank:02X}:{addr:04X}:{count}:fixed1"
        for name, (bank, addr, count) in zip((0, 1, 7), channels, strict=True)
    )
    return f"SCAN addr={address:04X} {parts}"


def _scanlen(address, steps):
    return f"SCANLEN addr={address:04X} steps={steps}"


class MissedTest(unittest.TestCase):
    def test_a_lookup_within_the_budget_is_not_a_miss(self) -> None:
        lines = [
            _scan(0x104C, ((BASE + 0x19, 0x104C, 832), (0x00, 0x0000, 0), (0x00, 0x0000, 0))),
            _scanlen(0x104C, BUDGET),
        ]

        self.assertEqual(harvest_jp.missed_streams(lines), {})

    def test_a_lookup_past_the_budget_names_the_stream_it_wanted(self) -> None:
        lines = [
            _scan(0x104C, ((BASE + 0x19, 0x104C, 832), (0x00, 0x0000, 0), (0x00, 0x0000, 0))),
            _scanlen(0x104C, BUDGET + 1),
        ]

        self.assertEqual(harvest_jp.missed_streams(lines), {0x19104C: 832})

    def test_a_lookup_with_no_scan_before_it_names_nothing(self) -> None:
        self.assertEqual(harvest_jp.missed_streams([_scanlen(0x104C, BUDGET + 1)]), {})

    def test_a_scan_for_a_different_address_is_not_the_one(self) -> None:
        lines = [
            _scan(0x2000, ((BASE + 0x19, 0x2000, 832), (0x00, 0x0000, 0), (0x00, 0x0000, 0))),
            _scanlen(0x104C, BUDGET + 1),
        ]

        self.assertEqual(harvest_jp.missed_streams(lines), {})

    def test_a_channel_asking_for_nothing_is_not_a_stream(self) -> None:
        lines = [
            _scan(0x104C, ((BASE + 0x19, 0x104C, 0), (0x00, 0x0000, 0), (0x00, 0x0000, 0))),
            _scanlen(0x104C, BUDGET + 1),
        ]

        self.assertEqual(harvest_jp.missed_streams(lines), {})

    def test_a_channel_reading_outside_the_window_is_not_a_stream(self) -> None:
        lines = [
            _scan(0x104C, ((0x7E, 0x104C, 832), (0x00, 0x0000, 0), (0x00, 0x0000, 0))),
            _scanlen(0x104C, BUDGET + 1),
        ]

        self.assertEqual(harvest_jp.missed_streams(lines), {})

    def test_the_largest_length_asked_for_wins(self) -> None:
        lines = [
            _scan(0x104C, ((BASE + 0x19, 0x104C, 832), (0x00, 0x0000, 0), (0x00, 0x0000, 0))),
            _scanlen(0x104C, BUDGET + 1),
            _scanlen(0x9999, 1),
            _scanlen(0x9998, 1),
            _scanlen(0x9997, 1),
            _scanlen(0x9996, 1),
            _scanlen(0x9995, 1),
            _scan(0x104C, ((BASE + 0x19, 0x104C, 2048), (0x00, 0x0000, 0), (0x00, 0x0000, 0))),
            _scanlen(0x104C, BUDGET + 1),
        ]

        self.assertEqual(harvest_jp.missed_streams(lines), {0x19104C: 2048})

    def test_a_later_shorter_request_does_not_shrink_the_answer(self) -> None:
        lines = [
            _scan(0x104C, ((BASE + 0x19, 0x104C, 2048), (0x00, 0x0000, 0), (0x00, 0x0000, 0))),
            _scanlen(0x104C, BUDGET + 1),
            _scanlen(0x9999, 1),
            _scanlen(0x9998, 1),
            _scanlen(0x9997, 1),
            _scanlen(0x9996, 1),
            _scanlen(0x9995, 1),
            _scan(0x104C, ((BASE + 0x19, 0x104C, 832), (0x00, 0x0000, 0), (0x00, 0x0000, 0))),
            _scanlen(0x104C, BUDGET + 1),
        ]

        self.assertEqual(harvest_jp.missed_streams(lines), {0x19104C: 2048})

    def test_a_scan_more_than_four_lines_back_is_out_of_reach(self) -> None:
        lines = [
            _scan(0x104C, ((BASE + 0x19, 0x104C, 832), (0x00, 0x0000, 0), (0x00, 0x0000, 0))),
            _scanlen(0x9999, 1),
            _scanlen(0x9998, 1),
            _scanlen(0x9997, 1),
            _scanlen(0x9996, 1),
            _scanlen(0x9995, 1),
            _scanlen(0x104C, BUDGET + 1),
        ]

        self.assertEqual(harvest_jp.missed_streams(lines), {})

    def test_the_earliest_scan_in_reach_is_the_one_used(self) -> None:
        """Not the nearest, which is worth knowing before trusting a busy log.

        The search walks forward from four lines back and stops at the first scan
        naming the address it wants. Two scans for one address inside that window
        therefore resolve to the older, which in a real log is the request that
        actually preceded the lookup.
        """
        lines = [
            _scan(0x104C, ((BASE + 0x19, 0x104C, 832), (0x00, 0x0000, 0), (0x00, 0x0000, 0))),
            _scan(0x104C, ((BASE + 0x19, 0x104C, 4096), (0x00, 0x0000, 0), (0x00, 0x0000, 0))),
            _scanlen(0x104C, BUDGET + 1),
        ]

        self.assertEqual(harvest_jp.missed_streams(lines), {0x19104C: 832})

    def test_any_of_the_three_channels_can_be_the_one_asking(self) -> None:
        lines = [
            _scan(0x104C, ((0x00, 0x0000, 0), (0x00, 0x0000, 0), (BASE + 0x19, 0x104C, 512))),
            _scanlen(0x104C, BUDGET + 1),
        ]

        self.assertEqual(harvest_jp.missed_streams(lines), {0x19104C: 512})

    def test_an_empty_log_names_nothing(self) -> None:
        self.assertEqual(harvest_jp.missed_streams([]), {})

    def test_a_source_address_is_the_window_offset_not_the_bank_number(self) -> None:
        lines = [
            _scan(0x8000, ((BASE + 0x02, 0x8000, 64), (0x00, 0x0000, 0), (0x00, 0x0000, 0))),
            _scanlen(0x8000, BUDGET + 1),
        ]

        self.assertEqual(harvest_jp.missed_streams(lines), {0x028000: 64})


class VariantTest(unittest.TestCase):
    @unittest.skipUnless(harvest_jp.RETAIL.exists(), "the retail cartridge is not present")
    def test_the_harvest_builds_four_variants_and_none_of_them_twice(self) -> None:
        import hardware

        variants = harvest_jp.variants(hardware.load("romimage").dump.read(harvest_jp.RETAIL))

        self.assertEqual(sorted(variants), ["base", "both", "sa", "spc"])
        self.assertEqual(len(set(variants.values())), 4)

    @unittest.skipUnless(harvest_jp.RETAIL.exists(), "the retail cartridge is not present")
    def test_the_harvest_variants_carry_no_skip_patch(self) -> None:
        """The harvest measures what the cartridge asks for, so it patches nothing that changes that.

        The skip patch exists to avoid an upload the cartridge would otherwise
        repeat. A harvest that carried it would record fewer requests than the
        hardware makes, and the table built from that harvest would be short.
        """
        import hardware

        repeatload = load_module("repeatload", ROOT / "repeatload.py")
        variants = harvest_jp.variants(hardware.load("romimage").dump.read(harvest_jp.RETAIL))

        for name, image in variants.items():
            self.assertFalse(repeatload.is_patched(image), name)

    def test_the_window_base_is_where_the_cartridge_window_starts(self) -> None:
        self.assertEqual(harvest_jp.WINDOW_BASE, 0xC0)

    def test_the_scan_budget_matches_the_one_the_verifier_uses(self) -> None:
        verify_image = load_module("verify_image", ROOT / "tools" / "verify_image.py")

        self.assertEqual(harvest_jp.SCAN_BUDGET, verify_image.SCAN_BUDGET)


if __name__ == "__main__":
    unittest.main()
