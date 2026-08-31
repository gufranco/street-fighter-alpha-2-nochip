import importlib.util
import unittest
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parent.parent


def load_module(name: str, where: Path) -> Any:
    spec = importlib.util.spec_from_file_location(name, where / f"{name}.py")
    assert spec is not None and spec.loader is not None, "no loader for that path"
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


freeze = load_module("freeze_spcfast", ROOT / "tools")


class DifferingRunsTest(unittest.TestCase):
    def test_identical_images_produce_no_runs(self) -> None:
        image = bytes(64)

        self.assertEqual(freeze.differing_runs(image, image), [])

    def test_one_changed_byte_is_one_run(self) -> None:
        before = bytes(64)
        after = bytearray(before)
        after[10] = 0xFF

        self.assertEqual(freeze.differing_runs(before, bytes(after)), [(10, b"\xff")])

    def test_adjacent_changes_join_into_one_run(self) -> None:
        before = bytes(64)
        after = bytearray(before)
        after[10:13] = b"\x01\x02\x03"

        self.assertEqual(freeze.differing_runs(before, bytes(after)), [(10, b"\x01\x02\x03")])

    def test_a_gap_splits_the_runs(self) -> None:
        before = bytes(64)
        after = bytearray(before)
        after[10] = 0x01
        after[12] = 0x02

        self.assertEqual(
            freeze.differing_runs(before, bytes(after)), [(10, b"\x01"), (12, b"\x02")]
        )

    def test_the_checksum_field_is_never_recorded(self) -> None:
        before = bytes(0x8000)
        after = bytearray(before)
        for index in freeze.CHECKSUM_FIELD:
            after[index] = 0xAB

        self.assertEqual(freeze.differing_runs(before, bytes(after)), [])

    def test_a_run_touching_the_checksum_field_stops_at_it(self) -> None:
        before = bytes(0x8000)
        after = bytearray(before)
        after[0x007FDA] = 0x01
        after[0x007FDB] = 0x02
        for index in freeze.CHECKSUM_FIELD:
            after[index] = 0xAB

        self.assertEqual(freeze.differing_runs(before, bytes(after)), [(0x007FDA, b"\x01\x02")])


class RenderTest(unittest.TestCase):
    def test_a_short_run_stays_on_one_line(self) -> None:
        rendered = freeze.render([(0x070222, bytes.fromhex("eaea"))])

        self.assertIn('(0x070222, bytes.fromhex("eaea")),', rendered)

    def test_a_long_run_is_wrapped(self) -> None:
        rendered = freeze.render([(0x0704EB, bytes(200))])

        self.assertIn("bytes.fromhex(", rendered)
        self.assertTrue(all(len(line) <= 100 for line in rendered.splitlines()))

    def test_the_rendered_table_is_valid_python_and_round_trips(self) -> None:
        runs = [(0x070222, bytes.fromhex("eaeaeaea")), (0x0704EB, bytes(range(120)))]
        namespace: dict[str, Any] = {}

        exec(freeze.render(runs), namespace)

        self.assertEqual(list(namespace["PATCH"]), runs)


if __name__ == "__main__":
    unittest.main(verbosity=2)
