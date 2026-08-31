import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "tools"))

import sample_audit as audit  # noqa: E402

DIRECTORY = 0x1000

FIRST = 0x1500


def blank():
    return bytearray(audit.APU_RAM)


def put_directory(ram, index, start, loop):
    at = DIRECTORY + index * 4
    ram[at] = start & 0xFF
    ram[at + 1] = start >> 8
    ram[at + 2] = loop & 0xFF
    ram[at + 3] = loop >> 8


def put_block(ram, at, last=False, loop=False, level=0x0C, filter_index=0, nibble=0x77):
    ram[at] = (level << 4) | (filter_index << 2) | (0x01 if last else 0) | (0x02 if loop else 0)
    for offset in range(1, 9):
        ram[at + offset] = nibble


def put_sample(ram, index, at, blocks=3, loop=False):
    put_directory(ram, index, at, at)
    for step in range(blocks):
        last = step == blocks - 1
        put_block(ram, at + step * audit.BLOCK_BYTES, last=last, loop=loop and last)


class DirectoryTest(unittest.TestCase):
    def test_an_entry_reads_back_the_addresses_it_was_given(self) -> None:
        ram = blank()
        put_directory(ram, 5, 0x1234, 0x5678)

        found = audit.entry(ram, DIRECTORY, 5)

        self.assertEqual(found, (0x1234, 0x5678))

    def test_the_directory_wraps_inside_the_sixty_four_kilobytes(self) -> None:
        ram = blank()
        put_directory(ram, 0, 0x1234, 0x1234)

        self.assertEqual(audit.entry(ram, DIRECTORY, 0), (0x1234, 0x1234))


class ChainTest(unittest.TestCase):
    def test_a_chain_ends_where_its_last_block_says_it_does(self) -> None:
        ram = blank()
        put_sample(ram, 0, FIRST, blocks=3)

        found = audit.chain(ram, FIRST)

        self.assertEqual(found.blocks, 3)
        self.assertIsNone(found.fault)

    def test_a_chain_covers_every_byte_of_every_block_it_walked(self) -> None:
        ram = blank()
        put_sample(ram, 0, FIRST, blocks=2)

        found = audit.chain(ram, FIRST)

        self.assertEqual(found.reach, range(FIRST, FIRST + 2 * audit.BLOCK_BYTES))

    def test_a_chain_that_never_ends_is_reported_rather_than_walked_forever(self) -> None:
        ram = blank()
        for at in range(FIRST, audit.APU_RAM - audit.BLOCK_BYTES, audit.BLOCK_BYTES):
            put_block(ram, at, last=False)

        found = audit.chain(ram, FIRST)

        self.assertEqual(found.fault, audit.RUNS_OFF)

    def test_a_chain_starting_past_the_end_is_refused(self) -> None:
        found = audit.chain(blank(), audit.APU_RAM - 4)

        self.assertEqual(found.fault, audit.RUNS_OFF)

    def test_a_chain_filling_the_whole_memory_stops_at_the_last_block(self) -> None:
        found = audit.chain(blank(), 0x0000)

        self.assertEqual(found.fault, audit.RUNS_OFF)
        self.assertEqual(found.blocks, audit.MAX_BLOCKS)

    def test_a_chain_of_one_block_is_a_chain(self) -> None:
        ram = blank()
        put_sample(ram, 0, FIRST, blocks=1)

        self.assertEqual(audit.chain(ram, FIRST).blocks, 1)


class PlayabilityTest(unittest.TestCase):
    def test_a_well_formed_sample_produces_sound_through_the_chip(self) -> None:
        ram = blank()
        put_sample(ram, 0, FIRST, blocks=4, loop=True)

        rendered = audit.play(ram, DIRECTORY, 0, samples=256)

        self.assertTrue(any(rendered))

    def test_a_sample_of_silence_produces_none(self) -> None:
        ram = blank()
        put_directory(ram, 0, FIRST, FIRST)
        put_block(ram, FIRST, last=True, level=0x00, nibble=0x00)

        rendered = audit.play(ram, DIRECTORY, 0, samples=64)

        self.assertFalse(any(rendered))

    def test_the_chip_reports_reaching_the_end_of_a_short_sample(self) -> None:
        ram = blank()
        put_sample(ram, 0, FIRST, blocks=1)

        self.assertTrue(audit.reaches_end(ram, DIRECTORY, 0))

    def test_and_does_not_for_one_that_loops_forever(self) -> None:
        ram = blank()
        put_sample(ram, 0, FIRST, blocks=200, loop=False)

        self.assertFalse(audit.reaches_end(ram, DIRECTORY, 0, samples=8))


class AuditTest(unittest.TestCase):
    def test_a_bank_whose_samples_are_all_well_formed_reports_nothing(self) -> None:
        ram = blank()
        put_sample(ram, 0, FIRST, blocks=2)
        put_sample(ram, 1, FIRST + 0x100, blocks=2)

        self.assertEqual(audit.faults(ram, DIRECTORY, (0, 1)), [])

    def test_a_sample_that_runs_off_the_end_is_named(self) -> None:
        ram = blank()
        put_directory(ram, 3, audit.APU_RAM - 4, audit.APU_RAM - 4)

        found = audit.faults(ram, DIRECTORY, (3,))

        self.assertEqual(found[0].sample, 3)
        self.assertEqual(found[0].fault, audit.RUNS_OFF)

    def test_a_loop_point_outside_the_sample_is_named(self) -> None:
        ram = blank()
        put_sample(ram, 0, FIRST, blocks=2)
        put_directory(ram, 0, FIRST, FIRST + 0x400)

        found = audit.faults(ram, DIRECTORY, (0,))

        self.assertEqual(found[0].fault, audit.LOOP_OUTSIDE)

    def test_a_loop_point_off_the_block_grid_is_named(self) -> None:
        ram = blank()
        put_sample(ram, 0, FIRST, blocks=2)
        put_directory(ram, 0, FIRST, FIRST + 3)

        found = audit.faults(ram, DIRECTORY, (0,))

        self.assertEqual(found[0].fault, audit.LOOP_UNALIGNED)

    def test_a_sample_nobody_uses_is_not_audited(self) -> None:
        ram = blank()
        put_sample(ram, 0, FIRST, blocks=2)
        put_directory(ram, 7, audit.APU_RAM - 4, audit.APU_RAM - 4)

        self.assertEqual(audit.faults(ram, DIRECTORY, (0,)), [])


class OverlapTest(unittest.TestCase):
    def test_two_samples_that_do_not_touch_report_nothing(self) -> None:
        ram = blank()
        put_sample(ram, 0, FIRST, blocks=2)
        put_sample(ram, 1, FIRST + 0x100, blocks=2)

        self.assertEqual(audit.overlaps(ram, DIRECTORY, (0, 1)), [])

    def test_two_samples_sharing_bytes_are_reported_as_a_pair(self) -> None:
        ram = blank()
        put_sample(ram, 0, FIRST, blocks=4)
        put_directory(ram, 1, FIRST + audit.BLOCK_BYTES, FIRST + audit.BLOCK_BYTES)

        found = audit.overlaps(ram, DIRECTORY, (0, 1))

        self.assertEqual(found[0][:2], (0, 1))

    def test_a_sample_deliberately_shared_by_two_entries_is_not_an_overlap(self) -> None:
        ram = blank()
        put_sample(ram, 0, FIRST, blocks=2)
        put_directory(ram, 1, FIRST, FIRST)

        self.assertEqual(audit.overlaps(ram, DIRECTORY, (0, 1)), [])


class WriteCollisionTest(unittest.TestCase):
    def test_an_upload_clear_of_every_playing_sample_is_safe(self) -> None:
        ram = blank()
        put_sample(ram, 0, FIRST, blocks=2)

        found = audit.collisions(ram, DIRECTORY, playing=(0,), written=range(0x8000, 0x8100))

        self.assertEqual(found, [])

    def test_an_upload_landing_on_a_playing_sample_is_reported(self) -> None:
        ram = blank()
        put_sample(ram, 0, FIRST, blocks=2)

        found = audit.collisions(ram, DIRECTORY, playing=(0,), written=range(FIRST, FIRST + 4))

        self.assertEqual(found[0].sample, 0)

    def test_an_upload_touching_the_directory_entry_itself_is_reported(self) -> None:
        ram = blank()
        put_sample(ram, 0, FIRST, blocks=2)

        found = audit.collisions(
            ram, DIRECTORY, playing=(0,), written=range(DIRECTORY, DIRECTORY + 4)
        )

        self.assertEqual(found[0].fault, audit.DIRECTORY_WRITTEN)

    def test_a_sample_that_is_not_playing_may_be_overwritten(self) -> None:
        ram = blank()
        put_sample(ram, 0, FIRST, blocks=2)
        put_sample(ram, 1, FIRST + 0x100, blocks=2)

        found = audit.collisions(
            ram, DIRECTORY, playing=(0,), written=range(FIRST + 0x100, FIRST + 0x110)
        )

        self.assertEqual(found, [])


class ReportTest(unittest.TestCase):
    def test_a_clean_bank_says_how_many_it_looked_at(self) -> None:
        ram = blank()
        put_sample(ram, 0, FIRST, blocks=2)

        lines = audit.report(ram, DIRECTORY, (0,))

        self.assertIn("1 samples", lines[0])

    def test_a_bank_with_a_fault_names_it(self) -> None:
        ram = blank()
        put_directory(ram, 0, audit.APU_RAM - 4, audit.APU_RAM - 4)

        lines = audit.report(ram, DIRECTORY, (0,))

        self.assertIn(audit.RUNS_OFF, lines[0])

    def test_a_bank_with_an_overlap_names_the_pair(self) -> None:
        ram = blank()
        put_sample(ram, 0, FIRST, blocks=4)
        put_directory(ram, 1, FIRST + audit.BLOCK_BYTES, FIRST + audit.BLOCK_BYTES)

        lines = audit.report(ram, DIRECTORY, (0, 1))

        self.assertTrue(any("share" in line for line in lines))


class EntryPointTest(unittest.TestCase):
    def image(self, ram):
        where = Path(tempfile.mkdtemp()) / "apu.bin"
        where.write_bytes(bytes(ram))
        return where

    def test_no_arguments_prints_the_usage_and_says_so(self) -> None:
        self.assertEqual(audit.main([]), 2)

    def test_an_image_and_a_directory_are_enough(self) -> None:
        ram = blank()
        put_sample(ram, 0, FIRST, blocks=2)

        self.assertEqual(audit.main([str(self.image(ram)), hex(DIRECTORY), "0"]), 0)

    def test_naming_no_samples_looks_at_every_entry(self) -> None:
        ram = blank()
        put_sample(ram, 0, FIRST, blocks=2)

        self.assertEqual(audit.main([str(self.image(ram)), hex(DIRECTORY)]), 0)


class ReadingTest(unittest.TestCase):
    def test_a_chain_prints_as_where_it_started_and_how_far_it_got(self) -> None:
        ram = blank()
        put_sample(ram, 0, FIRST, blocks=2)

        self.assertIn("2 blocks", repr(audit.chain(ram, FIRST)))

    def test_a_chain_that_did_not_end_says_so(self) -> None:
        self.assertIn(audit.RUNS_OFF, repr(audit.chain(blank(), audit.APU_RAM - 4)))

    def test_two_faults_naming_the_same_thing_are_the_same_fault(self) -> None:
        first = audit.Fault(sample=3, fault=audit.RUNS_OFF, at=0x1500)
        second = audit.Fault(sample=3, fault=audit.RUNS_OFF, at=0x1500)

        self.assertEqual([first], [second])

    def test_and_two_naming_different_samples_are_not(self) -> None:
        first = audit.Fault(sample=3, fault=audit.RUNS_OFF, at=0x1500)
        second = audit.Fault(sample=4, fault=audit.RUNS_OFF, at=0x1500)

        self.assertNotEqual([first], [second])

    def test_a_fault_prints_as_the_sample_and_what_is_wrong_with_it(self) -> None:
        found = audit.Fault(sample=3, fault=audit.RUNS_OFF, at=0x1500)

        self.assertIn("3", repr(found))
        self.assertIn(audit.RUNS_OFF, repr(found))


class LoadTest(unittest.TestCase):
    def test_an_apu_image_of_the_wrong_size_is_refused(self) -> None:
        with self.assertRaises(audit.Unreadable):
            audit.load(bytes(16))

    def test_an_image_of_the_right_size_is_taken_as_it_is(self) -> None:
        self.assertEqual(len(audit.load(bytes(audit.APU_RAM))), audit.APU_RAM)


if __name__ == "__main__":
    unittest.main()
