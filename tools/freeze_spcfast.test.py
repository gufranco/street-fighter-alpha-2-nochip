import importlib.util
import tempfile
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


class ShellOutTest(unittest.TestCase):
    """The one step that reaches for the assembler, with the reaching passed in."""

    def test_it_asks_the_assembler_for_the_named_region(self) -> None:
        asked: list[Any] = []
        (freeze.ROOT / "asm" / "probe-jp.sfc").write_bytes(bytes(0x400000))

        freeze.assemble("jp", execute=lambda args, **_rest: asked.append(args))

        self.assertIn("build.py", asked[0][1])

    def test_it_returns_what_the_assembler_left_behind(self) -> None:
        (freeze.ROOT / "asm" / "probe-jp.sfc").write_bytes(bytes(0x400000))

        found = freeze.assemble("jp", execute=lambda *_a, **_k: None)

        self.assertEqual(len(found), 0x400000)


class FreezeTest(unittest.TestCase):
    """The decision the tool makes once it has both assembled images."""

    SOURCE = (
        "PATCH = (\n"
        "    (0x000000, bytes.fromhex('00')),\n"
        ")\n"
        "\n"
        "def checksum(rom):\n"
        "    return 0\n"
        "\n"
        "def applied(rom):\n"
        "    return all(rom[at : at + len(data)] == data for at, data in PATCH)\n"
        "\n"
        "def apply(rom):\n"
        "    for at, data in PATCH:\n"
        "        pass\n"
        "\n"
        "def patch_bytes():\n"
        "    return sum(len(data) for _, data in PATCH)\n"
        "\n"
        "def report(rom):\n"
        '    print(f"  patch         {patch_bytes()} bytes in {len(PATCH)} runs")\n'
    )

    class Frozen:
        def __init__(self, produces: dict[bytes, Any]) -> None:
            self.produces = produces

        def apply(self, rom: Any) -> Any:
            return self.produces[bytes(rom)]

    def setUpTarget(self) -> Path:
        target = Path(tempfile.mkdtemp()) / "spcfast.py"
        target.write_text(self.SOURCE)
        return target

    def run_with(self, images: dict[str, bytes], **rest: Any) -> tuple[int, list[str], Path]:
        said: list[str] = []
        target = self.setUpTarget()
        retail = {region: bytes(0x400000) for region in freeze.RETAIL}
        code = freeze.main(
            ["freeze", "--check"],
            build=lambda region: images[region],
            read=lambda path: retail["jp" if "jp" in path.name else "usa"],
            target=target,
            verify=lambda _n: self.Frozen({bytes(0x400000): images["jp"]}),
            say=lambda *args, **_k: said.append(str(args[0])),
            **rest,
        )
        return code, said, target

    @staticmethod
    def image(changes: dict[int, bytes]) -> bytes:
        rom = bytearray(0x400000)
        for at, data in changes.items():
            rom[at : at + len(data)] = data
        return bytes(rom)

    def test_two_regions_that_differ_only_in_shared_runs_are_frozen(self) -> None:
        same = self.image({0x1000: b"\xaa\xbb"})

        code, said, _ = self.run_with({"jp": same, "usa": same})

        self.assertEqual((code, "1 runs" in "\n".join(said)), (0, True))

    def test_the_shared_table_is_written_into_the_target(self) -> None:
        same = self.image({0x1000: b"\xaa\xbb"})
        said: list[str] = []
        target = self.setUpTarget()
        retail = bytes(0x400000)

        freeze.main(
            ["freeze"],
            build=lambda _r: same,
            read=lambda _p: retail,
            target=target,
            verify=lambda _n: self.Frozen({retail: same}),
            say=lambda *args, **_k: said.append(str(args[0])),
        )

        self.assertIn("aabb", target.read_text())

    def test_a_check_run_leaves_the_target_as_it_was(self) -> None:
        same = self.image({0x1000: b"\xaa\xbb"})

        _, _, target = self.run_with({"jp": same, "usa": same})

        self.assertEqual(target.read_text(), self.SOURCE)

    def test_two_region_specific_runs_are_refused(self) -> None:
        jp = self.image({0x1000: b"\xaa", 0x2000: b"\xbb", 0x3000: b"\xcc"})
        usa = self.image({0x1000: b"\xaa"})

        code, said, _ = self.run_with({"jp": jp, "usa": usa})

        self.assertEqual((code, "at most one" in "\n".join(said)), (1, True))

    def test_one_region_specific_run_carrying_different_bytes_is_refused(self) -> None:
        jp = self.image({0x1000: b"\xaa", 0x2000: b"\xbb"})
        usa = self.image({0x1000: b"\xaa", 0x2000: b"\xcc"})

        code, said, _ = self.run_with({"jp": jp, "usa": usa})

        self.assertEqual((code, "identical bytes" in "\n".join(said)), (1, True))

    def test_one_region_specific_run_carrying_the_same_bytes_is_frozen(self) -> None:
        jp = self.image({0x1000: b"\xaa", 0x2000: b"\xbb"})
        usa = self.image({0x1000: b"\xaa", 0x4000: b"\xbb"})
        said: list[str] = []
        target = self.setUpTarget()
        retail = {"jp": bytes(0x400000), "usa": self.image({0x007FDC: b"\x01"})}

        def _read(path: Path) -> bytes:
            return retail["jp" if "jp" in path.name else "usa"]

        code = freeze.main(
            ["freeze", "--check"],
            build=lambda region: jp if region == "jp" else usa,
            read=_read,
            target=target,
            verify=lambda _n: self.Frozen({retail["jp"]: jp, retail["usa"]: usa}),
            say=lambda *args, **_k: said.append(str(args[0])),
        )

        self.assertEqual((code, "2 runs" in "\n".join(said)), (0, True))

    def test_a_table_that_does_not_reproduce_the_assembler_is_refused(self) -> None:
        same = self.image({0x1000: b"\xaa\xbb"})
        said: list[str] = []

        code = freeze.main(
            ["freeze", "--check"],
            build=lambda _r: same,
            read=lambda _p: bytes(0x400000),
            target=self.setUpTarget(),
            verify=lambda _n: self.Frozen({bytes(0x400000): self.image({0x1000: b"\x00"})}),
            say=lambda *args, **_k: said.append(str(args[0])),
        )

        self.assertEqual((code, "does not reproduce" in "\n".join(said)), (1, True))


class LoadTest(unittest.TestCase):
    """Reading a sibling module back after the table has been rewritten."""

    def test_it_returns_the_module_the_name_points_at(self) -> None:
        found = freeze.load("spcfast")

        self.assertTrue(hasattr(found, "PATCH"))


class TrailingRunTest(unittest.TestCase):
    """A run that reaches the last byte, where there is no next byte to close it."""

    def test_a_change_at_the_final_byte_is_still_recorded(self) -> None:
        before = bytes(16)
        after = bytes(15) + b"\xaa"

        self.assertEqual(freeze.differing_runs(before, after), [(15, b"\xaa")])

    def test_a_run_reaching_the_end_carries_every_byte_of_it(self) -> None:
        before = bytes(16)
        after = bytes(13) + b"\xaa\xbb\xcc"

        self.assertEqual(freeze.differing_runs(before, after), [(13, b"\xaa\xbb\xcc")])


class PlumbingTest(unittest.TestCase):
    """Adding the frame hook plumbing, which must not be added twice."""

    def test_a_source_that_already_carries_it_is_left_alone(self) -> None:
        source = "FRAME_HOOK_SITES = (1,)\ndef checksum(rom):\n    return 0\n"

        self.assertEqual(freeze.add_plumbing(source), source)

    def test_a_source_without_it_gains_it(self) -> None:
        source = "def checksum(rom):\n    return 0\n"

        self.assertIn("FRAME_HOOK_SITES", freeze.add_plumbing(source))


if __name__ == "__main__":
    unittest.main(verbosity=2)
