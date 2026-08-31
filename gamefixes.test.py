import importlib.util
import sys
import tempfile
import unittest
from collections.abc import Sequence
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).resolve().parent))

import hardware

sdd1 = hardware.load("sdd1")


ROOT = Path(__file__).resolve().parent


def load_module(name: str) -> Any:
    spec = importlib.util.spec_from_file_location(name, ROOT / f"{name}.py")
    assert spec is not None and spec.loader is not None, "no loader for that path"
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


gamefixes = load_module("gamefixes")
spcfast = load_module("spcfast")

USA = ROOT / "roms" / "sfa2-usa-final.sfc"
JP = ROOT / "roms" / "sfz2-jp-final.sfc"


def retail(path: Path) -> bytes:
    if not path.exists():
        raise unittest.SkipTest(f"{path} is not present")
    return path.read_bytes()


def carrier(fix: Any, filler: bytes = b"\x00" * 64) -> bytes:
    made: bytes = filler + fix.stock + filler
    return made


class TableTest(unittest.TestCase):
    def test_every_fix_replaces_a_run_of_its_own_length(self) -> None:
        for fix in gamefixes.FIXES:
            self.assertEqual(len(fix.stock), len(fix.patched), fix.name)

    def test_every_fix_actually_changes_something(self) -> None:
        for fix in gamefixes.FIXES:
            self.assertNotEqual(fix.stock, fix.patched, fix.name)

    def test_every_fix_names_the_regions_it_reaches(self) -> None:
        for fix in gamefixes.FIXES:
            self.assertTrue(fix.regions, fix.name)
            for region in fix.regions:
                self.assertIn(region, ("usa", "jp"), fix.name)

    def test_the_names_are_unique(self) -> None:
        names = [fix.name for fix in gamefixes.FIXES]

        self.assertEqual(len(names), len(set(names)))


class LocationTest(unittest.TestCase):
    def test_a_run_present_once_is_found(self) -> None:
        fix = gamefixes.FIXES[0]

        self.assertEqual(gamefixes.locate(carrier(fix), fix.stock), 64)

    def test_a_run_that_is_absent_reports_nothing(self) -> None:
        self.assertIsNone(gamefixes.locate(b"\x00" * 64, b"\xaa\xbb"))

    def test_a_run_present_twice_is_refused(self) -> None:
        fix = gamefixes.FIXES[0]
        twice = carrier(fix) + carrier(fix)

        with self.assertRaises(ValueError):
            gamefixes.locate(twice, fix.stock)


class ApplyTest(unittest.TestCase):
    def test_a_stock_run_becomes_the_patched_run(self) -> None:
        fix = gamefixes.FIXES[0]

        patched = gamefixes.apply(carrier(fix))

        self.assertEqual(patched[64 : 64 + len(fix.patched)], fix.patched)

    def test_applying_twice_changes_nothing_the_second_time(self) -> None:
        fix = gamefixes.FIXES[0]

        once = gamefixes.apply(carrier(fix))
        twice = gamefixes.apply(once)

        self.assertEqual(once, twice)

    def test_a_rom_carrying_no_fix_at_all_is_refused(self) -> None:
        with self.assertRaises(ValueError):
            gamefixes.apply(b"\x00" * 4096)

    def test_the_report_names_every_fix_and_its_state(self) -> None:
        fix = gamefixes.FIXES[0]

        found = gamefixes.survey(carrier(fix))

        self.assertEqual(found[fix.name], "applied")
        for other in gamefixes.FIXES[1:]:
            self.assertEqual(found[other.name], "absent")


class EmptyCallTest(unittest.TestCase):
    def rom_with(self, call: Any, sites: Sequence[int], filler: bytes = b"\x00" * 32) -> bytes:
        rom = bytearray(b"\x00" * 0x400000)
        rom[gamefixes.long_to_file(call.target)] = gamefixes.RTL
        run = gamefixes.call_run(call.target)
        for at in sites:
            rom[at : at + len(run)] = run
        return bytes(rom)

    def test_every_call_followed_by_a_return_is_found(self) -> None:
        call = gamefixes.EMPTY_CALLS[0]

        rom = self.rom_with(call, (0x1000, 0x2000))

        self.assertEqual(gamefixes.empty_call_sites(rom, call), [0x1000, 0x2000])

    def test_a_call_not_followed_by_a_return_is_left_alone(self) -> None:
        call = gamefixes.EMPTY_CALLS[0]
        rom = bytearray(self.rom_with(call, (0x1000,)))
        rom[0x1004] = 0xEA

        self.assertEqual(gamefixes.empty_call_sites(bytes(rom), call), [])

    def test_a_target_that_is_not_a_bare_return_is_refused(self) -> None:
        call = gamefixes.EMPTY_CALLS[0]
        rom = bytearray(self.rom_with(call, (0x1000,)))
        rom[gamefixes.long_to_file(call.target)] = 0xEA

        with self.assertRaises(ValueError):
            gamefixes.empty_call_sites(bytes(rom), call)

    def test_applying_turns_the_call_opcode_into_a_return(self) -> None:
        call = gamefixes.EMPTY_CALLS[0]
        rom = self.rom_with(call, (0x1000,))

        patched = gamefixes.apply(rom)

        self.assertEqual(patched[0x1000], gamefixes.RTS)
        self.assertEqual(patched[0x1001:0x1005], rom[0x1001:0x1005])

    def test_a_retired_site_is_reported_as_already_done(self) -> None:
        call = gamefixes.EMPTY_CALLS[0]
        rom = self.rom_with(call, (0x1000,))

        patched = gamefixes.apply(rom)

        self.assertEqual(gamefixes.empty_call_sites(patched, call), [])
        self.assertEqual(gamefixes.retired_sites(patched, call), [0x1000])

    def test_a_long_address_maps_to_its_window_offset(self) -> None:
        self.assertEqual(gamefixes.long_to_file(0xFFFF4D), 0x3FFF4D)
        self.assertEqual(gamefixes.long_to_file(0xC00000), 0x000000)


class RetailTest(unittest.TestCase):
    def test_every_empty_call_is_retired_in_both_regions(self) -> None:
        for path, expected in ((USA, 42), (JP, 42)):
            rom = retail(path)

            sites = gamefixes.empty_call_sites(rom, gamefixes.EMPTY_CALLS[0])

            self.assertEqual(len(sites), expected, str(path))

    def test_every_empty_call_target_is_a_bare_return(self) -> None:
        rom = retail(USA)

        for call in gamefixes.EMPTY_CALLS:
            at = gamefixes.long_to_file(call.target)

            self.assertEqual(rom[at], gamefixes.RTL, call.name)

    def test_the_three_routines_together_reach_forty_five_sites(self) -> None:
        rom = retail(USA)

        sites = sum(len(gamefixes.empty_call_sites(rom, call)) for call in gamefixes.EMPTY_CALLS)

        self.assertEqual(sites, 45)

    def test_every_fix_that_claims_usa_is_present_in_the_usa_rom(self) -> None:
        rom = retail(USA)

        found = gamefixes.survey(rom)

        for fix in gamefixes.FIXES:
            expected = "applied" if "usa" in fix.regions else "already"
            self.assertEqual(found[fix.name], expected, fix.name)

    def test_every_fix_that_claims_jp_is_present_in_the_jp_rom(self) -> None:
        rom = retail(JP)

        found = gamefixes.survey(rom)

        for fix in gamefixes.FIXES:
            if "jp" in fix.regions:
                self.assertEqual(found[fix.name], "applied", fix.name)
            else:
                self.assertIn(found[fix.name], ("already", "absent"), fix.name)

    def outside_the_checksum(self, rom: bytes | bytearray, patched: bytes | bytearray) -> int:
        field = range(spcfast.CHECKSUM_FIELD, spcfast.CHECKSUM_FIELD + 4)
        return sum(
            1
            for at, (before, after) in enumerate(zip(rom, patched, strict=True))
            if before != after and at not in field
        )

    def test_the_usa_rom_changes_by_exactly_the_declared_bytes(self) -> None:
        rom = retail(USA)

        patched = gamefixes.apply(rom)

        self.assertEqual(self.outside_the_checksum(rom, patched), gamefixes.changed_bytes(rom))

    def test_the_jp_rom_changes_by_exactly_the_declared_bytes(self) -> None:
        rom = retail(JP)

        patched = gamefixes.apply(rom)

        self.assertEqual(self.outside_the_checksum(rom, patched), gamefixes.changed_bytes(rom))

    def test_the_usa_rom_changes_more_bytes_than_the_jp_one(self) -> None:
        usa, jp = retail(USA), retail(JP)

        self.assertEqual(gamefixes.changed_bytes(usa), 214)
        self.assertEqual(gamefixes.changed_bytes(jp), 56)

    def test_the_patched_rom_carries_a_consistent_checksum(self) -> None:
        rom = retail(USA)

        patched = gamefixes.apply(rom)

        self.assertEqual(patched, spcfast.write_checksum(patched))

    def test_applying_to_an_already_patched_usa_rom_is_a_no_op(self) -> None:
        rom = retail(USA)

        once = gamefixes.apply(rom)

        self.assertEqual(gamefixes.apply(once), once)

    def test_every_sodom_plate_is_confined_to_one_region(self) -> None:
        confined = [fix.name for fix in gamefixes.FIXES if set(fix.regions) != {"usa", "jp"}]

        self.assertEqual(
            confined,
            [
                "sodom name on the life bar",
                "sodom name on the select screen",
                "sodom name on the vs screen",
                "sodom name on the vs results screen",
            ],
        )

    def test_the_rename_reaches_every_screen_that_shows_the_name(self) -> None:
        plates = [fix.name for fix in gamefixes.FIXES if fix.name.startswith("sodom name")]

        self.assertEqual(len(plates), 4)

    def occurrences(self, rom: bytes | bytearray, run: bytes) -> int:
        found, at = 0, rom.find(run)
        while at != -1:
            found += 1
            at = rom.find(run, at + 1)
        return found

    def test_a_fix_names_a_run_that_appears_once_in_every_region_it_claims(self) -> None:
        for path, region in ((USA, "usa"), (JP, "jp")):
            rom = retail(path)

            for fix in gamefixes.FIXES:
                if region not in fix.regions:
                    continue
                where = f"{fix.name} in {path.name}"
                self.assertEqual(self.occurrences(rom, fix.stock), 1, where)
                self.assertEqual(self.occurrences(rom, fix.patched), 0, where)

    def test_a_region_a_fix_does_not_claim_never_carries_the_stock_run(self) -> None:
        for path, region in ((USA, "usa"), (JP, "jp")):
            rom = retail(path)

            for fix in gamefixes.FIXES:
                if region in fix.regions:
                    continue

                self.assertEqual(self.occurrences(rom, fix.stock), 0, f"{fix.name} in {path.name}")

    def test_the_japanese_rom_already_reads_right_where_it_shares_the_run(self) -> None:
        rom = retail(JP)

        found = gamefixes.survey(rom)

        already = sorted(name for name, state in found.items() if state == "already")
        absent = sorted(name for name, state in found.items() if state == "absent")
        self.assertEqual(
            already,
            [
                "sodom name on the life bar",
                "sodom name on the select screen",
                "sodom name on the vs screen",
            ],
        )
        self.assertEqual(absent, ["sodom name on the vs results screen"])

    def test_the_vs_results_fix_only_turns_katana_into_sodom(self) -> None:
        rom = bytearray(retail(USA))
        fix = next(f for f in gamefixes.FIXES if f.name == "sodom name on the vs results screen")
        at = gamefixes.locate(bytes(rom), fix.stock)
        before = sdd1.decompress(bytes(rom), at, gamefixes.VS_RESULTS_LENGTH).data

        rom[at : at + len(fix.patched)] = fix.patched
        after = sdd1.decompress(bytes(rom), at, gamefixes.VS_RESULTS_LENGTH).data

        self.assertEqual(len(after), gamefixes.VS_RESULTS_LENGTH)
        moved = [i for i in range(len(before)) if before[i] != after[i]]
        self.assertEqual(moved, list(range(0x35A, 0x366, 2)))
        self.assertEqual(bytes(before[i] for i in moved), b"KATANA")
        self.assertEqual(bytes(after[i] for i in moved), b"SODOM ")

    def test_no_fix_writes_over_the_start_of_a_neighbouring_stream(self) -> None:
        usastreams = load_module("usastreams")
        rom = retail(USA)
        starts = sorted(start for start, _ in usastreams.STREAMS)

        for fix in gamefixes.FIXES:
            if "usa" not in fix.regions:
                continue
            at = gamefixes.locate(rom, fix.stock)
            inside = [s for s in starts if at < s < at + len(fix.stock)]

            self.assertEqual(inside, [], f"{fix.name} reaches into {inside}")

    def test_the_vs_results_fix_stops_where_the_next_stream_begins(self) -> None:
        usastreams = load_module("usastreams")
        rom = retail(USA)
        fix = next(f for f in gamefixes.FIXES if f.name == "sodom name on the vs results screen")
        at = gamefixes.locate(rom, fix.stock)

        following = min(start for start, _ in usastreams.STREAMS if start > at)

        self.assertEqual(at + len(fix.stock), following)

    def test_the_vs_results_fix_zero_fills_the_bytes_the_shorter_stream_leaves(self) -> None:
        fix = next(f for f in gamefixes.FIXES if f.name == "sodom name on the vs results screen")

        self.assertEqual(len(fix.patched), len(fix.stock))
        self.assertEqual(fix.patched[-6:], b"\x00" * 6)

    def test_the_akuma_pose_fixes_reach_both_regions(self) -> None:
        poses = [fix for fix in gamefixes.FIXES if fix.name.startswith("akuma")]

        self.assertEqual(len(poses), 2)
        for fix in poses:
            self.assertEqual(set(fix.regions), {"usa", "jp"}, fix.name)

    def test_the_reorder_puts_the_taunt_first_and_drops_the_dead_entry(self) -> None:
        fix = next(f for f in gamefixes.FIXES if f.name == "akuma win pose order")

        def words(run: bytes) -> list[int]:
            return [run[i] | (run[i + 1] << 8) for i in range(0, len(run), 2)]

        self.assertEqual(words(fix.stock), [0x390, 0x39E, 0x3C4, 0x3DA])
        self.assertEqual(words(fix.patched), [0x426, 0x390, 0x39E, 0x3DA])

    def test_the_index_moves_with_the_pose_it_names(self) -> None:
        fix = next(f for f in gamefixes.FIXES if f.name == "akuma silent win pose index")

        moved = [(a, b) for a, b in zip(fix.stock, fix.patched, strict=True) if a != b]

        self.assertEqual(moved, [(0x01, 0x02)])

    def test_the_silent_pose_index_matches_where_the_reorder_puts_it(self) -> None:
        order = next(f for f in gamefixes.FIXES if f.name == "akuma win pose order")
        index = next(f for f in gamefixes.FIXES if f.name == "akuma silent win pose index")

        def words(run: bytes) -> list[int]:
            return [run[i] | (run[i + 1] << 8) for i in range(0, len(run), 2)]

        silent = 0x39E
        self.assertEqual(words(order.stock).index(silent), index.stock[3])
        self.assertEqual(words(order.patched).index(silent), index.patched[3])

    def test_the_object_table_fix_reaches_both_regions(self) -> None:
        fix = next(f for f in gamefixes.FIXES if f.name == "object table overflow")

        self.assertEqual(set(fix.regions), {"usa", "jp"})

    def test_the_object_table_fix_trades_a_store_for_a_decrement(self) -> None:
        fix = next(f for f in gamefixes.FIXES if f.name == "object table overflow")

        moved = [
            (i, a, b) for i, (a, b) in enumerate(zip(fix.stock, fix.patched, strict=True)) if a != b
        ]

        self.assertEqual(moved, [(5, 0x84, 0xD6), (6, 0x20, 0x87), (10, 0x05, 0x03)])

    def test_the_object_table_fix_keeps_the_run_the_same_length(self) -> None:
        fix = next(f for f in gamefixes.FIXES if f.name == "object table overflow")

        self.assertEqual(len(fix.stock), 16)
        self.assertEqual(len(fix.patched), 16)

    def test_no_fix_changes_how_a_stage_animates(self) -> None:
        names = [fix.name for fix in gamefixes.FIXES]

        self.assertNotIn("stage animation frame gate", names)
        self.assertEqual([name for name in names if name.endswith("stage lights")], [])

    def test_no_fix_claims_a_scene_that_cannot_be_driven(self) -> None:
        names = [fix.name for fix in gamefixes.FIXES]

        self.assertNotIn("akuma jump frame", names)


class EntryTest(unittest.TestCase):
    """The command line, run with both streams collected rather than printed."""

    def _paths(self) -> tuple[Path, Path]:
        where = Path(tempfile.mkdtemp())
        source = where / "in.sfc"
        source.write_bytes(USA.read_bytes())
        return source, where / "out.sfc"

    def test_too_few_arguments_are_refused_with_the_usage(self) -> None:
        complained: list[Any] = []

        code = gamefixes.main(["gamefixes.py"], say=lambda _l: None, complain=complained.append)

        self.assertEqual(code, 2)
        self.assertIn("usage", complained[0])

    @unittest.skipUnless(
        USA.exists(), "the retail dump is supplied by the builder"
    )  # pragma: no cover
    def test_patching_the_source_in_place_is_refused(self) -> None:
        source, _ = self._paths()
        complained: list[Any] = []

        code = gamefixes.main(
            ["gamefixes.py", str(source), str(source)],
            say=lambda _l: None,
            complain=complained.append,
        )

        self.assertEqual(code, 1)
        self.assertIn("in place", complained[0])

    @unittest.skipUnless(
        USA.exists(), "the retail dump is supplied by the builder"
    )  # pragma: no cover
    def test_a_run_writes_the_patched_image_and_says_what_it_did(self) -> None:
        source, output = self._paths()
        said: list[Any] = []

        code = gamefixes.main(["gamefixes.py", str(source), str(output)], say=said.append)

        self.assertEqual(code, 0)
        self.assertTrue(output.exists())
        self.assertTrue(said)


if __name__ == "__main__":
    unittest.main()
