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


if __name__ == "__main__":
    unittest.main()
