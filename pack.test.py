import contextlib
import importlib.util
import shutil
import subprocess
import tempfile
import unittest
from collections.abc import Iterator
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parent


def load_module(name: str) -> Any:
    spec = importlib.util.spec_from_file_location(name, ROOT / f"{name}.py")
    assert spec is not None and spec.loader is not None, "no loader for that path"
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


pack = load_module("pack")
version = load_module("version")


class RegionTest(unittest.TestCase):
    def test_both_cartridges_are_covered(self) -> None:
        self.assertEqual(sorted(pack.REGIONS), ["jp", "usa"])

    def test_each_region_names_its_retail_dump_and_its_patch(self) -> None:
        for region in pack.REGIONS.values():
            self.assertTrue(region.retail.name.endswith(".sfc"))
            self.assertTrue(region.bypass.endswith(".asm"))

    def test_the_two_regions_use_different_sources(self) -> None:
        self.assertNotEqual(pack.REGIONS["usa"].retail, pack.REGIONS["jp"].retail)


class NameTest(unittest.TestCase):
    def test_the_output_carries_the_region_and_the_version(self) -> None:
        name = pack.output_name("usa", "1.4.2")

        self.assertEqual(name, "sfa2-usa-nochip-v1.4.2.sfc")

    def test_the_japanese_output_uses_its_own_title(self) -> None:
        self.assertEqual(pack.output_name("jp", "1.4.2"), "sfz2-jp-nochip-v1.4.2.sfc")

    def test_an_unreleased_build_says_so(self) -> None:
        self.assertIn("-dev", pack.output_name("usa", version.UNRELEASED))

    def test_an_unknown_region_is_rejected(self) -> None:
        with self.assertRaises(KeyError):
            pack.output_name("eu", "1.0.0")


class ManifestTest(unittest.TestCase):
    def test_a_manifest_line_pairs_the_digest_with_the_name(self) -> None:
        line = pack.manifest_line("name.sfc", b"abc")

        self.assertTrue(line.endswith("  name.sfc"))
        self.assertEqual(len(line.split("  ")[0]), 64)

    def test_the_digest_is_of_the_image_and_not_the_name(self) -> None:
        first = pack.manifest_line("a.sfc", b"same")
        second = pack.manifest_line("b.sfc", b"same")

        self.assertEqual(first.split("  ")[0], second.split("  ")[0])


class AssemblyFailureTest(unittest.TestCase):
    @staticmethod
    def result(returncode: int = 1, stdout: str = "", stderr: str = "") -> Any:
        return subprocess.CompletedProcess(
            args=["python3", "build.py"], returncode=returncode, stdout=stdout, stderr=stderr
        )

    def test_the_message_names_the_region_and_the_exit_code(self) -> None:
        message = pack.assembly_failure("jp", self.result(returncode=3))

        self.assertIn("jp", message)
        self.assertIn("3", message)

    def test_what_the_assembler_said_is_carried_and_not_discarded(self) -> None:
        message = pack.assembly_failure(
            "usa", self.result(stdout="staged the rom", stderr="docker is not on PATH")
        )

        self.assertIn("docker is not on PATH", message)
        self.assertIn("staged the rom", message)

    def test_an_empty_stream_adds_no_heading(self) -> None:
        message = pack.assembly_failure("jp", self.result(stderr="only this"))

        self.assertNotIn("stdout", message)
        self.assertIn("stderr", message)

    def test_the_message_points_at_the_prerequisite(self) -> None:
        message = pack.assembly_failure("jp", self.result())

        self.assertIn("docker --version", message)

    def test_a_failure_is_raised_as_its_own_kind_of_error(self) -> None:
        self.assertTrue(issubclass(pack.AssemblyFailed, Exception))


class LoadingTest(unittest.TestCase):
    """A tree with no submodules says so rather than failing on an import."""

    def test_the_model_it_loads_is_the_image_handling_one(self) -> None:
        self.assertTrue(hasattr(pack.load_images(), "dump"))

    def test_a_tree_without_it_stops_with_what_the_loader_said(self) -> None:
        def absent(_name: str) -> Any:
            raise pack.hardware.ModelMissing("run git submodule update")

        with self.assertRaises(SystemExit) as raised:
            pack.load_images(absent)

        self.assertIn("git submodule update", str(raised.exception))


class EntriesTest(unittest.TestCase):
    def test_the_usa_table_becomes_entries(self) -> None:
        self.assertTrue(pack.entries_for("usa"))

    def test_and_the_japanese_one_becomes_different_entries(self) -> None:
        self.assertNotEqual(pack.entries_for("jp"), pack.entries_for("usa"))


class ShellingOutTest(unittest.TestCase):
    def test_the_real_path_runs_the_command_it_was_given(self) -> None:
        self.assertEqual(pack._shell_out(["true"]).returncode, 0)


class AssembleTest(unittest.TestCase):
    """What assembling a bypass patch shells out to, checked without Docker."""

    def test_the_command_names_the_patch_and_where_the_output_goes(self) -> None:
        found = pack.assemble_command("usa", pack.ROOT / "dist" / "x.sfc", "usa-bypass.sfc")

        self.assertIn("build.py", found)
        self.assertIn("usa-bypass.sfc", found)

    def _under_root(self) -> Path:
        where = Path(tempfile.mkdtemp(dir=pack.ROOT))
        self.addCleanup(shutil.rmtree, where, True)
        return where

    def test_an_assembler_that_fails_carries_what_it_said(self) -> None:
        failed = type("Done", (), {"returncode": 1, "stdout": "out", "stderr": "asar said no"})

        with self.assertRaises(pack.AssemblyFailed) as raised:
            pack.assemble_bypass("usa", b"\x00" * 16, self._under_root(), lambda _a: failed)

        self.assertIn("asar said no", str(raised.exception))

    def test_and_says_that_docker_has_to_be_running(self) -> None:
        failed = type("Done", (), {"returncode": 1, "stdout": "", "stderr": ""})

        with self.assertRaises(pack.AssemblyFailed) as raised:
            pack.assemble_bypass("usa", b"\x00" * 16, self._under_root(), lambda _a: failed)

        self.assertIn("docker --version", str(raised.exception))

    def test_an_assembler_that_succeeds_hands_back_the_image_it_wrote(self) -> None:
        done = type("Done", (), {"returncode": 0, "stdout": "", "stderr": ""})
        produced = pack.ROOT / "asm" / "usa-bypass.sfc"
        produced.write_bytes(b"\xab" * 32)
        self.addCleanup(lambda: produced.unlink() if produced.exists() else None)

        found = pack.assemble_bypass("usa", b"\x00" * 16, self._under_root(), lambda _a: done)

        self.assertEqual(found, b"\xab" * 32)


@contextlib.contextmanager
def a_dump_in_place(region: str = "usa") -> Iterator[Path]:
    """Point a region at a file that exists, so the presence check lets a run through.

    These cases drive `pack.main` past the point where it looks for the dump, and
    what they check has nothing to do with the dump's contents: the builder is
    injected. Pointing the region at a temporary file rather than skipping is what
    lets them run on a machine that holds no cartridge, which is every machine but
    the author's.
    """
    original = pack.REGIONS[region]
    with tempfile.TemporaryDirectory() as where:
        stand_in = Path(where) / "stand-in.sfc"
        stand_in.write_bytes(b"\x00")
        pack.REGIONS[region] = original._replace(retail=stand_in)
        try:
            yield stand_in
        finally:
            pack.REGIONS[region] = original


class EntryTest(unittest.TestCase):
    """A run from the command line, with the slow steps passed in."""

    def test_a_region_nobody_knows_is_refused(self) -> None:
        complained: list[Any] = []

        code = pack.main(["pack.py", "mars"], say=lambda _l: None, complain=complained.append)

        self.assertEqual(code, 2)
        self.assertIn("unknown region", complained[0])

    def test_a_dump_that_is_not_here_is_named_rather_than_guessed_at(self) -> None:
        complained: list[Any] = []
        original = pack.REGIONS["usa"]
        pack.REGIONS["usa"] = original._replace(retail=Path("/nowhere/at/all.sfc"))
        try:
            code = pack.main(["pack.py", "usa"], say=lambda _l: None, complain=complained.append)
        finally:
            pack.REGIONS["usa"] = original

        self.assertEqual(code, 1)
        self.assertIn("not present", complained[0])
        self.assertIn("nowhere", " ".join(complained))

    def test_a_table_that_does_not_pass_the_gate_stops_the_build(self) -> None:
        complained: list[Any] = []

        with a_dump_in_place():
            code = pack.main(
                ["pack.py", "usa"],
                gate_check=lambda _region: ["a stream is missing"],
                say=lambda _l: None,
                complain=complained.append,
            )

        self.assertIn(code, (1,))
        self.assertIn("does not pass the gate", " ".join(complained))

    def test_a_patch_that_will_not_assemble_stops_it_too(self) -> None:
        def boom(_region: str, _workdir: Path) -> Any:
            raise pack.AssemblyFailed("asar said no")

        complained: list[Any] = []
        with tempfile.TemporaryDirectory() as tmp, a_dump_in_place():
            code = pack.main(
                ["pack.py", "usa"],
                make=boom,
                gate_check=lambda _region: [],
                say=lambda _l: None,
                complain=complained.append,
                dist=tmp,
            )

        self.assertEqual(code, 1)
        self.assertIn("asar said no", complained[0])

    def test_a_whole_run_writes_an_image_and_a_manifest(self) -> None:
        said: list[Any] = []
        with tempfile.TemporaryDirectory() as tmp, a_dump_in_place():
            code = pack.main(
                ["pack.py", "usa"],
                make=lambda _region, _workdir: b"\x00" * 64,
                gate_check=lambda _region: [],
                say=said.append,
                dist=tmp,
            )

            self.assertEqual(code, 0)
            written = (Path(tmp) / pack.MANIFEST).read_text()

        self.assertIn(pack.output_name("usa"), written)
        self.assertIn("64 bytes", " ".join(said))


if __name__ == "__main__":
    unittest.main(verbosity=2)
