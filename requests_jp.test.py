import importlib.util
import unittest
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parent

ROM_BYTES = 0x400000


def load_module(name: str) -> Any:
    spec = importlib.util.spec_from_file_location(name, ROOT / f"{name}.py")
    assert spec is not None and spec.loader is not None, "no loader for that path"
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


requests_jp = load_module("requests_jp")
jpstreams = load_module("jpstreams")

TABLE = dict(jpstreams.STREAMS)


class ShapeTest(unittest.TestCase):
    def test_every_entry_is_a_source_and_a_length(self) -> None:
        for entry in requests_jp.REQUESTS:
            self.assertEqual(len(entry), 2)

    def test_sources_are_unique(self) -> None:
        sources = [source for source, _ in requests_jp.REQUESTS]

        self.assertEqual(len(sources), len(set(sources)))

    def test_every_length_is_positive(self) -> None:
        for source, length in requests_jp.REQUESTS:
            self.assertGreater(length, 0, f"{source:#08x}")

    def test_every_source_lies_inside_a_four_megabyte_rom(self) -> None:
        for source, _ in requests_jp.REQUESTS:
            self.assertLess(source, ROM_BYTES, f"{source:#08x}")

    def test_the_set_is_not_empty(self) -> None:
        self.assertGreater(len(requests_jp.REQUESTS), 0)


class GateTest(unittest.TestCase):
    """The contract the recorded requests exist to enforce.

    Each entry is an address the retail cartridge was observed to decompress
    from, and the largest transfer it asked for. The converted image serves those
    reads from a table, so an address the hardware asks for and the table does
    not carry, or carries with a shorter length, hands the game the wrong bytes
    for something the cartridge demonstrably needs.
    """

    def test_every_address_the_hardware_asked_for_is_in_the_table(self) -> None:
        missing = [source for source, _ in requests_jp.REQUESTS if source not in TABLE]

        self.assertEqual([f"{source:#08x}" for source in missing], [])

    def test_no_entry_is_shorter_than_what_the_hardware_asked_for(self) -> None:
        short = [
            f"{source:#08x}: table {TABLE[source]} < observed {length}"
            for source, length in requests_jp.REQUESTS
            if source in TABLE and TABLE[source] < length
        ]

        self.assertEqual(short, [])

    def test_the_table_is_a_superset_rather_than_a_transcript(self) -> None:
        asked = {source for source, _ in requests_jp.REQUESTS}

        self.assertGreater(len(TABLE), len(asked))


if __name__ == "__main__":
    unittest.main()
