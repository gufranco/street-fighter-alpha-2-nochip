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


tour_oracle = load_module("tour_oracle", ROOT / "tools" / "tour_oracle.py")

BASE = tour_oracle.WINDOW_BASE


def _dma(bank, address, count, channel=0, fixed=1):
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


if __name__ == "__main__":
    unittest.main()
