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


verify_streams = load_module("verify_streams", ROOT / "tools" / "verify_streams.py")


class BatchTest(unittest.TestCase):
    def test_nothing_to_check_is_no_batches(self) -> None:
        self.assertEqual(verify_streams.batches([], size=10), [])

    def test_fewer_cases_than_a_batch_is_one_batch(self) -> None:
        self.assertEqual(verify_streams.batches([1, 2, 3], size=10), [[1, 2, 3]])

    def test_an_exact_multiple_leaves_no_remainder(self) -> None:
        self.assertEqual(verify_streams.batches([1, 2, 3, 4], size=2), [[1, 2], [3, 4]])

    def test_a_remainder_becomes_a_shorter_last_batch(self) -> None:
        self.assertEqual(verify_streams.batches([1, 2, 3], size=2), [[1, 2], [3]])

    def test_every_case_appears_exactly_once(self) -> None:
        cases = list(range(1000))

        flattened = [case for batch in verify_streams.batches(cases, size=7) for case in batch]

        self.assertEqual(flattened, cases)

    def test_no_batch_is_longer_than_the_size_asked_for(self) -> None:
        for batch in verify_streams.batches(list(range(1000)), size=7):
            self.assertLessEqual(len(batch), 7)

    def test_the_default_size_is_the_one_the_module_names(self) -> None:
        cases = list(range(verify_streams.BATCH + 1))

        self.assertEqual(len(verify_streams.batches(cases)), 2)


class RegionTest(unittest.TestCase):
    def test_both_regions_are_covered(self) -> None:
        self.assertEqual(sorted(verify_streams.SETS), ["jp", "usa"])

    def test_each_region_names_a_different_retail_cartridge(self) -> None:
        first, second = (retail for retail, _ in verify_streams.SETS.values())

        self.assertNotEqual(first, second)

    def test_each_region_supplies_a_non_empty_set_of_streams(self) -> None:
        for region, (_, cases_for) in verify_streams.SETS.items():
            self.assertGreater(len(cases_for()), 0, region)

    def test_the_two_regions_do_not_share_a_stream_table(self) -> None:
        jp = verify_streams.SETS["jp"][1]()
        usa = verify_streams.SETS["usa"][1]()

        self.assertNotEqual(set(jp), set(usa))

    def test_every_case_is_a_source_and_a_length(self) -> None:
        for region, (_, cases_for) in verify_streams.SETS.items():
            for source, length in cases_for()[:50]:
                self.assertGreaterEqual(source, 0, region)
                self.assertGreater(length, 0, region)


class VerifyTest(unittest.TestCase):
    """Batching the work and reporting progress while it happens."""

    def run_on(self, mismatched: list[Any]) -> tuple[list[Any], list[Any], list[str]]:
        said: list[str] = []
        cases, mismatches = verify_streams.verify(
            "jp",
            read=lambda _p: bytes(0x400000),
            compare=lambda _rom, chunk: [one for one in chunk if one in mismatched],
            say=said.append,
        )
        return cases, mismatches, said

    def test_a_region_where_everything_agrees_reports_no_mismatches(self) -> None:
        _, mismatches, _ = self.run_on([])

        self.assertEqual(mismatches, [])

    def test_it_reports_progress_once_per_batch(self) -> None:
        cases, _, said = self.run_on([])

        self.assertEqual(len(said), len(verify_streams.batches(cases)))

    def test_the_running_count_reaches_every_case(self) -> None:
        cases, _, said = self.run_on([])

        self.assertIn(f"{len(cases):5d}/{len(cases)}", said[-1])

    def test_a_case_the_reference_disagrees_on_is_carried_out(self) -> None:
        first = list(verify_streams.SETS["jp"][1]())[0]

        _, mismatches, _ = self.run_on([first])

        self.assertEqual(mismatches, [first])


class CommandTest(unittest.TestCase):
    """The command line, driven without a container."""

    def run_with(self, argv: list[str], **rest: Any) -> tuple[int, list[str]]:
        said: list[str] = []
        code = verify_streams.main(
            argv,
            say=lambda *args, **_k: said.append(str(args[0])),
            **{"build": lambda: 0, "check": lambda _r: ([1, 2, 3], []), **rest},
        )
        return code, said

    def test_a_build_that_fails_stops_the_run(self) -> None:
        code, said = self.run_with(["verify_streams.py"], build=lambda: 1)

        self.assertEqual((code, "failed to build" in said[0]), (1, True))

    def test_a_region_where_everything_agrees_passes(self) -> None:
        code, said = self.run_with(["verify_streams.py", "jp"])

        self.assertEqual((code, "all 3 streams identical" in said[0]), (0, True))

    def test_no_region_named_means_every_region(self) -> None:
        _, said = self.run_with(["verify_streams.py"])

        self.assertEqual(len(said), len(verify_streams.SETS))

    def test_a_region_with_a_mismatch_fails_and_names_it(self) -> None:
        code, said = self.run_with(
            ["verify_streams.py", "jp"], check=lambda _r: ([1], [(0x100000, 16, "wrong")])
        )

        self.assertEqual((code, "MISMATCH" in said[0]), (1, True))

    def test_only_the_first_twenty_mismatches_are_listed(self) -> None:
        many = [(n, 16, "wrong") for n in range(30)]

        _, said = self.run_with(["verify_streams.py", "jp"], check=lambda _r: ([1], many))

        self.assertEqual(len([one for one in said if "MISMATCH" in one]), 20)


if __name__ == "__main__":
    unittest.main()
