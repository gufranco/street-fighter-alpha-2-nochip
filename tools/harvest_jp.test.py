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


def _scan(address: int, channels: Any) -> str:
    parts = " ".join(
        f"ch{name}={bank:02X}:{addr:04X}:{count}:fixed1"
        for name, (bank, addr, count) in zip((0, 1, 7), channels, strict=True)
    )
    return f"SCAN addr={address:04X} {parts}"


def _scanlen(address: int, steps: int) -> str:
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
    @unittest.skipUnless(
        harvest_jp.RETAIL.exists(), "the retail cartridge is not present"
    )  # pragma: no cover
    def test_the_harvest_builds_four_variants_and_none_of_them_twice(self) -> None:
        import hardware

        variants = harvest_jp.variants(hardware.load("romimage").dump.read(harvest_jp.RETAIL))

        self.assertEqual(sorted(variants), ["base", "both", "sa", "spc"])
        self.assertEqual(len(set(variants.values())), 4)

    @unittest.skipUnless(
        harvest_jp.RETAIL.exists(), "the retail cartridge is not present"
    )  # pragma: no cover
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


class ShellOutTest(unittest.TestCase):
    """The two steps that reach outside, with the reaching passed in."""

    @staticmethod
    def headed() -> bytes:
        rom = bytearray(0x400000)
        rom[0x7FC0:0x7FD5] = b"PROBE                "[:21]
        rom[0x7FD5], rom[0x7FD7], rom[0x7FD9] = 0x20, 0x0C, 0x01
        rom[0x7FDA], rom[0x7FDE:0x7FE0] = 0x33, (0xFFFF).to_bytes(2, "little")
        return bytes(rom)

    def test_building_an_image_asks_the_assembler_for_the_variant(self) -> None:
        asked: list[Any] = []
        rom = self.headed()

        def _record(args: Any, **rest: Any) -> Any:
            asked.append(args)
            (harvest_jp.ROOT / "asm" / args[4]).write_bytes(rom)
            return None

        harvest_jp.build_image(rom, {}, "probe", execute=_record)

        self.assertIn("build.py", asked[0][1])

    def test_the_image_it_returns_is_the_one_it_wrote(self) -> None:
        rom = self.headed()

        def _record(args: Any, **rest: Any) -> Any:
            (harvest_jp.ROOT / "asm" / args[4]).write_bytes(rom)
            return None

        found = harvest_jp.build_image(rom, {}, "probe", execute=_record)

        self.assertTrue(found.exists())

    def test_the_scratch_file_the_assembler_wrote_is_removed(self) -> None:
        rom = self.headed()
        seen: list[Path] = []

        def _record(args: Any, **rest: Any) -> Any:
            seen.append(harvest_jp.ROOT / "asm" / args[4])
            seen[-1].write_bytes(rom)
            return None

        harvest_jp.build_image(rom, {}, "probe", execute=_record)

        self.assertFalse(seen[0].exists())

    def test_scanning_writes_a_log_and_reads_it_back(self) -> None:
        harvest_jp.OUT.mkdir(parents=True, exist_ok=True)
        image = harvest_jp.OUT / "probe-image.sfc"
        image.write_bytes(b"")

        def _write(*_args: Any, stdout: Any = None, **_rest: Any) -> Any:
            stdout.write(b"one\ntwo\n")
            return None

        found = harvest_jp.scan_log(image, execute=_write)

        self.assertEqual(found, ["one", "two"])

    def test_and_asks_the_emulator_for_the_image_it_was_given(self) -> None:
        harvest_jp.OUT.mkdir(parents=True, exist_ok=True)
        image = harvest_jp.OUT / "probe-image.sfc"
        image.write_bytes(b"")
        asked: list[Any] = []

        def _record(args: Any, stdout: Any = None, **_rest: Any) -> Any:
            asked.append(args)
            stdout.write(b"")
            return None

        harvest_jp.scan_log(image, execute=_record)

        self.assertIn(str(image.relative_to(harvest_jp.ROOT)), asked[0])


class ConvergenceTest(unittest.TestCase):
    """The loop, driven with every collaborator supplied."""

    def a_run(self, wanted: list[dict[int, int]]) -> tuple[dict[int, int], list[str]]:
        said: list[str] = []
        rounds = iter(wanted)

        def _scan(_image: Any) -> list[str]:
            return []

        def _build(_cart: Any, _table: Any, _name: str) -> Path:
            return Path("nowhere.sfc")

        def _missed(_lines: list[str]) -> dict[int, int]:
            return next(rounds, {})

        original = harvest_jp.missed_streams
        harvest_jp.missed_streams = _missed
        try:
            table = harvest_jp.main(
                rom=bytes(0x400000),
                table={},
                carts={"base": bytes(0x400000)},
                build=_build,
                scan=_scan,
                say=said.append,
                rounds=4,
            )
        finally:
            harvest_jp.missed_streams = original
        return table, said

    def test_a_round_that_finds_nothing_stops_the_loop(self) -> None:
        _table, said = self.a_run([{}])

        self.assertIn("converged after 1", "\n".join(said))

    def test_a_stream_that_does_not_decode_is_reported_and_skipped(self) -> None:
        table, said = self.a_run([{0x3FFFFF: 4096}])

        self.assertEqual(table, {})
        self.assertIn("does not decode", "\n".join(said))

    def test_a_stream_that_decodes_is_taken_into_the_table(self) -> None:
        table, _said = self.a_run([{0x100000: 8}])

        self.assertEqual(table, {0x100000: 8})

    def test_the_round_cap_stops_a_loop_that_never_settles(self) -> None:
        _table, said = self.a_run([{0x100000 + n * 0x400: 8} for n in range(8)])

        self.assertNotIn("converged", "\n".join(said))


class AbsorbTest(unittest.TestCase):
    def test_a_stream_with_nothing_before_it_is_simply_recorded(self) -> None:
        table: dict[int, int] = {}

        found = harvest_jp.absorb(bytes(0x1000), table, 0x100, 16, say=lambda _l: None)

        self.assertEqual((found, table), (True, {0x100: 16}))

    def test_a_longer_length_replaces_a_shorter_one(self) -> None:
        table = {0x100: 8}

        harvest_jp.absorb(bytes(0x1000), table, 0x100, 16, say=lambda _l: None)

        self.assertEqual(table[0x100], 16)

    def test_a_shorter_length_does_not_shrink_what_is_there(self) -> None:
        table = {0x100: 16}

        harvest_jp.absorb(bytes(0x1000), table, 0x100, 8, say=lambda _l: None)

        self.assertEqual(table[0x100], 16)


class ShortenTest(unittest.TestCase):
    """Finding the longest length that still ends where the next stream starts."""

    ROM = bytes(0x400000)

    def test_a_boundary_a_length_can_reach_is_found(self) -> None:
        boundary = harvest_jp.compressed_end(self.ROM, 0x100000, 64)

        found = harvest_jp.shorten_to(self.ROM, 0x100000, 256, boundary)

        self.assertEqual(harvest_jp.compressed_end(self.ROM, 0x100000, found), boundary)

    def test_a_boundary_no_length_reaches_yields_nothing(self) -> None:
        found = harvest_jp.shorten_to(self.ROM, 0x100000, 256, 0x100000 + 1)

        self.assertIsNone(found)

    def test_the_answer_is_the_longest_that_fits_rather_than_any_of_them(self) -> None:
        boundary = harvest_jp.compressed_end(self.ROM, 0x100000, 64)
        found = harvest_jp.shorten_to(self.ROM, 0x100000, 256, boundary)

        self.assertGreater(harvest_jp.compressed_end(self.ROM, 0x100000, found + 1), boundary)


class OverlapTest(unittest.TestCase):
    """A stream that runs into the next one is trimmed, or the pair is refused."""

    ROM = bytes(0x400000)

    def test_an_earlier_stream_that_overruns_is_trimmed_back(self) -> None:
        table = {0x100000: 256}
        said: list[str] = []
        boundary = harvest_jp.compressed_end(self.ROM, 0x100000, 64)

        found = harvest_jp.absorb(self.ROM, table, boundary, 8, say=said.append)

        self.assertTrue(found)
        self.assertLess(table[0x100000], 256)
        self.assertIn("trimmed", "\n".join(said))

    def test_a_pair_that_cannot_be_separated_is_refused(self) -> None:
        table = {0x100000: 256}
        said: list[str] = []

        found = harvest_jp.absorb(self.ROM, table, 0x100000 + 1, 8, say=said.append)

        self.assertFalse(found)
        self.assertIn("cannot trim", "\n".join(said))

    def test_a_refusal_leaves_the_table_as_it_was(self) -> None:
        table = {0x100000: 256}

        harvest_jp.absorb(self.ROM, table, 0x100000 + 1, 8, say=lambda _l: None)

        self.assertEqual(table, {0x100000: 256})


class SkipTest(unittest.TestCase):
    """The three reasons a reported stream is passed over rather than absorbed."""

    ROM = bytes(0x400000)

    @staticmethod
    def short(rom: Any, source: int, length: int) -> Any:
        return harvest_jp.sdd1.decompress(rom, source, length // 2)

    def run_with(
        self,
        source: int,
        length: int,
        table: dict[int, int],
        decode: Any = harvest_jp.sdd1.decompress,
    ) -> list[str]:
        said: list[str] = []
        bank, address = source >> 16, source & 0xFFFF
        log = [
            _scan(address, ((BASE + bank, address, length), (0, 0, 0), (0, 0, 0))),
            _scanlen(address, BUDGET + 1),
        ]
        harvest_jp.main(
            rom=self.ROM,
            table=table,
            carts={"one": Path("one.sfc")},
            build=lambda _c, _t, _n: Path("image.sfc"),
            scan=lambda _i: log,
            say=said.append,
            decode=decode,
            rounds=1,
        )
        return said

    def test_a_stream_already_held_at_that_length_is_passed_over(self) -> None:
        said = self.run_with(0x191000, 64, {0x191000: 64})

        self.assertNotIn("added", "\n".join(said))

    def test_a_stream_that_decodes_to_the_wrong_length_is_passed_over(self) -> None:
        said = self.run_with(0x191000, 4096, {}, decode=self.short)

        self.assertIn("produced", "\n".join(said))

    def test_and_it_is_not_written_into_the_table(self) -> None:
        table: dict[int, int] = {}

        self.run_with(0x191000, 4096, table, decode=self.short)

        self.assertEqual(table, {})

    def test_a_stream_that_cannot_be_separated_is_passed_over(self) -> None:
        table = {0x191000: 256}
        said = self.run_with(0x191001, 8, table)

        self.assertIn("cannot trim", "\n".join(said))


if __name__ == "__main__":
    unittest.main()
