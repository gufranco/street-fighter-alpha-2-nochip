import importlib.util
import random
import shutil
import subprocess
import sys
import unittest
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).resolve().parent))

import hardware

sdd1 = hardware.load("sdd1")
dump = hardware.load("romimage").dump


ROOT = Path(__file__).resolve().parent


def load_module(name: str) -> Any:
    spec = importlib.util.spec_from_file_location(name, ROOT / f"{name}.py")
    assert spec is not None and spec.loader is not None, "no loader for that path"
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


ref = load_module("sdd1ref")

STAR_OCEAN = ROOT / "roms" / "star-ocean-jp-original.sfc"
ALPHA2 = ROOT / "roms" / "sfa2-usa-final.sfc"


def docker_available():
    if not shutil.which("docker"):
        return False
    return (
        subprocess.run(["docker", "info"], capture_output=True, text=True, check=False).returncode
        == 0
    )


class WireFormatTest(unittest.TestCase):
    def test_a_request_carries_the_rom_then_every_case(self) -> None:
        rom = bytes(range(64))
        cases = [(0, 16), (32, 8)]

        blob = ref.encode_request(rom, cases)

        self.assertEqual(int.from_bytes(blob[:4], "little"), len(rom))
        self.assertEqual(blob[4 : 4 + len(rom)], rom)
        tail = blob[4 + len(rom) :]
        self.assertEqual(int.from_bytes(tail[:4], "little"), len(cases))
        self.assertEqual(int.from_bytes(tail[4:8], "little"), 0)
        self.assertEqual(int.from_bytes(tail[8:12], "little"), 16)

    def test_a_response_splits_on_the_requested_lengths(self) -> None:
        cases = [(0, 3), (10, 5)]

        parts = ref.decode_response(b"aaabbbbb", cases)

        self.assertEqual(parts, [b"aaa", b"bbbbb"])

    def test_a_zero_length_case_claims_a_full_64k_block(self) -> None:
        cases = [(0, 0)]

        parts = ref.decode_response(b"\x00" * sdd1.MAX_LENGTH, cases)

        self.assertEqual(len(parts[0]), sdd1.MAX_LENGTH)

    def test_a_short_response_is_rejected(self) -> None:
        with self.assertRaises(ValueError):
            ref.decode_response(b"aa", [(0, 3)])

    def test_a_length_above_a_64k_block_is_rejected(self) -> None:
        with self.assertRaises(ValueError):
            ref.encode_request(b"\x00" * 16, [(0, sdd1.MAX_LENGTH + 1)])

    def test_an_offset_outside_the_rom_is_rejected(self) -> None:
        with self.assertRaises(ValueError):
            ref.encode_request(b"\x00" * 16, [(16, 4)])


@unittest.skipUnless(docker_available(), "docker is not available")
@unittest.skipUnless(STAR_OCEAN.exists() and ALPHA2.exists(), "reference roms are not present")
class DifferentialTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        if ref.build_image() != 0:
            raise unittest.SkipTest("reference image failed to build")

    def assert_agrees(self, rom, cases):
        expected = ref.reference_outputs(rom, cases)

        for (offset, length), want in zip(cases, expected, strict=True):
            got = sdd1.decompress(rom, offset, length).data
            self.assertEqual(got, want, f"mismatch at offset {offset:#x}")

    def test_it_agrees_with_the_c_reference_on_arbitrary_star_ocean_offsets(self) -> None:
        rom = dump.read(STAR_OCEAN)
        rng = random.Random(20260813)
        cases = [
            (rng.randrange(len(rom) - 65536), rng.choice([1, 2, 15, 64, 832, 4096]))
            for _ in range(400)
        ]

        self.assert_agrees(rom, cases)

    def test_it_agrees_with_the_c_reference_on_every_header_configuration(self) -> None:
        rom = bytearray(dump.read(ALPHA2)[:262144])
        cases = []
        for index in range(16):
            offset = 4096 * (index + 1)
            rom[offset] = (index & 0x0F) << 4
            cases.append((offset, 2048))

        self.assert_agrees(bytes(rom), cases)

    def test_it_agrees_with_the_c_reference_on_a_full_64k_block(self) -> None:
        rom = dump.read(STAR_OCEAN)

        self.assert_agrees(rom, [(0x101010, 0)])


if __name__ == "__main__":
    unittest.main(verbosity=2)
