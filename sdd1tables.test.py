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


tables = load_module("sdd1tables")
sdd1map = load_module("sdd1map")

TAGGED = ROOT / "roms" / "sfa2-usa-vc-sound-restored.sfc"


def entry(index: int, source: int, target: int | None, length: int | None) -> Any:
    return sdd1map.Entry(index=index, source=source, target=target, length=length)


class SourceKeyTest(unittest.TestCase):
    def test_a_stream_is_keyed_by_the_address_the_game_programs(self) -> None:
        self.assertEqual(tables.source_key(0x007890), (0xC0, 0x7890))
        self.assertEqual(tables.source_key(0x1AE002), (0xDA, 0xE002))
        self.assertEqual(tables.source_key(0x3E0FAE), (0xFE, 0x0FAE))

    def test_the_bank_carries_the_window_offset_the_engine_ors_in(self) -> None:
        for offset in (0x000000, 0x0F0000, 0x3F0000):
            bank, _ = tables.source_key(offset)

            self.assertEqual(bank, 0xC0 + (offset >> 16))


class AllocationTest(unittest.TestCase):
    def test_a_lone_stream_sits_at_its_own_address(self) -> None:
        placed = tables.allocate([(0xC0, 0x1234)])

        self.assertEqual(placed, [0x1234])

    def test_a_collision_moves_the_later_stream_forward(self) -> None:
        placed = tables.allocate([(0xC0, 0x1234), (0xC5, 0x1234)])

        self.assertEqual(placed, [0x1234, 0x1235])

    def test_the_scan_finds_every_stream_at_its_own_slot(self) -> None:
        keys = [(0xC0, 0x1000), (0xC5, 0x1000), (0xC0, 0x1001), (0xC5, 0x1002)]

        placed = tables.allocate(keys)

        tables.verify(keys, placed)

    def test_a_broken_placement_is_reported(self) -> None:
        keys = [(0xC0, 0x1000), (0xC0, 0x1002)]
        broken = [0x1003, 0x1002]

        with self.assertRaises(tables.PlacementError):
            tables.verify(keys, broken)

    def test_the_table_cannot_hold_more_streams_than_slots(self) -> None:
        keys = [(0xC0, i & 0xFFFF) for i in range(tables.SLOTS + 1)]

        with self.assertRaises(tables.PlacementError):
            tables.allocate(keys)


class BuildTest(unittest.TestCase):
    def test_four_tables_of_one_bank_each_come_back(self) -> None:
        entries = [entry(0, 0x007890, 0, 832)]

        built = tables.build([(e, 0x028000) for e in entries])

        self.assertEqual(len(built.key), tables.SLOTS)
        for part in (built.dest_low, built.dest_high, built.dest_bank):
            self.assertEqual(len(part), tables.SLOTS)

    def test_a_stream_reads_back_the_destination_it_was_given(self) -> None:
        e = entry(0, 0x007890, 0, 832)

        built = tables.build([(e, 0x1F8000)])
        slot = built.slots[0]

        self.assertEqual(built.key[slot], 0xC0)
        self.assertEqual(built.dest_low[slot], 0x00)
        self.assertEqual(built.dest_high[slot], 0x80)
        self.assertEqual(built.dest_bank[slot], 0x1F)

    def test_empty_slots_stay_zero_so_the_scan_skips_them(self) -> None:
        built = tables.build([(entry(0, 0x007890, 0, 832), 0x028000)])

        self.assertEqual(built.key[0x1234], tables.EMPTY)

    def test_a_destination_bank_of_zero_is_refused(self) -> None:
        with self.assertRaises(ValueError):
            tables.build([(entry(0, 0x007890, 0, 832), 0x008000)])


@unittest.skipUnless(TAGGED.exists(), "the tagged rom is not present")  # pragma: no cover
class RealMapTest(unittest.TestCase):
    entries: ClassVar[Any]

    @classmethod
    @override
    def setUpClass(cls) -> None:
        cls.entries = [e for e in sdd1map.build_map(dump.read(TAGGED)) if e.length]

    def test_every_real_stream_places_and_verifies(self) -> None:
        keys = [tables.source_key(e.source) for e in self.entries]

        placed = tables.allocate(keys)

        tables.verify(keys, placed)
        self.assertEqual(len(placed), len(self.entries))

    def test_the_real_map_fits_with_room_to_spare(self) -> None:
        keys = [tables.source_key(e.source) for e in self.entries]

        placed = tables.allocate(keys)

        self.assertLess(len(set(placed)), tables.SLOTS // 8)
        self.assertEqual(len(set(placed)), len(placed))

    def test_most_streams_land_on_their_own_address_without_probing(self) -> None:
        keys = [tables.source_key(e.source) for e in self.entries]

        placed = tables.allocate(keys)
        exact = sum(1 for (_, addr), slot in zip(keys, placed, strict=True) if addr == slot)

        self.assertGreater(exact / len(placed), 0.9)


class RepairTest(unittest.TestCase):
    """Placements the greedy pass gets wrong and the repair pass fixes."""

    AMBIGUOUS: ClassVar[list[tuple[int, int]]] = [
        (0xC1, 0x05),
        (0xC1, 0x3E),
        (0xC1, 0x26),
        (0xC1, 0x2D),
        (0xC2, 0x1B),
        (0xC2, 0x11),
        (0xC1, 0x11),
        (0xC0, 0x20),
        (0xC2, 0x12),
        (0xC1, 0x0C),
        (0xC2, 0x09),
        (0xC2, 0x2A),
        (0xC1, 0x0C),
        (0xC1, 0x37),
        (0xC1, 0x1A),
    ]
    """A key set crowded enough that the first placement leaves keys ambiguous.

    Found by searching random key sets for one that reaches the repair pass. It
    carries a repeated key, so the repair cannot succeed and the refusal comes
    after the attempts rather than instead of them. Keys this crowded do not
    occur in either cartridge, which is why neither the repair pass nor the
    refusal is reachable from the real tables.
    """

    def test_a_key_set_the_repair_cannot_settle_is_refused(self) -> None:
        with self.assertRaises(tables.PlacementError):
            tables.allocate(self.AMBIGUOUS)

    def test_the_refusal_says_the_scans_stayed_ambiguous(self) -> None:
        with self.assertRaises(tables.PlacementError) as refusal:
            tables.allocate(self.AMBIGUOUS)

        self.assertIn("unambiguous", str(refusal.exception))

    def test_two_keys_that_cannot_be_told_apart_are_refused(self) -> None:
        with self.assertRaises(tables.PlacementError):
            tables.allocate([(0xC1, 0x100), (0xC1, 0x100)])

    def test_more_keys_than_slots_are_refused(self) -> None:
        with self.assertRaises(tables.PlacementError):
            tables.allocate([(0xC1, 0)] * (tables.SLOTS + 1))


class VerifyTest(unittest.TestCase):
    """Checking a placement rather than producing one."""

    def test_a_placement_where_every_key_scans_correctly_is_accepted(self) -> None:
        keys = [(0xC1, 0x100), (0xC2, 0x200)]

        tables.verify(keys, tables.allocate(keys))

    def test_two_keys_given_the_same_slot_are_refused(self) -> None:
        with self.assertRaises(tables.PlacementError) as refusal:
            tables.verify([(0xC1, 0x100), (0xC2, 0x200)], [0x100, 0x100])

        self.assertIn("used twice", str(refusal.exception))

    def test_a_key_that_scans_somewhere_else_is_refused(self) -> None:
        with self.assertRaises(tables.PlacementError) as refusal:
            tables.verify([(0xC1, 0x100), (0xC1, 0x200)], [0x300, 0x100])

        self.assertIn("scans to", str(refusal.exception))


class ScanTest(unittest.TestCase):
    """Following the table from an address until the bank matches."""

    def test_a_bank_that_is_in_the_table_is_found(self) -> None:
        self.assertEqual(tables._scan({0x100: 0xC1}, 0xC1, 0x100), 0x100)

    def test_a_bank_a_few_slots_along_is_found(self) -> None:
        self.assertEqual(tables._scan({0x103: 0xC1}, 0xC1, 0x100), 0x103)

    def test_a_bank_that_is_not_in_the_table_is_not_found(self) -> None:
        self.assertIsNone(tables._scan({0x100: 0xC2}, 0xC1, 0x100))


class FullTableTest(unittest.TestCase):
    """A table with no slot left to give."""

    def test_a_full_table_has_no_free_slot(self) -> None:
        full = dict.fromkeys(range(tables.SLOTS), 0xC1)

        with self.assertRaises(tables.PlacementError):
            tables._first_free(full, 0)


if __name__ == "__main__":
    unittest.main(verbosity=2)
