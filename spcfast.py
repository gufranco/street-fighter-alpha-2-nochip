import importlib.util
import sys
from collections.abc import Callable
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parent


def _load(name: str) -> Any:
    spec = importlib.util.spec_from_file_location(name, ROOT / f"{name}.py")
    assert spec is not None and spec.loader is not None, "no loader for that path"
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


DRIVER_BASE = 0x071C56
RECEIVE_LOOP = 0x0EBD
BLOCK_HEADER = 0x0EFF

CHECKSUM_FIELD = 0x007FDC
CHECKSUM_FIELD_SUM = 0x01FE

BLANK_GATE = bytes([0xAF, 0x12, 0x42, 0x00, 0x29, 0xC0, 0xF0, 0xF8])

STOCK_PROBE = (
    (0x072B13, bytes([0xEC, 0xF4, 0x00, 0x5E, 0xF4, 0x00, 0xD0, 0xF8])),
    (0x07046D, bytes([0x01])),
    (0x070222, BLANK_GATE),
)

PATCH = (
    (0x070222, bytes.fromhex("eaeaeaeaeaeaeaea")),
    (0x070241, bytes.fromhex("eaeaeaeaeaeaeaea")),
    (0x07025F, bytes.fromhex("eaeaeaeaeaeaeaea")),
    (0x0702B2, bytes.fromhex("eaeaeaeaeaeaeaea")),
    (0x0702D1, bytes.fromhex("eaeaeaeaeaeaeaea")),
    (0x0702EF, bytes.fromhex("eaeaeaeaeaeaeaea")),
    (0x070337, bytes.fromhex("eaeaeaeaeaeaeaea")),
    (0x070355, bytes.fromhex("eaeaeaeaeaeaeaea")),
    (0x070373, bytes.fromhex("eaeaeaeaeaeaeaea")),
    (0x0703C1, bytes.fromhex("eaeaeaeaeaeaeaea")),
    (0x0703E2, bytes.fromhex("eaeaeaeaeaeaeaea")),
    (0x070401, bytes.fromhex("eaeaeaeaeaeaeaea")),
    (0x070420, bytes.fromhex("eaeaeaeaeaeaeaea")),
    (0x07043B, bytes.fromhex("eaeaeaeaeaeaeaea")),
    (0x07046D, bytes.fromhex("03")),
    (0x070479, bytes.fromhex("eaeaeaeaeaeaeaea")),
    (0x070488, bytes.fromhex("4ceb04")),
    (0x070498, bytes.fromhex("eaeaeaeaeaeaeaea")),
    (0x0704B6, bytes.fromhex("eaeaeaeaeaeaeaea")),
    (
        0x0704EB,
        bytes.fromhex(
            "c230da3ba2e01f9a48a301aabf010000481a1a206b0548981863011863014898186303485aa3078f4221"
            "00e220a9008f402100cf402100d0fac230a307aaa00000e220b3018f412100b3038f422100b3058f4321"
            "00981a8f402100c8caf008cf402100d0fa80dcc230a301186309a8a307aa6868686868681b688ae2204c"
            "b504484a4a48a206004a4a48186303830368cad0f4a30338e30138e30138e301c903009007a3011a8301"
            "80e968fa60"
        ),
    ),
    (0x072B13, bytes.fromhex("eb")),
    (0x072B15, bytes.fromhex("d0fce4e66803f04c7e")),
    (0x072B1F, bytes.fromhex("d00de4f5cb")),
    (
        0x072B25,
        bytes.fromhex(
            "d714fcd0f3ab152fef10e72f237ef4f00410fa2f1be4f5d714f8f6e4f7cbf4d7ca7dd7c8fcd0e6ab15ab"
            "c9abcb2fde"
        ),
    ),
    (0x072B55, bytes.fromhex("e4")),
    (
        0x072B57,
        bytes.fromhex("ebf7da14ebf4e4f5c4e6cbf46800f0172faa1a14baf67a14dac87af6daca8d00cb"),
    ),
    (0x072B79, bytes.fromhex("fc2fb6")),
)


JOYPAD_WAIT = bytes([0xAD, 0x12, 0x42, 0x4A, 0xB0, 0xFA])
FRAME_HOOK = bytes.fromhex("")
FRAME_HOOK_SITES = (0x000208, 0x00020C)


def frame_hook_site(rom: bytes | bytearray) -> int:
    for site in FRAME_HOOK_SITES:
        window = rom[site : site + len(JOYPAD_WAIT)]
        if window == JOYPAD_WAIT or window[: len(FRAME_HOOK)] == FRAME_HOOK:
            return site
    raise ValueError("the frame interrupt's joypad wait is at neither known position")


def runs_for(rom: bytes | bytearray) -> tuple[tuple[int, bytes], ...]:
    if not FRAME_HOOK:
        return PATCH
    return (*PATCH, (frame_hook_site(rom), FRAME_HOOK))


def checksum(rom: bytes | bytearray) -> int:
    zeroed = bytearray(rom)
    zeroed[CHECKSUM_FIELD : CHECKSUM_FIELD + 4] = bytes(4)
    return (sum(zeroed) + CHECKSUM_FIELD_SUM) & 0xFFFF


def write_checksum(rom: bytes | bytearray) -> bytes:
    stamped = bytearray(rom)
    value = checksum(stamped)
    complement = value ^ 0xFFFF
    stamped[CHECKSUM_FIELD : CHECKSUM_FIELD + 4] = bytes(
        [complement & 0xFF, complement >> 8, value & 0xFF, value >> 8]
    )
    return bytes(stamped)


def patch_bytes() -> int:
    return sum(len(data) for _, data in PATCH) + len(FRAME_HOOK)


def find_blank_gates(rom: bytes | bytearray) -> list[int]:
    found = []
    position = rom.find(BLANK_GATE, 0x070000)
    while position != -1 and position < 0x080000:
        found.append(position)
        position = rom.find(BLANK_GATE, position + 1)
    return found


def is_stock(rom: bytes | bytearray) -> bool:
    return all(rom[at : at + len(want)] == want for at, want in STOCK_PROBE)


def is_patched(rom: bytes | bytearray) -> bool:
    return all(rom[at : at + len(data)] == data for at, data in runs_for(rom))


def apply(rom: bytes | bytearray) -> bytes:
    if is_patched(rom):
        return bytes(rom)
    if not is_stock(rom):
        raise ValueError("this is not an unpatched retail Alpha 2 or Zero 2 ROM")

    patched = bytearray(rom)
    for at, data in runs_for(rom):
        patched[at : at + len(data)] = data
    return write_checksum(patched)


def main(
    argv: list[str],
    say: Callable[[str], None] = print,
    complain: Callable[[str], None] | None = None,
) -> int:
    """The command line, with both streams passed in so a run can be checked."""
    complain = say if complain is None else complain
    if len(argv) != 3:
        complain("usage: spcfast.py <source-rom> <output-rom>")
        return 2

    source, output = Path(argv[1]), Path(argv[2])
    if source.resolve() == output.resolve():
        complain("refusing to patch the source ROM in place")
        return 1

    rom = source.read_bytes()
    patched = apply(rom)
    output.write_bytes(patched)

    say(f"  driver        {DRIVER_BASE + RECEIVE_LOOP:#08x}  two bytes per handshake")
    say(f"  blank gates   {len(find_blank_gates(rom))} sites retired")
    say(f"  patch         {patch_bytes()} bytes in {len(runs_for(rom))} runs")
    say(f"[done] {output} ({len(patched):,} bytes)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
