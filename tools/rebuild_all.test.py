import importlib.util
import sys
import unittest
from pathlib import Path
from typing import Any, ClassVar, override

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

import hardware  # noqa: E402

dump = hardware.load("romimage").dump


def load_module(name: str, path: Path) -> Any:
    spec = importlib.util.spec_from_file_location(name, path)
    assert spec is not None and spec.loader is not None, "no loader for that path"
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


rebuild_all = load_module("rebuild_all", ROOT / "tools" / "rebuild_all.py")

RETAIL = ROOT / "roms" / "sfz2-jp-final.sfc"


class MatrixTest(unittest.TestCase):
    def test_every_region_names_a_retail_cartridge_and_a_bypass(self) -> None:
        self.assertEqual(sorted(rebuild_all.RETAIL), sorted(rebuild_all.BYPASS))

    def test_the_prefight_table_goes_into_exactly_one_variant(self) -> None:
        self.assertIn(rebuild_all.PREFIGHT_VARIANT, ("base", "spc", "sa", "both"))


@unittest.skipUnless(RETAIL.exists(), "the retail cartridge is not present")  # pragma: no cover
class VariantTest(unittest.TestCase):
    retail: ClassVar[Any]
    variants: ClassVar[Any]

    @classmethod
    @override
    def setUpClass(cls) -> None:
        cls.retail = dump.read(RETAIL)
        cls.variants = rebuild_all.variants(cls.retail)

    def test_four_variants_are_produced(self) -> None:
        self.assertEqual(sorted(self.variants), ["base", "both", "sa", "spc"])

    def test_the_base_variant_is_the_retail_cartridge_untouched(self) -> None:
        self.assertEqual(self.variants["base"], self.retail)

    def test_every_variant_is_the_same_size_as_the_cartridge(self) -> None:
        for name, image in self.variants.items():
            self.assertEqual(len(image), len(self.retail), name)

    def test_every_variant_other_than_the_base_differs_from_it(self) -> None:
        for name, image in self.variants.items():
            if name == "base":
                continue
            self.assertNotEqual(image, self.retail, name)

    def test_no_two_variants_are_the_same_image(self) -> None:
        seen: dict[Any, Any] = {}
        for name, image in self.variants.items():
            self.assertNotIn(image, seen.values(), name)
            seen[name] = image

    def test_the_fast_upload_variant_carries_the_fast_upload_patch(self) -> None:
        spcfast = load_module("spcfast", ROOT / "spcfast.py")

        self.assertTrue(spcfast.is_patched(self.variants["spc"]))
        self.assertFalse(spcfast.is_patched(self.variants["sa"]))

    def test_the_everything_variant_carries_the_skip_patch_as_well(self) -> None:
        repeatload = load_module("repeatload", ROOT / "repeatload.py")

        self.assertTrue(repeatload.is_patched(self.variants["both"]))
        self.assertFalse(repeatload.is_patched(self.variants["spc"]))

    def test_the_everything_variant_carries_the_unlock(self) -> None:
        shinakuma = load_module("shinakuma", ROOT / "shinakuma.py")

        self.assertTrue(shinakuma.is_patched(self.variants["both"]))
        self.assertTrue(shinakuma.is_patched(self.variants["sa"]))


class EntryTest(unittest.TestCase):
    def test_each_region_resolves_to_a_non_empty_set_of_streams(self) -> None:
        for region in rebuild_all.RETAIL:
            self.assertGreater(len(rebuild_all.entries_for(region)), 0, region)

    def test_the_two_regions_resolve_to_different_sets(self) -> None:
        jp = [(entry.source, entry.length) for entry in rebuild_all.entries_for("jp")]
        usa = [(entry.source, entry.length) for entry in rebuild_all.entries_for("usa")]

        self.assertNotEqual(jp, usa)


class AssembleTest(unittest.TestCase):
    """Staging one variant and asking the assembler for it."""

    @staticmethod
    def build(region: str, name: str, cart: bytes) -> tuple[Path, list[Any]]:
        asked: list[Any] = []

        def _record(args: Any, **_rest: Any) -> Any:
            asked.append(args)
            (rebuild_all.ROOT / "asm" / args[4]).write_bytes(cart)
            return None

        return rebuild_all.assemble(region, name, cart, execute=_record), asked

    def test_the_bypass_source_for_the_region_is_the_one_assembled(self) -> None:
        _, asked = self.build("jp", "probe", bytes(0x1000))

        self.assertIn(rebuild_all.BYPASS["jp"], asked[0][2])

    def test_the_staged_cartridge_is_written_beside_the_output(self) -> None:
        self.build("jp", "probe", bytes(0x1000))

        self.assertTrue((rebuild_all.OUT / "jp-probe-cart.sfc").exists())

    def test_it_returns_the_assembled_image_under_the_build_directory(self) -> None:
        found, _ = self.build("jp", "probe", bytes(0x1000))

        self.assertEqual(found, rebuild_all.OUT / "jp-probe-bypass.sfc")

    def test_the_scratch_file_the_assembler_wrote_is_removed(self) -> None:
        self.build("jp", "probe", bytes(0x1000))

        self.assertFalse((rebuild_all.ROOT / "asm" / "jp-probe-bypass.sfc").exists())


class ImageSourceTest(unittest.TestCase):
    """What each variant puts into the image."""

    ROM = bytes(0x400000)

    def test_an_ordinary_variant_carries_nothing_extra(self) -> None:
        found = rebuild_all.image_source("base", Path("bypass.sfc"), read=lambda _p: self.ROM)

        self.assertEqual(found, (self.ROM, ()))

    def test_the_prefight_variant_carries_its_table(self) -> None:
        rom = bytearray(self.ROM)
        at = 0x030000
        rom[at : at + len(rebuild_all.prefight.BUILDER_SIGNATURE)] = (
            rebuild_all.prefight.BUILDER_SIGNATURE
        )
        rom[rebuild_all.prefight.FILLER_FILE : rebuild_all.prefight.FILLER_END] = (
            b"\xff" * rebuild_all.prefight.FILLER_SIZE
        )
        window = rebuild_all.prefight.WINDOW_FIRST_BANK + (at >> 16)
        rom[0x020000:0x020004] = rebuild_all.prefight.call_to((window << 16) | (at & 0xFFFF))

        _, extra = rebuild_all.image_source(
            rebuild_all.PREFIGHT_VARIANT, Path("bypass.sfc"), read=lambda _p: bytes(rom)
        )

        self.assertEqual(extra[0][0], rebuild_all.prefight.TABLE_ADDRESS)


class CommandTest(unittest.TestCase):
    """The rebuild loop, driven without the dumps and without the assembler."""

    @staticmethod
    def headed() -> bytes:
        rom = bytearray(0x400000)
        rom[0x7FC0:0x7FD5] = b"PROBE                "[:21]
        rom[0x7FD5], rom[0x7FD7], rom[0x7FD9] = 0x20, 0x0C, 0x01
        rom[0x7FDA], rom[0x7FDE:0x7FE0] = 0x33, (0xFFFF).to_bytes(2, "little")
        return bytes(rom)

    def run_with(self, carts: dict[str, dict[str, Any]]) -> tuple[int, list[str]]:
        said: list[str] = []
        rom = self.headed()
        code = rebuild_all.main(
            carts=carts,
            build=lambda region, name, _c: rebuild_all.OUT / f"{region}-{name}-bypass.sfc",
            source_for=lambda _n, _b: (rom, ()),
            table_for=lambda _r: [],
            say=said.append,
        )
        return code, said

    def test_one_variant_produces_one_report_line(self) -> None:
        code, said = self.run_with({"jp": {"base": b""}})

        self.assertEqual((code, len(said)), (0, 1))

    def test_the_line_names_the_region_and_the_variant(self) -> None:
        _, said = self.run_with({"jp": {"base": b""}})

        self.assertIn("jp-base:", said[0])

    def test_every_variant_of_every_region_is_built(self) -> None:
        _, said = self.run_with({"jp": {"base": b"", "spc": b""}, "usa": {"base": b""}})

        self.assertEqual(len(said), 3)

    def test_the_free_image_is_written_where_the_name_says(self) -> None:
        self.run_with({"jp": {"base": b""}})

        self.assertTrue((rebuild_all.OUT / "jp-base-free.sfc").exists())

    def test_the_prefight_variant_carries_its_table(self) -> None:
        rom = self.headed()
        seen: list[str] = []

        def _source(name: str, _bypass: Path) -> tuple[Any, tuple[Any, ...]]:
            seen.append(name)
            return rom, ()

        rebuild_all.main(
            carts={"jp": {rebuild_all.PREFIGHT_VARIANT: b""}},
            build=lambda region, name, _c: rebuild_all.OUT / f"{region}-{name}-bypass.sfc",
            source_for=_source,
            table_for=lambda _r: [],
            say=lambda _l: None,
        )

        self.assertEqual(seen, [rebuild_all.PREFIGHT_VARIANT])


if __name__ == "__main__":
    unittest.main()
