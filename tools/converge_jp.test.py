import importlib.util
import tempfile
import unittest
from pathlib import Path
from typing import Any, override

ROOT = Path(__file__).resolve().parent.parent


def load_module(name: str, where: Path = ROOT) -> Any:
    spec = importlib.util.spec_from_file_location(name, where / f"{name}.py")
    assert spec is not None and spec.loader is not None, "no loader for that path"
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


converge = load_module("converge_jp", ROOT / "tools")


class ScanPatternTest(unittest.TestCase):
    LINE = "SCAN addr=104C ch0=D9:104C:8192:fixed1 ch1=C0:D4FE:0:fixed0 ch7=4E:AA28:0:fixed0"

    def test_a_scan_line_is_recognised(self) -> None:
        self.assertIsNotNone(converge.SCAN.match(self.LINE))

    def test_the_requested_address_is_the_first_field(self) -> None:
        self.assertEqual(converge.SCAN.match(self.LINE).group(1), "104C")

    def test_a_line_that_is_not_a_scan_is_ignored(self) -> None:
        self.assertIsNone(converge.SCAN.match("SCANLEN addr=104C steps=12"))


class WindowTest(unittest.TestCase):
    def test_the_window_starts_at_bank_c0(self) -> None:
        self.assertEqual(converge.WINDOW_BASE, 0xC0)

    def test_the_scan_budget_matches_the_gate(self) -> None:
        gate = load_module("gate")

        self.assertEqual(converge.SCAN_BUDGET, gate.SCAN_BUDGET)


class PassTest(unittest.TestCase):
    def test_every_pass_names_a_driver_and_a_frame_count(self) -> None:
        for name, extra, frames in converge.PASSES:
            self.assertTrue(name)
            self.assertTrue(any(argument.startswith("SF") for argument in extra))
            self.assertGreater(frames, 0)

    def test_the_passes_are_not_all_the_same_driver(self) -> None:
        drivers = {tuple(extra) for _, extra, _ in converge.PASSES}

        self.assertGreater(len(drivers), 1)


def _scan(address: int, channels: Any) -> str:
    parts = " ".join(
        f"ch{name}={bank:02X}:{addr:04X}:{count}:fixed1"
        for name, (bank, addr, count) in zip((0, 1, 7), channels, strict=True)
    )
    return f"SCAN addr={address:04X} {parts}"


class TableTest(unittest.TestCase):
    """The table on disk, which is the only state that survives a round."""

    @override
    def setUp(self) -> None:
        self.path = Path(tempfile.mkdtemp()) / "table.txt"

    def test_a_written_table_reads_back_the_same(self) -> None:
        converge.write_table({0x191000: 832, 0x100000: 16}, self.path)

        self.assertEqual(converge.read_table(self.path), {0x191000: 832, 0x100000: 16})

    def test_it_is_written_in_source_order_so_the_diff_stays_readable(self) -> None:
        converge.write_table({0x191000: 832, 0x100000: 16}, self.path)

        self.assertEqual(self.path.read_text().splitlines()[0].split()[0], str(0x100000))

    def test_an_empty_table_round_trips_rather_than_failing(self) -> None:
        converge.write_table({}, self.path)

        self.assertEqual(converge.read_table(self.path), {})


class RequestTest(unittest.TestCase):
    """Reading the streams a pass asked for out of the emulator log."""

    class Result:
        def __init__(self, out: str) -> None:
            self.stdout, self.stderr = out, ""

    def run_on(self, lines: list[str]) -> dict[int, int]:
        found: dict[int, int] = converge.requests_of(
            converge.ROOT / "image.sfc",
            [],
            10,
            execute=lambda *_a, **_k: self.Result("\n".join(lines)),
        )
        return found

    def test_a_pass_that_asked_for_a_stream_names_it(self) -> None:
        line = _scan(0x104C, ((converge.WINDOW_BASE + 0x19, 0x104C, 832), (0, 0, 0), (0, 0, 0)))

        self.assertEqual(self.run_on([line]), {0x19104C: 832})

    def test_a_pass_that_asked_for_nothing_names_nothing(self) -> None:
        self.assertEqual(self.run_on(["nothing here"]), {})

    def test_a_channel_below_the_window_is_not_a_stream(self) -> None:
        line = _scan(0x104C, ((0x00, 0x104C, 832), (0, 0, 0), (0, 0, 0)))

        self.assertEqual(self.run_on([line]), {})

    def test_a_channel_at_a_different_address_is_not_this_request(self) -> None:
        line = _scan(0x104C, ((converge.WINDOW_BASE + 0x19, 0x2000, 832), (0, 0, 0), (0, 0, 0)))

        self.assertEqual(self.run_on([line]), {})

    def test_a_zero_length_channel_is_not_a_stream(self) -> None:
        line = _scan(0x104C, ((converge.WINDOW_BASE + 0x19, 0x104C, 0), (0, 0, 0), (0, 0, 0)))

        self.assertEqual(self.run_on([line]), {})

    def test_the_longest_of_two_reports_for_one_source_wins(self) -> None:
        short = _scan(0x104C, ((converge.WINDOW_BASE + 0x19, 0x104C, 16), (0, 0, 0), (0, 0, 0)))
        long = _scan(0x104C, ((converge.WINDOW_BASE + 0x19, 0x104C, 832), (0, 0, 0), (0, 0, 0)))

        self.assertEqual(self.run_on([long, short]), {0x19104C: 832})

    def test_it_reads_the_error_stream_too_because_the_driver_writes_there(self) -> None:
        line = _scan(0x104C, ((converge.WINDOW_BASE + 0x19, 0x104C, 832), (0, 0, 0), (0, 0, 0)))

        class OnStderr:
            stdout = ""
            stderr = line

        found = converge.requests_of(
            converge.ROOT / "image.sfc", [], 10, execute=lambda *_a, **_k: OnStderr()
        )

        self.assertEqual(found, {0x19104C: 832})


class BuildTest(unittest.TestCase):
    """Assembling the three variants, with the assembler passed in."""

    @staticmethod
    def headed() -> bytes:
        rom = bytearray(0x400000)
        rom[0x7FC0:0x7FD5] = b"PROBE                "[:21]
        rom[0x7FD5], rom[0x7FD7], rom[0x7FD9] = 0x20, 0x0C, 0x01
        rom[0x7FDA], rom[0x7FDE:0x7FE0] = 0x33, (0xFFFF).to_bytes(2, "little")
        return bytes(rom)

    def built(self) -> Any:
        rom = self.headed()

        def _record(args: Any, **_rest: Any) -> Any:
            (converge.ROOT / "asm" / args[4]).write_bytes(rom)
            return None

        return converge.build_variants(
            {}, execute=_record, carts={"base": rom, "spc": rom, "both": rom}
        )

    def test_one_image_is_built_for_each_variant(self) -> None:
        self.assertEqual(len(self.built()), 3)

    def test_every_image_it_names_exists_on_disk(self) -> None:
        self.assertTrue(all(one.exists() for one in self.built()))

    def test_the_variants_are_distinct_cartridges(self) -> None:
        self.assertEqual(len({one.name for one in self.built()}), 3)


class ConvergenceTest(unittest.TestCase):
    """The rule that decides when the table is complete."""

    ROM = bytes(0x400000)

    def run_with(
        self, asked: list[dict[int, int]], **rest: Any
    ) -> tuple[int, list[str], dict[int, int]]:
        said: list[str] = []
        table: dict[int, int] = {}
        rounds = iter(asked)

        def _request(*_args: Any) -> dict[int, int]:
            return next(rounds, {})

        code = converge.main(
            retail=self.ROM,
            build=lambda _t: [Path("one.sfc")],
            request=_request,
            read=lambda: dict(table),
            write=table.update,
            say=said.append,
            **rest,
        )
        return code, said, table

    def test_a_round_that_finds_nothing_reports_convergence(self) -> None:
        code, said, _ = self.run_with([{}])

        self.assertEqual((code, "converged" in "\n".join(said)), (0, True))

    def test_a_stream_the_table_wants_is_added(self) -> None:
        _, _, table = self.run_with([{0x191000: 832}])

        self.assertEqual(table, {0x191000: 832})

    def test_a_run_that_never_settles_says_so_through_its_status(self) -> None:
        said: list[str] = []
        table: dict[int, int] = {}
        fresh = iter(range(1, 500))

        code = converge.main(
            retail=self.ROM,
            build=lambda _t: [Path("one.sfc")],
            request=lambda *_a: {0x191000 + next(fresh) * 0x1000: 16},
            read=lambda: dict(table),
            write=table.update,
            say=said.append,
            rounds=2,
        )

        self.assertEqual(code, 1)

    def test_a_stream_that_does_not_decode_is_skipped(self) -> None:
        def _raise(*_args: Any) -> Any:
            raise converge.sdd1.TruncatedStream("nope")

        _, said, table = self.run_with([{0x191000: 832}], decode=_raise)

        self.assertEqual((table, "does not decode" in "\n".join(said)), ({}, True))

    def test_a_stream_that_decodes_short_is_skipped(self) -> None:
        def _short(rom: Any, source: int, length: int) -> Any:
            return converge.sdd1.decompress(rom, source, length // 2)

        _, said, table = self.run_with([{0x191000: 832}], decode=_short)

        self.assertEqual((table, "produced" in "\n".join(said)), ({}, True))

    def test_a_stream_already_in_the_table_is_not_a_candidate(self) -> None:
        said: list[str] = []
        table = {0x191000: 832}

        converge.main(
            retail=self.ROM,
            build=lambda _t: [Path("one.sfc")],
            request=lambda *_a: {0x191000: 832},
            read=lambda: dict(table),
            write=lambda _t: None,
            say=said.append,
        )

        self.assertIn("0 candidates", "\n".join(said))


if __name__ == "__main__":
    unittest.main(verbosity=2)
