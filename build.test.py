import contextlib
import importlib.util
import io
import tempfile
import unittest
from pathlib import Path
from typing import Any

MODULE_PATH = Path(__file__).resolve().parent / "build.py"


def load_module() -> Any:
    spec = importlib.util.spec_from_file_location("build", MODULE_PATH)
    assert spec is not None and spec.loader is not None, "no loader for that path"
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


bd = load_module()


class ImageTest(unittest.TestCase):
    def test_the_image_tag_is_pinned_not_latest(self) -> None:
        self.assertNotIn(":latest", bd.IMAGE)
        self.assertIn(":", bd.IMAGE)

    def test_the_dockerfile_sits_beside_the_sources(self) -> None:
        self.assertTrue((bd.ASM_DIR / "Dockerfile").exists())


class CommandTest(unittest.TestCase):
    def test_the_build_command_names_the_pinned_tag(self) -> None:
        args = bd.build_image_command()

        self.assertIn("build", args)
        self.assertIn(bd.IMAGE, args)

    def test_the_patch_command_mounts_the_work_tree_read_write(self) -> None:
        args = bd.patch_command(Path("/w"), "p.asm", "rom.sfc")

        joined = " ".join(args)
        self.assertIn("--rm", args)
        self.assertIn("/w:/work", joined)
        self.assertIn("p.asm", args)
        self.assertIn("rom.sfc", args)

    def test_the_container_runs_without_network(self) -> None:
        args = bd.patch_command(Path("/w"), "p.asm", "rom.sfc")

        self.assertIn("--network=none", args)

    def test_paths_are_passed_as_names_not_host_paths(self) -> None:
        args = bd.patch_command(Path("/some/host/dir"), "patch.asm", "rom.sfc")

        self.assertNotIn("/some/host/dir/patch.asm", args)


class ArgumentTest(unittest.TestCase):
    def test_the_image_only_flag_is_reachable_on_its_own(self) -> None:
        self.assertTrue(bd.wants_image_only(["build.py", "--image"]))

    def test_a_normal_invocation_is_not_image_only(self) -> None:
        self.assertFalse(bd.wants_image_only(["build.py", "p.asm", "in", "out"]))

    def test_too_few_arguments_is_not_image_only(self) -> None:
        self.assertFalse(bd.wants_image_only(["build.py"]))


class SafetyTest(unittest.TestCase):
    def test_a_rom_is_copied_before_patching(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            work = Path(tmp)
            rom = work / "orig.sfc"
            rom.write_bytes(b"x" * 1024)

            out = bd.stage_rom(rom, work, "out.sfc")

            self.assertTrue(out.exists())
            self.assertEqual(out.read_bytes(), rom.read_bytes())
            self.assertNotEqual(out, rom)

    def test_staging_never_overwrites_the_source(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            work = Path(tmp)
            rom = work / "orig.sfc"
            rom.write_bytes(b"A" * 512)

            out = bd.stage_rom(rom, work, "out.sfc")
            out.write_bytes(b"B" * 512)

            self.assertEqual(rom.read_bytes(), b"A" * 512)


class ToolchainTest(unittest.TestCase):
    def test_an_absent_program_is_named_rather_than_traced(self) -> None:
        with self.assertRaises(bd.ToolchainMissing) as raised:
            bd.run(["definitely-not-a-real-program-9f3a", "--version"])

        self.assertIn("definitely-not-a-real-program-9f3a", str(raised.exception))

    def test_the_message_says_how_to_check_the_program_is_there(self) -> None:
        message = bd.missing_message("docker")

        self.assertIn("docker --version", message)

    def test_the_message_says_why_a_container_is_used(self) -> None:
        self.assertIn("pinned", bd.missing_message("docker"))

    def test_an_absent_toolchain_exits_one_and_says_so_on_stderr(self) -> None:
        def absent():
            raise bd.ToolchainMissing("docker is not on PATH")

        original, bd.main = bd.main, absent
        stderr = io.StringIO()
        try:
            with contextlib.redirect_stderr(stderr):
                code = bd.cli()
        finally:
            bd.main = original

        self.assertEqual(code, 1)
        self.assertIn("docker is not on PATH", stderr.getvalue())

    def test_a_reachable_program_returns_its_own_exit_code(self) -> None:
        self.assertEqual(bd.run(["true"]), 0)
        self.assertEqual(bd.run(["false"]), 1)


class RunTest(unittest.TestCase):
    """What a build shells out to, checked without shelling out."""

    def test_a_command_is_printed_before_it_runs(self) -> None:
        said = []

        bd.run(["docker", "build"], execute=lambda _args: 0, say=said.append)

        self.assertIn("docker build", said[0])

    def test_and_what_it_returned_comes_back(self) -> None:
        self.assertEqual(bd.run(["x"], execute=lambda _args: 3, say=lambda _line: None), 3)


class StagingTest(unittest.TestCase):
    def test_patching_the_source_in_place_is_refused(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            where = Path(tmp)
            (where / "in.sfc").write_bytes(b"\x00" * 16)

            with self.assertRaises(ValueError):
                bd.stage_rom(where / "in.sfc", where, "in.sfc")


class ShellingOutTest(unittest.TestCase):
    """That the real path runs the command, checked with one that does nothing."""

    def test_with_nothing_passed_in_it_runs_the_command_itself(self) -> None:
        code = bd.run(["true"], say=lambda _line: None)

        self.assertEqual(code, 0)


class EntryTest(unittest.TestCase):
    def test_asking_for_the_image_alone_builds_only_that(self) -> None:
        ran = []

        code = bd.main(
            ["bd.py", "--image"], execute=lambda args: ran.append(args) or 0, say=lambda _l: None
        )

        self.assertEqual(code, 0)
        self.assertEqual(len(ran), 1)

    def test_too_few_arguments_are_refused_with_the_usage(self) -> None:
        said = []

        code = bd.main(["bd.py", "patch.asm"], say=lambda _l: None, complain=said.append)

        self.assertEqual(code, 2)
        self.assertIn("usage", said[0])

    def test_an_image_that_will_not_build_stops_before_anything_is_staged(self) -> None:
        said = []

        code = bd.main(
            ["bd.py", "patch.asm", "in.sfc", "out.sfc"],
            execute=lambda _args: 1,
            say=lambda _l: None,
            complain=said.append,
        )

        self.assertEqual(code, 1)
        self.assertIn("failed to build", said[0])

    def test_a_whole_run_stages_the_rom_and_patches_it(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            where = Path(tmp)
            (where / "patch.asm").write_text("; nothing")
            (where / "in.sfc").write_bytes(b"\x00" * 32)
            ran = []

            code = bd.main(
                ["bd.py", str(where / "patch.asm"), str(where / "in.sfc"), "out.sfc"],
                execute=lambda args: ran.append(args) or 0,
                say=lambda _l: None,
            )

            self.assertEqual(code, 0)
            self.assertEqual(len(ran), 2)
            self.assertTrue((where / "out.sfc").exists())

    def test_a_patch_that_fails_is_reported_as_what_it_returned(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            where = Path(tmp)
            (where / "patch.asm").write_text("; nothing")
            (where / "in.sfc").write_bytes(b"\x00" * 32)
            answers = iter([0, 4])

            code = bd.main(
                ["bd.py", str(where / "patch.asm"), str(where / "in.sfc"), "out.sfc"],
                execute=lambda _args: next(answers),
                say=lambda _l: None,
            )

            self.assertEqual(code, 4)


if __name__ == "__main__":
    unittest.main(verbosity=2)
