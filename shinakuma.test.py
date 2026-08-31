import importlib.util
import sys
import tempfile
import unittest
from pathlib import Path
from typing import Any, ClassVar, override

sys.path.insert(0, str(Path(__file__).resolve().parent))

import hardware

wdc65816 = hardware.load("mos65xx")
dump = hardware.load("romimage").dump


ROOT = Path(__file__).resolve().parent


def load_module(name: str) -> Any:
    spec = importlib.util.spec_from_file_location(name, ROOT / f"{name}.py")
    assert spec is not None and spec.loader is not None, "no loader for that path"
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


shinakuma = load_module("shinakuma")

USA = ROOT / "roms" / "sfa2-usa-final.sfc"
JP = ROOT / "roms" / "sfz2-jp-final.sfc"


class SignatureTest(unittest.TestCase):
    def test_the_gate_signature_is_the_documented_length(self) -> None:
        self.assertEqual(len(shinakuma.GATE), 0x2F)

    def test_the_signature_starts_with_php_and_a_sixteen_bit_switch(self) -> None:
        self.assertEqual(shinakuma.GATE[:3], bytes([0x08, 0xC2, 0x30]))

    def test_the_signature_ends_by_storing_the_unlock_flag(self) -> None:
        self.assertEqual(shinakuma.GATE[-6:], bytes([0xA9, 0x4B, 0x4A, 0x8D, 0x09, 0x1B]))

    def test_the_branch_lands_on_the_unconditional_store(self) -> None:
        landing = shinakuma.PRECONDITION + 2 + shinakuma.BRANCH[1]

        self.assertEqual(landing, shinakuma.SET_FLAG)

    def test_the_initials_spell_the_documented_code(self) -> None:
        self.assertEqual(shinakuma.INITIALS, b"KAJ")

    def test_the_button_combination_is_l_x_y_and_start(self) -> None:
        self.assertEqual(
            shinakuma.COMBINATION,
            shinakuma.BUTTON_L | shinakuma.BUTTON_X | shinakuma.BUTTON_Y | shinakuma.BUTTON_START,
        )


class FindGateTest(unittest.TestCase):
    def test_a_rom_without_the_gate_yields_nothing(self) -> None:
        self.assertIsNone(shinakuma.find_gate(bytes(0x20000)))

    def test_the_gate_is_located_by_its_signature(self) -> None:
        rom = bytearray(0x20000)
        rom[0x00ABCD : 0x00ABCD + len(shinakuma.GATE)] = shinakuma.GATE

        self.assertEqual(shinakuma.find_gate(bytes(rom)), 0x00ABCD)

    def test_two_gates_are_rejected_as_ambiguous(self) -> None:
        rom = bytearray(0x20000)
        rom[0x001000 : 0x001000 + len(shinakuma.GATE)] = shinakuma.GATE
        rom[0x009000 : 0x009000 + len(shinakuma.GATE)] = shinakuma.GATE

        with self.assertRaises(ValueError):
            shinakuma.find_gate(bytes(rom))


class ApplyTest(unittest.TestCase):
    def make_rom(self) -> bytes:
        rom = bytearray(0x20000)
        rom[0x00EC6E : 0x00EC6E + len(shinakuma.GATE)] = shinakuma.GATE
        return bytes(rom)

    def test_the_branch_replaces_the_precondition_test(self) -> None:
        patched = shinakuma.apply(self.make_rom())
        site = 0x00EC6E + shinakuma.PRECONDITION

        self.assertEqual(patched[site : site + 2], shinakuma.BRANCH)

    def test_only_the_branch_and_the_checksum_change(self) -> None:
        rom = self.make_rom()

        patched = shinakuma.apply(rom)
        changed = {i for i in range(len(rom)) if rom[i] != patched[i]}
        site = 0x00EC6E + shinakuma.PRECONDITION
        allowed = {site, site + 1} | set(
            range(shinakuma.spcfast.CHECKSUM_FIELD, shinakuma.spcfast.CHECKSUM_FIELD + 4)
        )

        self.assertTrue(changed.issubset(allowed))

    def test_the_store_itself_is_left_alone(self) -> None:
        rom = self.make_rom()
        patched = shinakuma.apply(rom)
        site = 0x00EC6E + shinakuma.SET_FLAG

        self.assertEqual(patched[site : site + 6], rom[site : site + 6])

    def test_the_source_rom_is_not_modified(self) -> None:
        rom = self.make_rom()

        shinakuma.apply(rom)

        self.assertEqual(rom[0x00EC6E + shinakuma.PRECONDITION], 0xAD)

    def test_applying_twice_changes_nothing_further(self) -> None:
        once = shinakuma.apply(self.make_rom())

        self.assertEqual(shinakuma.apply(once), once)

    def test_a_rom_without_the_gate_is_rejected(self) -> None:
        with self.assertRaises(ValueError):
            shinakuma.apply(bytes(0x20000))


class DisassemblyTest(unittest.TestCase):
    def test_the_stock_gate_disassembles_to_the_documented_listing(self) -> None:
        listing = [
            instruction.text
            for instruction in wdc65816.disassemble(shinakuma.GATE, 0, 0xC0EC6E, m=False, x=False)
        ]

        self.assertEqual(
            listing,
            [
                "php",
                "rep #$30",
                "lda $1b05",
                "bpl $ec9d",
                "lda $1b09",
                "cmp #$4a4b",
                "beq $ec9d",
                "lda $7efe04",
                "cmp #$414b",
                "bne $ec9d",
                "lda $7efe05",
                "cmp #$4a41",
                "bne $ec9d",
                "lda $b0",
                "cmp #$5060",
                "bne $ec9d",
                "lda #$4a4b",
                "sta $1b09",
            ],
        )

    def test_the_patched_gate_branches_straight_to_the_store(self) -> None:
        patched = bytearray(shinakuma.GATE)
        patched[shinakuma.PRECONDITION : shinakuma.PRECONDITION + 2] = shinakuma.BRANCH
        listing = list(wdc65816.disassemble(bytes(patched), 0, 0xC0EC6E, count=3, m=False, x=False))

        self.assertEqual([i.text for i in listing], ["php", "rep #$30", "bra $ec97"])


@unittest.skipUnless(
    USA.exists() and JP.exists(), "the retail ROMs are not present"
)  # pragma: no cover
class RetailRomTest(unittest.TestCase):
    jp: ClassVar[Any]
    usa: ClassVar[Any]

    @classmethod
    @override
    def setUpClass(cls) -> None:
        cls.usa = dump.read(USA)
        cls.jp = dump.read(JP)

    def test_the_gate_is_present_exactly_once_in_each_region(self) -> None:
        self.assertEqual(shinakuma.find_gate(self.usa), 0x00EC6E)
        self.assertEqual(shinakuma.find_gate(self.jp), 0x00ECA0)

    def test_the_gate_is_byte_identical_across_regions(self) -> None:
        usa = shinakuma.find_gate(self.usa)
        jp = shinakuma.find_gate(self.jp)

        self.assertEqual(
            self.usa[usa : usa + len(shinakuma.GATE)],
            self.jp[jp : jp + len(shinakuma.GATE)],
        )

    def test_patching_touches_only_the_branch_and_the_checksum(self) -> None:
        patched = shinakuma.apply(self.usa)
        changed = {i for i in range(len(patched)) if patched[i] != self.usa[i]}
        site = 0x00EC6E + shinakuma.PRECONDITION
        allowed = {site, site + 1} | set(
            range(shinakuma.spcfast.CHECKSUM_FIELD, shinakuma.spcfast.CHECKSUM_FIELD + 4)
        )

        self.assertTrue(changed.issubset(allowed))
        self.assertIn(site, changed)
        self.assertIn(site + 1, changed)

    def test_the_substitution_handler_is_untouched(self) -> None:
        patched = shinakuma.apply(self.usa)

        self.assertEqual(patched[0x00CA7F:0x00CAD0], self.usa[0x00CA7F:0x00CAD0])

    def test_both_regions_patch_at_their_own_offset(self) -> None:
        for rom, offset in ((self.usa, 0x00EC6E), (self.jp, 0x00ECA0)):
            patched = shinakuma.apply(rom)
            site = offset + shinakuma.PRECONDITION

            self.assertEqual(patched[site : site + 2], shinakuma.BRANCH)


class GatelessTest(unittest.TestCase):
    """An image with no unlock gate is refused rather than written out unchanged."""

    def test_an_image_with_no_gate_is_refused(self) -> None:
        with self.assertRaises(ValueError) as raised:
            shinakuma.apply(bytes(0x40000))

        self.assertIn("no Shin Akuma unlock gate", str(raised.exception))


class EntryTest(unittest.TestCase):
    """The command line, run with both streams collected rather than printed."""

    def _paths(self) -> tuple[Path, Path]:
        where = Path(tempfile.mkdtemp())
        source = where / "in.sfc"
        source.write_bytes(USA.read_bytes())
        return source, where / "out.sfc"

    @unittest.skipUnless(
        USA.exists(), "the retail dump is supplied by the builder"
    )  # pragma: no cover
    def test_running_it_again_on_its_own_output_reports_rather_than_raising(self) -> None:
        source, output = self._paths()
        shinakuma.main(["shinakuma.py", str(source), str(output)], say=lambda _l: None)
        said: list[str] = []

        code = shinakuma.main(
            ["shinakuma.py", str(output), str(output.parent / "third.sfc")], say=said.append
        )

        self.assertEqual(code, 0)
        self.assertIn("already", " ".join(said))

    @unittest.skipUnless(
        USA.exists(), "the retail dump is supplied by the builder"
    )  # pragma: no cover
    def test_and_leaves_the_image_it_was_given_unchanged(self) -> None:
        source, output = self._paths()
        shinakuma.main(["shinakuma.py", str(source), str(output)], say=lambda _l: None)
        third = output.parent / "third.sfc"

        shinakuma.main(["shinakuma.py", str(output), str(third)], say=lambda _l: None)

        self.assertEqual(third.read_bytes(), output.read_bytes())

    def test_too_few_arguments_are_refused_with_the_usage(self) -> None:
        complained: list[Any] = []

        code = shinakuma.main(["shinakuma.py"], say=lambda _l: None, complain=complained.append)

        self.assertEqual(code, 2)
        self.assertIn("usage", complained[0])

    @unittest.skipUnless(
        USA.exists(), "the retail dump is supplied by the builder"
    )  # pragma: no cover
    def test_patching_the_source_in_place_is_refused(self) -> None:
        source, _ = self._paths()
        complained: list[Any] = []

        code = shinakuma.main(
            ["shinakuma.py", str(source), str(source)],
            say=lambda _l: None,
            complain=complained.append,
        )

        self.assertEqual(code, 1)
        self.assertIn("in place", complained[0])

    @unittest.skipUnless(
        USA.exists(), "the retail dump is supplied by the builder"
    )  # pragma: no cover
    def test_a_run_writes_the_patched_image_and_says_what_it_did(self) -> None:
        source, output = self._paths()
        said: list[Any] = []

        code = shinakuma.main(["shinakuma.py", str(source), str(output)], say=said.append)

        self.assertEqual(code, 0)
        self.assertTrue(output.exists())
        self.assertTrue(said)


if __name__ == "__main__":
    unittest.main(verbosity=2)
