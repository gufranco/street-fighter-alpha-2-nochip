import importlib.util
import sys
import unittest
from pathlib import Path
from typing import Any, ClassVar, override

sys.path.insert(0, str(Path(__file__).resolve().parent))

import hardware

dump = hardware.load("romimage").dump


ROOT = Path(__file__).resolve().parent


def load_module(name: str) -> Any:
    spec = importlib.util.spec_from_file_location(name, ROOT / f"{name}.py")
    assert spec is not None and spec.loader is not None, "no loader for that path"
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


mapcheck = load_module("mapcheck")
jpstreams = load_module("jpstreams")

JP_ROM = ROOT / "roms" / "sfz2-jp-final.sfc"


class LoadTest(unittest.TestCase):
    def test_a_table_loads_as_sorted_pairs(self) -> None:
        self.assertEqual(mapcheck.load([(512, 64), (256, 32)]), [(256, 32), (512, 64)])

    def test_a_table_with_a_non_positive_length_is_rejected(self) -> None:
        with self.assertRaises(ValueError):
            mapcheck.load([(256, 0)])

    def test_the_shipped_table_is_the_default(self) -> None:
        self.assertEqual(len(mapcheck.load()), len(jpstreams.STREAMS))


class DuplicateTest(unittest.TestCase):
    def test_distinct_sources_report_no_duplicates(self) -> None:
        self.assertEqual(mapcheck.duplicate_sources([(1, 2), (3, 4)]), [])

    def test_a_repeated_source_is_reported(self) -> None:
        self.assertEqual(mapcheck.duplicate_sources([(1, 2), (1, 4)]), [1])


class KeyTest(unittest.TestCase):
    def test_a_source_maps_to_its_window_bank_and_offset(self) -> None:
        self.assertEqual(mapcheck.window_key(0x1A86EC), (0xDA, 0x86EC))

    def test_the_first_window_bank_is_c0(self) -> None:
        self.assertEqual(mapcheck.window_key(0x000000), (0xC0, 0x0000))


class ScanCostTest(unittest.TestCase):
    def test_an_empty_map_costs_nothing(self) -> None:
        self.assertEqual(mapcheck.scan_cost([]), (0, 0))

    def test_a_single_stream_is_found_immediately(self) -> None:
        median, worst = mapcheck.scan_cost([(0x1A86EC, 3936)])

        self.assertEqual(worst, 0)
        self.assertEqual(median, 0)

    def test_colliding_addresses_push_a_key_further_out(self) -> None:
        entries = [(0x000100 + (bank << 16), 32) for bank in range(4)]

        _, worst = mapcheck.scan_cost(entries)

        self.assertGreater(worst, 0)


@unittest.skipUnless(JP_ROM.exists(), "the Japanese ROM is absent")
class JapaneseMapTest(unittest.TestCase):
    entries: ClassVar[Any]
    rom: ClassVar[Any]

    @classmethod
    @override
    def setUpClass(cls) -> None:
        cls.rom = dump.read(JP_ROM)
        cls.entries = mapcheck.load()

    def test_the_map_holds_the_streams_the_build_needs(self) -> None:
        self.assertGreaterEqual(len(self.entries), 2816)

    def test_no_source_appears_twice(self) -> None:
        self.assertEqual(mapcheck.duplicate_sources(self.entries), [])

    def test_every_stream_decompresses(self) -> None:
        self.assertEqual(mapcheck.undecodable(self.rom, self.entries), [])

    def test_every_stream_stays_inside_the_rom(self) -> None:
        for source, _ in self.entries:
            self.assertLess(source, len(self.rom))

    def test_the_lookup_stays_cheap_to_scan(self) -> None:
        _, worst = mapcheck.scan_cost(self.entries)

        self.assertLessEqual(worst, mapcheck.SCAN_BUDGET)

    def test_the_streams_recovered_by_harvesting_are_present(self) -> None:
        sources = {source for source, _ in self.entries}

        for recovered in mapcheck.RECOVERED_JP:
            self.assertIn(recovered, sources)


if __name__ == "__main__":
    unittest.main(verbosity=2)
