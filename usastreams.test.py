import importlib.util
import sys
import unittest
from pathlib import Path
from typing import Any

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


usastreams = load_module("usastreams")
jpstreams = load_module("jpstreams")
rombuild = load_module("rombuild")

TAGGED_ROM = ROOT / "roms" / "sfa2-usa-vc-sound-restored.sfc"


class ShapeTest(unittest.TestCase):
    def test_the_table_holds_every_tagged_stream_plus_the_harvested_ones(self) -> None:
        self.assertEqual(len(usastreams.TAGGED), 2815)
        self.assertEqual(len(usastreams.STREAMS), 2815 + len(usastreams.HARVESTED))

    def test_the_harvested_entries_are_not_in_the_tagged_set(self) -> None:
        tagged = {source for source, _ in usastreams.TAGGED}

        for source, _ in usastreams.HARVESTED:
            self.assertNotIn(source, tagged, f"{source:#08x}")

    def test_the_table_is_the_tagged_set_merged_with_the_harvested_one(self) -> None:
        self.assertEqual(
            usastreams.STREAMS, tuple(sorted(usastreams.TAGGED + usastreams.HARVESTED))
        )

    def test_sources_are_unique(self) -> None:
        sources = [source for source, _ in usastreams.STREAMS]

        self.assertEqual(len(sources), len(set(sources)))

    def test_sources_are_ordered(self) -> None:
        sources = [source for source, _ in usastreams.STREAMS]

        self.assertEqual(sources, sorted(sources))

    def test_every_length_is_positive(self) -> None:
        for source, length in usastreams.STREAMS:
            self.assertGreater(length, 0, f"{source:#08x}")

    def test_every_source_lies_inside_a_four_megabyte_rom(self) -> None:
        for source, _ in usastreams.STREAMS:
            self.assertLess(source, 0x400000)

    def test_the_two_regions_are_different_tables(self) -> None:
        self.assertNotEqual(set(usastreams.STREAMS), set(jpstreams.STREAMS))


@unittest.skipUnless(TAGGED_ROM.exists(), "the tagged ROM is not present")  # pragma: no cover
class RegenerationTest(unittest.TestCase):
    def test_the_frozen_table_matches_what_the_tags_say(self) -> None:
        entries = rombuild.load_entries(dump.read(TAGGED_ROM))
        extracted = tuple((entry.source, entry.length) for entry in entries if entry.length)

        self.assertEqual(extracted, usastreams.TAGGED)


if __name__ == "__main__":
    unittest.main(verbosity=2)
