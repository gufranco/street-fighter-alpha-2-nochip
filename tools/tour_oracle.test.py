import importlib.util
import sys
import tempfile
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


tour_oracle = load_module("tour_oracle", ROOT / "tools" / "tour_oracle.py")

BASE = tour_oracle.WINDOW_BASE


def _dma(bank: int, address: int, count: int, channel: int = 0, fixed: int = 1) -> str:
    return f"DMA ch={channel} src={bank:02X}:{address:04X} n={count} b=80 fixed={fixed}"


class RequestTest(unittest.TestCase):
    def test_a_fixed_source_inside_the_window_is_a_request(self) -> None:
        found = tour_oracle.requests([_dma(BASE + 0x19, 0x104C, 832)])

        self.assertEqual(found, {0x19104C: 832})

    def test_a_source_that_advances_is_not_a_decompression(self) -> None:
        self.assertEqual(tour_oracle.requests([_dma(BASE + 0x19, 0x104C, 832, fixed=0)]), {})

    def test_a_source_below_the_window_is_not_cartridge_data(self) -> None:
        self.assertEqual(tour_oracle.requests([_dma(0x7E, 0x104C, 832)]), {})

    def test_the_largest_length_asked_for_from_one_source_wins(self) -> None:
        found = tour_oracle.requests(
            [_dma(BASE + 0x19, 0x104C, 832), _dma(BASE + 0x19, 0x104C, 2048)]
        )

        self.assertEqual(found, {0x19104C: 2048})

    def test_a_later_smaller_request_does_not_shrink_the_answer(self) -> None:
        found = tour_oracle.requests(
            [_dma(BASE + 0x19, 0x104C, 2048), _dma(BASE + 0x19, 0x104C, 832)]
        )

        self.assertEqual(found, {0x19104C: 2048})

    def test_two_sources_are_two_requests(self) -> None:
        found = tour_oracle.requests(
            [_dma(BASE + 0x19, 0x104C, 832), _dma(BASE + 0x1A, 0x2000, 512)]
        )

        self.assertEqual(found, {0x19104C: 832, 0x1A2000: 512})

    def test_any_channel_can_carry_a_request(self) -> None:
        found = tour_oracle.requests([_dma(BASE + 0x19, 0x104C, 832, channel=7)])

        self.assertEqual(found, {0x19104C: 832})

    def test_the_first_bank_of_the_window_is_the_first_bank_of_the_file(self) -> None:
        found = tour_oracle.requests([_dma(BASE, 0x8000, 64)])

        self.assertEqual(found, {0x008000: 64})

    def test_lines_that_are_not_transfers_are_ignored(self) -> None:
        found = tour_oracle.requests(["RESULT load=ok frames=1", "", _dma(BASE, 0x8000, 64)])

        self.assertEqual(found, {0x008000: 64})

    def test_an_empty_log_asks_for_nothing(self) -> None:
        self.assertEqual(tour_oracle.requests([]), {})


class PassTest(unittest.TestCase):
    def test_every_pass_names_itself_once(self) -> None:
        names = [name for name, _, _ in tour_oracle.PASSES]

        self.assertEqual(len(names), len(set(names)))

    def test_the_frame_count_of_each_pass_is_the_budget_times_the_roster(self) -> None:
        for name, extra, frames in tour_oracle.PASSES:
            budget = next(
                int(entry.split("=")[1]) for entry in extra if entry.startswith("SFTOURBUDGET=")
            )

            self.assertEqual(frames % budget, 0, name)

    def test_at_least_one_pass_enters_fights(self) -> None:
        self.assertTrue(any("SFTOURCONFIRM=1" in extra for _, extra, _ in tour_oracle.PASSES))

    def test_the_passes_do_not_all_use_the_same_budget(self) -> None:
        budgets = {
            entry for _, extra, _ in tour_oracle.PASSES for entry in extra if "BUDGET" in entry
        }

        self.assertGreater(len(budgets), 1)


class OracleTest(unittest.TestCase):
    def test_the_oracle_is_a_cartridge_form_image(self) -> None:
        self.assertTrue(tour_oracle.ORACLE.endswith("-cart.sfc"))

    def test_the_oracle_carries_no_skip_patch(self) -> None:
        """A harvest has to see every request, including the repeated ones.

        The skip patch exists to avoid an upload the cartridge would otherwise
        repeat. An oracle carrying it would record fewer requests than the
        hardware makes, and every table built from that oracle would be short by
        exactly the requests the patch suppressed.
        """
        self.assertNotIn("repeat", tour_oracle.ORACLE)
        self.assertNotIn("both", tour_oracle.ORACLE)

    def test_the_window_base_is_the_one_every_tool_here_uses(self) -> None:
        harvest_jp = load_module("harvest_jp", ROOT / "tools" / "harvest_jp.py")

        self.assertEqual(tour_oracle.WINDOW_BASE, harvest_jp.WINDOW_BASE)


class ShellOutTest(unittest.TestCase):
    """The one step that reaches for a container, with the reaching passed in."""

    def test_it_reads_back_what_the_pass_wrote_to_the_log(self) -> None:
        line = "DMA ch=0 src=D9:104C n=832 b=18 fixed=1\n"

        def _write(_command: Any, stdout: Any = None, **_rest: Any) -> Any:
            stdout.write(line.encode())
            return None

        found = tour_oracle.run("probe", [], 10, execute=_write)

        self.assertEqual(found, {0x19104C: 832})

    def test_a_pass_that_logged_nothing_names_nothing(self) -> None:
        found = tour_oracle.run("probe", [], 10, execute=lambda *_a, **_k: None)

        self.assertEqual(found, {})

    def test_the_pass_is_told_which_cartridge_and_how_many_frames(self) -> None:
        asked: list[Any] = []

        def _record(command: Any, **_rest: Any) -> Any:
            asked.append(command)
            return None

        tour_oracle.run("probe", ["-e", "SFPROBE=1"], 4242, execute=_record)

        self.assertIn("4242", asked[0])


class CommandTest(unittest.TestCase):
    """The rule that decides what the tour adds to the table."""

    ROM = bytes(0x400000)

    def run_with(self, seen: dict[int, int], held: dict[int, int], **rest: Any) -> dict[int, int]:
        where = Path(tempfile.mkdtemp())
        table_path = where / "table.txt"
        table_path.write_text("\n".join(f"{s} {n}" for s, n in held.items()) + "\n")
        tour_oracle.main(
            rom=self.ROM,
            table_path=table_path,
            seen_path=where / "seen.txt",
            tour=lambda *_a: seen,
            say=lambda _l: None,
            **rest,
        )
        return {
            int(line.split()[0]): int(line.split()[1])
            for line in table_path.read_text().splitlines()
            if line.strip()
        }

    def test_a_stream_the_table_does_not_hold_is_added(self) -> None:
        self.assertEqual(self.run_with({0x191000: 832}, {}), {0x191000: 832})

    def test_a_stream_held_shorter_than_the_tour_saw_is_grown(self) -> None:
        found = self.run_with({0x191000: 832}, {0x191000: 16})

        self.assertEqual(found, {0x191000: 832})

    def test_a_stream_already_held_at_that_length_is_left_alone(self) -> None:
        found = self.run_with({0x191000: 832}, {0x191000: 832})

        self.assertEqual(found, {0x191000: 832})

    def test_a_stream_held_longer_than_the_tour_saw_is_not_shortened(self) -> None:
        found = self.run_with({0x191000: 16}, {0x191000: 832})

        self.assertEqual(found, {0x191000: 832})

    def test_a_stream_that_does_not_decode_is_skipped(self) -> None:
        def _raise(*_args: Any) -> Any:
            raise tour_oracle.sdd1.TruncatedStream("nope")

        self.assertEqual(self.run_with({0x191000: 832}, {}, decode=_raise), {})

    def test_a_stream_that_decodes_short_is_skipped(self) -> None:
        def _short(rom: Any, source: int, length: int) -> Any:
            return tour_oracle.sdd1.decompress(rom, source, length // 2)

        self.assertEqual(self.run_with({0x191000: 832}, {}, decode=_short), {})

    def test_what_the_tour_saw_is_written_out_beside_the_table(self) -> None:
        where = Path(tempfile.mkdtemp())
        table_path = where / "table.txt"
        table_path.write_text("")
        seen_path = where / "seen.txt"

        tour_oracle.main(
            rom=self.ROM,
            table_path=table_path,
            seen_path=seen_path,
            tour=lambda *_a: {0x191000: 832},
            say=lambda _l: None,
        )

        self.assertEqual(seen_path.read_text().strip(), "1642496 832")

    def test_the_report_counts_what_it_added(self) -> None:
        said: list[str] = []
        where = Path(tempfile.mkdtemp())
        table_path = where / "table.txt"
        table_path.write_text("")

        tour_oracle.main(
            rom=self.ROM,
            table_path=table_path,
            seen_path=where / "seen.txt",
            tour=lambda *_a: {0x191000: 832},
            say=said.append,
        )

        self.assertIn("1 added", said[-1])


if __name__ == "__main__":
    unittest.main()
