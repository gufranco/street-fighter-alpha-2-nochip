import hashlib
import importlib.util
import json
import tempfile
import unittest
import zlib
from collections.abc import Sequence
from pathlib import Path
from typing import Any, override

MODULE_PATH = Path(__file__).resolve().parent / "identify.py"


def load_module() -> Any:
    spec = importlib.util.spec_from_file_location("identify", MODULE_PATH)
    assert spec is not None and spec.loader is not None, "no loader for that path"
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


ident = load_module()

RETAIL = bytes(range(256)) * 4096
OTHER = bytes(range(255, -1, -1)) * 4096
CORRUPT = (b"\x00" * 1024) + RETAIL[1024:]


def digest_of(data: bytes | bytearray) -> dict[str, Any]:
    return {
        "size": len(data),
        "crc32": f"{zlib.crc32(data) & 0xFFFFFFFF:08X}",
        "md5": hashlib.md5(data).hexdigest(),
        "sha1": hashlib.sha1(data).hexdigest(),
        "sha256": hashlib.sha256(data).hexdigest(),
    }


def manifest_fixture() -> dict[str, Any]:
    return {
        "canonical": {"form": "one file, no copier header"},
        "decides": "sha256",
        "artifacts": [
            {
                "name": "Dungeon Master, USA",
                "filename": "dungeon-master-usa.sfc",
                "accepted": [digest_of(RETAIL)],
                "provenance": "fixture",
            },
            {
                "name": "Dungeon Master, Japan",
                "filename": "dungeon-master-jp.sfc",
                "accepted": [digest_of(OTHER)],
                "provenance": "fixture",
            },
            {
                "name": "Dungeon Master, Europe",
                "filename": "dungeon-master-eur.sfc",
                "accepted": [],
                "provenance": "no dump held",
            },
        ],
        "known_bad": [
            {
                "name": "a truncated USA dump",
                "sha256": digest_of(CORRUPT)["sha256"],
                "why": "the first kilobyte is zeroed",
            }
        ],
    }


def artifact_named(manifest: dict[str, Any], filename: str) -> dict[str, Any]:
    return next(a for a in manifest["artifacts"] if a["filename"] == filename)


class DigestTest(unittest.TestCase):
    def test_every_published_value_is_reported(self) -> None:
        identity = ident.digests(RETAIL)

        self.assertEqual(identity.size, len(RETAIL))
        self.assertEqual(identity.sha256, hashlib.sha256(RETAIL).hexdigest())
        self.assertEqual(identity.sha1, hashlib.sha1(RETAIL).hexdigest())
        self.assertEqual(identity.crc32, f"{zlib.crc32(RETAIL) & 0xFFFFFFFF:08X}")

    def test_the_crc_is_eight_uppercase_hex_digits(self) -> None:
        identity = ident.digests(b"")

        self.assertEqual(len(identity.crc32), 8)
        self.assertEqual(identity.crc32, identity.crc32.upper())


class DiagnoseTest(unittest.TestCase):
    @override
    def setUp(self) -> None:
        self.manifest = manifest_fixture()
        self.tmp = tempfile.TemporaryDirectory()
        self.roms = Path(self.tmp.name)
        self.addCleanup(self.tmp.cleanup)

    def usa(self) -> dict[str, Any]:
        return artifact_named(self.manifest, "dungeon-master-usa.sfc")

    def test_the_expected_dump_reads_as_ok(self) -> None:
        (self.roms / "dungeon-master-usa.sfc").write_bytes(RETAIL)

        found = ident.diagnose(self.usa(), self.manifest, self.roms)

        self.assertEqual(found.state, ident.STATE_OK)
        self.assertFalse(ident.blocking(found))

    def test_a_copier_header_is_stripped_before_the_digest_is_taken(self) -> None:
        (self.roms / "dungeon-master-usa.sfc").write_bytes(b"\x00" * 512 + RETAIL)

        found = ident.diagnose(self.usa(), self.manifest, self.roms)

        self.assertEqual(found.state, ident.STATE_OK)
        self.assertEqual(found.form, "copier header, stripped")

    def test_an_absent_file_is_missing_rather_than_wrong(self) -> None:
        found = ident.diagnose(self.usa(), self.manifest, self.roms)

        self.assertEqual(found.state, ident.STATE_MISSING)
        self.assertFalse(ident.blocking(found))

    def test_a_file_of_the_wrong_length_names_the_length_it_wanted(self) -> None:
        (self.roms / "dungeon-master-usa.sfc").write_bytes(RETAIL[:4096])

        found = ident.diagnose(self.usa(), self.manifest, self.roms)

        self.assertEqual(found.state, ident.STATE_WRONG_SIZE)
        self.assertIn(f"{len(RETAIL):,}", found.detail)
        self.assertTrue(ident.blocking(found))

    def test_the_right_length_with_other_bytes_is_reported_as_content(self) -> None:
        altered = bytearray(RETAIL)
        altered[999] ^= 0xFF
        (self.roms / "dungeon-master-usa.sfc").write_bytes(bytes(altered))

        found = ident.diagnose(self.usa(), self.manifest, self.roms)

        self.assertEqual(found.state, ident.STATE_WRONG_CONTENT)
        self.assertTrue(ident.blocking(found))

    def test_a_known_bad_dump_is_named_as_corrupt_rather_than_wrong(self) -> None:
        (self.roms / "dungeon-master-usa.sfc").write_bytes(CORRUPT)

        found = ident.diagnose(self.usa(), self.manifest, self.roms)

        self.assertEqual(found.state, ident.STATE_KNOWN_BAD)
        self.assertIn("zeroed", found.detail)

    def test_another_entry_under_the_wrong_filename_is_identified(self) -> None:
        (self.roms / "dungeon-master-usa.sfc").write_bytes(OTHER)

        found = ident.diagnose(self.usa(), self.manifest, self.roms)

        self.assertEqual(found.state, ident.STATE_OTHER_ENTRY)
        self.assertIn("Japan", found.detail)

    def test_an_entry_with_no_published_digest_never_blocks(self) -> None:
        found = ident.diagnose(
            artifact_named(self.manifest, "dungeon-master-eur.sfc"), self.manifest, self.roms
        )

        self.assertEqual(found.state, ident.STATE_UNDECLARED)
        self.assertFalse(ident.blocking(found))


class ExplainTest(unittest.TestCase):
    @override
    def setUp(self) -> None:
        self.manifest = manifest_fixture()
        self.tmp = tempfile.TemporaryDirectory()
        self.roms = Path(self.tmp.name)
        self.addCleanup(self.tmp.cleanup)

    def mismatch(self) -> Any:
        (self.roms / "dungeon-master-usa.sfc").write_bytes(RETAIL[:4096])
        return ident.diagnose(
            artifact_named(self.manifest, "dungeon-master-usa.sfc"), self.manifest, self.roms
        )

    def test_a_mismatch_prints_the_digest_it_computed(self) -> None:
        found = self.mismatch()

        text = ident.explain(found)

        self.assertIn(found.identity.sha256, text)

    def test_a_mismatch_prints_a_command_for_every_operating_system(self) -> None:
        found = self.mismatch()

        text = ident.explain(found)

        for label, _ in ident.DIGEST_COMMANDS:
            self.assertIn(label, text)

    def test_a_correct_dump_does_not_print_repair_advice(self) -> None:
        (self.roms / "dungeon-master-usa.sfc").write_bytes(RETAIL)
        found = ident.diagnose(
            artifact_named(self.manifest, "dungeon-master-usa.sfc"), self.manifest, self.roms
        )

        text = ident.explain(found)

        self.assertNotIn("PowerShell", text)


class RunTest(unittest.TestCase):
    @override
    def setUp(self) -> None:
        self.manifest = manifest_fixture()
        self.tmp = tempfile.TemporaryDirectory()
        self.roms = Path(self.tmp.name)
        self.addCleanup(self.tmp.cleanup)

    def test_every_artifact_is_reported(self) -> None:
        findings = ident.run(self.manifest, self.roms)

        self.assertEqual(len(findings), len(self.manifest["artifacts"]))

    def test_a_filename_filter_narrows_the_report(self) -> None:
        findings = ident.run(self.manifest, self.roms, wanted=("dungeon-master-usa.sfc",))

        self.assertEqual(len(findings), 1)
        self.assertEqual(findings[0].filename, "dungeon-master-usa.sfc")


class ShippedManifestTest(unittest.TestCase):
    @override
    def setUp(self) -> None:
        self.manifest = ident.read_manifest()

    def test_the_shipped_manifest_names_sha256_as_the_decider(self) -> None:
        self.assertEqual(self.manifest["decides"], "sha256")

    def test_every_artifact_declares_a_filename_and_provenance(self) -> None:
        for artifact in self.manifest["artifacts"]:
            self.assertTrue(artifact["filename"])
            self.assertTrue(artifact["provenance"])

    def test_every_published_digest_carries_a_size_and_a_sha256(self) -> None:
        for artifact in self.manifest["artifacts"]:
            for accepted in artifact["accepted"]:
                self.assertIn("size", accepted)
                self.assertEqual(len(accepted["sha256"]), 64)

    def test_every_dump_this_project_reads_has_digests_published(self) -> None:
        without = [a["filename"] for a in self.manifest["artifacts"] if not a["accepted"]]

        self.assertEqual(without, [])

    def test_and_the_two_retail_dumps_are_among_them(self) -> None:
        named = [a["filename"] for a in self.manifest["artifacts"]]

        self.assertIn("sfa2-usa-final.sfc", named)
        self.assertIn("sfz2-jp-final.sfc", named)

    def test_no_digest_repeats_across_artifacts(self) -> None:
        seen = [
            accepted["sha256"]
            for artifact in self.manifest["artifacts"]
            for accepted in artifact["accepted"]
        ]

        self.assertEqual(len(seen), len(set(seen)))

    def test_the_manifest_is_valid_json_on_disk(self) -> None:
        raw = json.loads(ident.MANIFEST_PATH.read_text())

        self.assertIn("artifacts", raw)


class EntryTest(unittest.TestCase):
    """A run from the command line, with the manifest passed in."""

    def _manifest(self, artifacts: list[Any]) -> dict[str, Any]:
        return {"decides": "sha256", "artifacts": artifacts, "known_bad": [], "not_this": []}

    def _artifact(
        self, filename: str = "nothing-here.sfc", accepted: Sequence[Any] = ()
    ) -> dict[str, Any]:
        return {
            "name": "Something",
            "filename": filename,
            "accepted": list(accepted),
            "provenance": "made up",
        }

    def test_a_name_nothing_matches_is_reported_rather_than_passing(self) -> None:
        complained: list[Any] = []

        code = ident.main(
            ["identify.py", "nothing-at-all.sfc"],
            manifest=self._manifest([self._artifact()]),
            say=lambda _l: None,
            complain=complained.append,
        )

        self.assertEqual(code, 2)
        self.assertIn("no artifact", complained[0])

    def test_a_dump_that_is_not_here_is_reported_and_fails(self) -> None:
        said: list[Any] = []

        code = ident.main(
            ["identify.py"],
            manifest=self._manifest([self._artifact(accepted=[{"size": 1, "sha256": "ab" * 32}])]),
            say=said.append,
        )

        self.assertEqual(code, 1)
        self.assertIn("missing", " ".join(said))

    def test_a_manifest_with_no_digests_yet_says_so(self) -> None:
        said: list[Any] = []

        ident.main(["identify.py"], manifest=self._manifest([self._artifact()]), say=said.append)

        self.assertIn("no digest published", " ".join(said))

    def test_every_line_it_prints_names_the_file_it_is_about(self) -> None:
        said: list[Any] = []

        ident.main(["identify.py"], manifest=self._manifest([self._artifact()]), say=said.append)

        self.assertIn("nothing-here.sfc", said[0])


class HintTest(unittest.TestCase):
    """What to do about a dump that is here and wrong, which is the useful case."""

    def _finding(self, state: str) -> Any:
        return ident.Finding("Something", "a.sfc", state, "", None, None)

    def test_a_file_of_the_wrong_size_suggests_a_copier_header_or_a_split_set(self) -> None:
        self.assertIn("copier", ident.repair_hint(self._finding(ident.STATE_WRONG_SIZE)))

    def test_a_file_of_the_wrong_content_names_what_it_might_be(self) -> None:
        self.assertIn("revision", ident.repair_hint(self._finding(ident.STATE_WRONG_CONTENT)))

    def test_a_file_that_is_another_entry_says_to_rename_it(self) -> None:
        self.assertIn("rename", ident.repair_hint(self._finding(ident.STATE_OTHER_ENTRY)))

    def test_a_known_bad_dump_says_to_find_another_copy(self) -> None:
        self.assertIn("another copy", ident.repair_hint(self._finding(ident.STATE_KNOWN_BAD)))

    def test_and_a_dump_that_is_right_needs_no_hint(self) -> None:
        self.assertEqual(ident.repair_hint(self._finding(ident.STATE_OK)), "")


if __name__ == "__main__":
    unittest.main(verbosity=2)
