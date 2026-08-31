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


if __name__ == "__main__":
    unittest.main()
