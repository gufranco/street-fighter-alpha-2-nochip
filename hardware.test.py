import importlib
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

import hardware


class PathTest(unittest.TestCase):
    def test_every_model_it_names_is_checked_out_and_not_merely_named(self) -> None:
        self.assertEqual(hardware.missing_models(), [])

    def test_a_model_it_does_not_carry_is_refused_by_name(self) -> None:
        with self.assertRaises(hardware.UnknownPackage):
            hardware.root_of("nonsense")

    def test_the_refusal_lists_what_is_available(self) -> None:
        with self.assertRaises(hardware.UnknownPackage) as raised:
            hardware.root_of("nonsense")

        self.assertIn("sdd1", str(raised.exception))

    def test_installing_puts_every_model_on_the_import_path(self) -> None:
        hardware.install()

        for name in hardware.PACKAGES:
            self.assertIn(str(hardware.root_of(name)), sys.path)

    def test_installing_twice_does_not_stack_the_path(self) -> None:
        hardware.install()
        before = list(sys.path)

        hardware.install()

        self.assertEqual(sys.path, before)


class LoadTest(unittest.TestCase):
    def test_a_model_comes_back_by_the_name_it_is_published_under(self) -> None:
        found = hardware.load("sdd1")

        self.assertTrue(hasattr(found, "decompress"))

    def test_loading_a_model_it_does_not_carry_is_refused_before_importing(self) -> None:
        with self.assertRaises(hardware.UnknownPackage):
            hardware.load("nonsense")

    def test_loading_the_same_model_twice_gives_the_same_module(self) -> None:
        self.assertIs(hardware.load("mapper"), hardware.load("mapper"))


class ModelTest(unittest.TestCase):
    def setUp(self) -> None:
        hardware.install()

    def test_the_processor_reads_as_well_as_runs(self) -> None:
        cpu = importlib.import_module("mos65xx")

        self.assertTrue(hasattr(cpu, "Cpu"))
        self.assertTrue(hasattr(cpu, "disassemble"))

    def test_the_audio_processor_is_the_one_that_was_vendored(self) -> None:
        apu = importlib.import_module("spc700")

        self.assertTrue(hasattr(apu, "Cpu"))
        self.assertTrue(hasattr(apu, "disassemble"))

    def test_the_decompressor_is_the_one_that_was_vendored(self) -> None:
        chip = importlib.import_module("sdd1")

        self.assertTrue(hasattr(chip, "decompress"))
        self.assertEqual(chip.MAX_LENGTH, 0x10000)

    def test_the_audio_mixer_is_the_one_that_was_vendored(self) -> None:
        mixer = importlib.import_module("sdsp")

        self.assertTrue(hasattr(mixer, "Chip"))
        self.assertEqual(mixer.VOICE_COUNT, 8)

    def test_the_image_handling_is_the_one_that_was_vendored(self) -> None:
        found = importlib.import_module("romimage")

        self.assertTrue(hasattr(found.dump, "read"))
        self.assertTrue(hasattr(found.rewrite, "declare_rom_only"))

    def test_the_image_package_reads_the_map_this_project_pinned(self) -> None:
        found = importlib.import_module("romimage")
        used = importlib.import_module("mapper")

        self.assertIs(found.rewrite.mapper, used)

    def test_the_cartridge_map_is_the_one_that_was_vendored(self) -> None:
        found = importlib.import_module("mapper")

        self.assertTrue(hasattr(found, "resolve"))
        self.assertEqual(found.ENABLE, 0x420B)

    def test_every_model_reports_a_released_version(self) -> None:
        for name in hardware.PACKAGES:
            found = importlib.import_module(name)

            self.assertRegex(found.__version__, r"^\d+\.\d+\.\d+$")


class CheckoutTest(unittest.TestCase):
    def test_a_directory_with_nothing_in_it_does_not_count_as_checked_out(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            empty = Path(tmp) / "snes-rom-image-python"
            empty.mkdir()
            original, hardware.ROOT = hardware.ROOT, Path(tmp)
            try:
                self.assertFalse(hardware.is_checked_out("romimage"))
            finally:
                hardware.ROOT = original

    def test_loading_an_unchecked_out_model_names_the_command_that_fixes_it(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            (Path(tmp) / "snes-rom-image-python").mkdir()
            (Path(tmp) / ".git").mkdir()
            original, hardware.ROOT = hardware.ROOT, Path(tmp)
            try:
                with self.assertRaises(hardware.ModelMissing) as raised:
                    hardware.load("romimage")
            finally:
                hardware.ROOT = original

        self.assertIn("not checked out", str(raised.exception))
        self.assertIn("git submodule update --init --recursive", str(raised.exception))

    def test_the_message_names_every_model_that_is_missing_not_just_the_one_asked_for(self) -> None:
        message = hardware.checkout_message(["romimage", "sdd1"], from_git=True)

        self.assertIn("romimage", message)
        self.assertIn("sdd1", message)

    def test_the_message_reads_as_singular_when_one_model_is_missing(self) -> None:
        self.assertIn("model is", hardware.checkout_message(["sdd1"], from_git=True))

    def test_the_message_reads_as_plural_when_several_are_missing(self) -> None:
        self.assertIn("models are", hardware.checkout_message(["sdd1", "mapper"], from_git=True))

    def test_a_clone_is_told_the_command_that_fills_the_submodules_in(self) -> None:
        message = hardware.checkout_message(["sdd1"], from_git=True)

        self.assertIn("git submodule update --init --recursive", message)
        self.assertNotIn("archive", message)

    def test_an_archive_is_not_given_a_command_that_cannot_work_there(self) -> None:
        message = hardware.checkout_message(["sdd1"], from_git=False)

        self.assertNotIn("git submodule update", message)

    def test_an_archive_is_told_to_clone_and_where_from(self) -> None:
        message = hardware.checkout_message(["sdd1"], from_git=False)

        self.assertIn("archive", message)
        self.assertIn(f"git clone --recurse-submodules {hardware.ORIGIN}", message)

    def test_this_working_tree_is_recognised_as_a_clone(self) -> None:
        self.assertTrue(hardware.is_git_checkout())

    def test_an_unknown_name_is_still_refused_before_anything_else(self) -> None:
        with self.assertRaises(hardware.UnknownPackage):
            hardware.is_checked_out("nonsense")


if __name__ == "__main__":
    unittest.main()
