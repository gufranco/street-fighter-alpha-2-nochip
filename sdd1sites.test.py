import importlib.util
import sys
import unittest
from pathlib import Path
from typing import Any, ClassVar, override

sys.path.insert(0, str(Path(__file__).resolve().parent))

import hardware

dump = hardware.load("romimage").dump


ROOT = Path(__file__).resolve().parent


def load_module(name: str) -> Any:
    spec = importlib.util.spec_from_file_location(name, ROOT / f"{name}.py")
    assert spec is not None and spec.loader is not None, "no loader for that path"
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


sites = load_module("sdd1sites")
sdd1map = load_module("sdd1map")

RETAIL = ROOT / "roms" / "sfa2-usa-final.sfc"
TAGGED = ROOT / "roms" / "sfa2-usa-vc-sound-restored.sfc"
EXPECTED_ARM_SITES = 7
KNOWN_ARM_OFFSETS = (
    0x000482,
    0x00085A,
    0x000881,
    0x0077BF,
    0x12BBD3,
    0x1AE002,
    0x1AE131,
)


class MaskTest(unittest.TestCase):
    def test_stream_bytes_are_marked_as_data(self) -> None:
        rom = bytes(4096)
        entry = sdd1map.Entry(index=0, source=100, target=0, length=16)

        mask = sites.compressed_mask(rom, [entry])

        self.assertTrue(mask[100])
        self.assertFalse(mask[99])

    def test_an_entry_of_unknown_length_is_skipped(self) -> None:
        rom = bytes(4096)
        entry = sdd1map.Entry(index=0, source=100, target=0, length=None)

        self.assertEqual(sum(sites.compressed_mask(rom, [entry])), 0)


class RegisterScanTest(unittest.TestCase):
    def test_a_write_to_the_arm_register_is_found(self) -> None:
        rom = b"\x00" * 16 + b"\x8d\x01\x48" + b"\x00" * 16
        mask = bytearray(len(rom))

        found = sites.find_register_writes(rom, mask)

        self.assertEqual([(f.offset, f.register) for f in found], [(16, 0x4801)])

    def test_a_write_buried_in_compressed_data_is_ignored(self) -> None:
        rom = b"\x00" * 16 + b"\x8d\x01\x48" + b"\x00" * 16
        mask = bytearray(len(rom))
        mask[16] = 1

        self.assertEqual(sites.find_register_writes(rom, mask), [])

    def test_the_whole_register_block_is_scanned(self) -> None:
        rom = b"\x8d\x00\x48" + b"\x8d\x04\x48" + b"\x8d\x08\x48"
        mask = bytearray(len(rom))

        found = sites.find_register_writes(rom, mask)

        self.assertEqual([f.register for f in found], [0x4800, 0x4804])


@unittest.skipUnless(
    RETAIL.exists() and TAGGED.exists(), "roms are not present"
)  # pragma: no cover
class RealRomTest(unittest.TestCase):
    found: ClassVar[Any]
    mask: ClassVar[Any]
    rom: ClassVar[Any]

    @classmethod
    @override
    def setUpClass(cls) -> None:
        cls.rom = dump.read(RETAIL)
        entries = sdd1map.build_map(dump.read(TAGGED))
        cls.mask = sites.compressed_mask(cls.rom, entries)
        cls.found = sites.find_register_writes(cls.rom, cls.mask)

    def test_the_arm_register_is_written_from_exactly_seven_places(self) -> None:
        arms = [f for f in self.found if f.register == sites.ARM_REGISTER]

        self.assertEqual(len(arms), EXPECTED_ARM_SITES)
        self.assertEqual(tuple(f.offset for f in arms), KNOWN_ARM_OFFSETS)

    def test_no_register_write_hides_inside_compressed_data(self) -> None:
        for found in self.found:
            self.assertFalse(self.mask[found.offset])

    def test_every_arm_site_is_followed_by_a_dma_start(self) -> None:
        for offset in KNOWN_ARM_OFFSETS:
            listing = sites.window(self.rom, offset, forward=16)
            after = [i for i in listing if i.offset > offset]

            self.assertTrue(
                any(i.text == "sta $420b" for i in after[:4]),
                f"no dma start after {offset:#x}",
            )

    def test_the_window_resynchronises_onto_the_site(self) -> None:
        listing = sites.window(self.rom, KNOWN_ARM_OFFSETS[0])

        self.assertIn(KNOWN_ARM_OFFSETS[0], [i.offset for i in listing])

    def test_every_arm_site_sits_in_a_bank_reachable_as_lorom_code(self) -> None:
        for offset in KNOWN_ARM_OFFSETS:
            address = sites.lorom_address(offset)

            self.assertLess(address >> 16, 0x80)
            self.assertGreaterEqual(address & 0xFFFF, 0x8000)


def tagged_blob(markers: list[tuple[int, int]], size: int = 8192) -> bytes:
    blob = bytearray(size)
    for position, target in markers:
        blob[position : position + 4] = sdd1map.MARKER
        blob[position + 4 : position + 8] = target.to_bytes(4, "little")
    return bytes(blob)


class WindowTest(unittest.TestCase):
    """Backing up to the instruction boundary a register write really sits on."""

    def test_a_write_near_the_start_still_yields_a_listing(self) -> None:
        rom = bytearray(256)
        rom[4:7] = bytes([sites.STA_ABSOLUTE, 0x01, 0x48])

        listing = sites.window(rom, 4)

        self.assertTrue(listing)

    def test_the_listing_reaches_the_site_that_was_asked_for(self) -> None:
        rom = bytearray(4096)
        rom[0x400:0x403] = bytes([sites.STA_ABSOLUTE, 0x01, 0x48])

        listing = sites.window(rom, 0x400)

        self.assertTrue(any(one.offset == 0x400 for one in listing))

    def test_a_window_that_never_lands_on_the_site_falls_back_to_it(self) -> None:
        rom = bytearray(256)
        rom[0:3] = bytes([sites.STA_ABSOLUTE, 0x01, 0x48])

        listing = sites.window(rom, 0, back=0, forward=4)

        self.assertEqual(listing[0].offset, 0)


class CommandTest(unittest.TestCase):
    """The command line, driven without a dump on the machine."""

    def run_with(self, argv: list[str], rom: bytes, tagged: bytes) -> tuple[int, list[str]]:
        said: list[str] = []
        code = sites.main(
            argv,
            read=lambda where: tagged if str(where) == "tagged" else rom,
            say=lambda *args, **_k: said.append(str(args[0])),
        )
        return code, said

    def test_too_few_arguments_prints_the_usage(self) -> None:
        code, said = self.run_with(["sdd1sites.py", "one"], b"", b"")

        self.assertEqual((code, "usage" in said[0]), (2, True))

    def test_a_cartridge_with_no_register_writes_reports_the_coverage(self) -> None:
        code, said = self.run_with(
            ["sdd1sites.py", "rom", "tagged"], bytes(0x10000), tagged_blob([(0x100, 0)])
        )

        self.assertEqual((code, "compressed data covers" in said[0]), (0, True))

    def test_a_register_write_is_named_with_its_register(self) -> None:
        rom = bytearray(0x10000)
        rom[0x400:0x403] = bytes([sites.STA_ABSOLUTE, 0x00, 0x48])

        _, said = self.run_with(
            ["sdd1sites.py", "rom", "tagged"], bytes(rom), tagged_blob([(0x100, 0)])
        )

        self.assertIn("$4800 written from 1 places", "\n".join(said))

    def test_an_arm_site_is_listed_in_detail(self) -> None:
        rom = bytearray(0x10000)
        rom[0x400:0x403] = bytes([sites.STA_ABSOLUTE, 0x01, 0x48])

        _, said = self.run_with(
            ["sdd1sites.py", "rom", "tagged"], bytes(rom), tagged_blob([(0x100, 0)])
        )

        self.assertIn("arm sites in detail", "\n".join(said))

    def test_a_write_inside_compressed_data_is_not_a_site(self) -> None:
        markers = tagged_blob([(0x300, 0), (0x500, 4096)])
        covered = sites.compressed_mask(bytes(0x10000), sdd1map.build_map(markers))
        inside = covered.index(1) + 4
        rom = bytearray(0x10000)
        rom[inside : inside + 3] = bytes([sites.STA_ABSOLUTE, 0x01, 0x48])

        _, said = self.run_with(["sdd1sites.py", "rom", "tagged"], bytes(rom), markers)

        self.assertNotIn("$4801 written", "\n".join(said))


if __name__ == "__main__":
    unittest.main(verbosity=2)
