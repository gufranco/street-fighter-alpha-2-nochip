import importlib.util
import re
import unittest
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parent


def load_module(name: str) -> Any:
    spec = importlib.util.spec_from_file_location(name, ROOT / f"{name}.py")
    assert spec is not None and spec.loader is not None, "no loader for that path"
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


version = load_module("version")

SEMVER = re.compile(r"^\d+\.\d+\.\d+$")


class VersionTest(unittest.TestCase):
    def test_the_version_is_a_release_number(self) -> None:
        self.assertRegex(version.VERSION, SEMVER)

    def test_the_assignment_is_the_one_the_release_script_rewrites(self) -> None:
        source = (ROOT / "version.py").read_text()

        self.assertRegex(source, re.compile(r'^VERSION = "\d+\.\d+\.\d+"$', re.MULTILINE))


class StampedNameTest(unittest.TestCase):
    def test_the_name_carries_the_version(self) -> None:
        self.assertEqual(version.stamped("sfa2-usa-nochip", "1.2.3"), "sfa2-usa-nochip-v1.2.3.sfc")

    def test_the_shipped_version_is_the_default(self) -> None:
        self.assertIn(f"-v{version.VERSION}", version.stamped("x"))

    def test_a_development_build_is_marked_as_one(self) -> None:
        self.assertEqual(version.stamped("x", "0.0.0"), "x-v0.0.0-dev.sfc")


if __name__ == "__main__":
    unittest.main(verbosity=2)
