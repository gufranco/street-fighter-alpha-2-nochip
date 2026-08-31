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


spcfast = _load("spcfast")

INITIALS = b"KAJ"

BUTTON_Y = 0x4000
BUTTON_START = 0x1000
BUTTON_X = 0x0040
BUTTON_L = 0x0020
COMBINATION = BUTTON_L | BUTTON_X | BUTTON_Y | BUTTON_START

UNLOCK_FLAG = 0x1B09
UNLOCK_VALUE = 0x4A4B

GATE = bytes(
    [
        0x08,
        0xC2,
        0x30,
        0xAD,
        0x05,
        0x1B,
        0x10,
        0x27,
        0xAD,
        0x09,
        0x1B,
        0xC9,
        0x4B,
        0x4A,
        0xF0,
        0x1F,
        0xAF,
        0x04,
        0xFE,
        0x7E,
        0xC9,
        0x4B,
        0x41,
        0xD0,
        0x16,
        0xAF,
        0x05,
        0xFE,
        0x7E,
        0xC9,
        0x41,
        0x4A,
        0xD0,
        0x0D,
        0xA5,
        0xB0,
        0xC9,
        0x60,
        0x50,
        0xD0,
        0x06,
        0xA9,
        0x4B,
        0x4A,
        0x8D,
        0x09,
        0x1B,
    ]
)

PRECONDITION = 3
SET_FLAG = 0x29
BRANCH = bytes([0x80, SET_FLAG - (PRECONDITION + 2)])


def find_gate(rom: bytes | bytearray) -> int | None:
    found = []
    position = rom.find(GATE)
    while position != -1:
        found.append(position)
        position = rom.find(GATE, position + 1)
    if len(found) > 1:
        raise ValueError(f"the unlock gate appears {len(found)} times, expected one")
    return found[0] if found else None


def is_patched(rom: bytes | bytearray) -> bool:
    if find_gate(rom) is not None:
        return False
    probe = bytearray(GATE)
    probe[PRECONDITION : PRECONDITION + 2] = BRANCH
    return rom.find(bytes(probe)) != -1


def apply(rom: bytes | bytearray) -> bytes:
    if is_patched(rom):
        return bytes(rom)

    gate = find_gate(rom)
    if gate is None:
        raise ValueError("no Shin Akuma unlock gate found")

    patched = bytearray(rom)
    site = gate + PRECONDITION
    patched[site : site + 2] = BRANCH
    return bytes(spcfast.write_checksum(patched))


def main(
    argv: list[str],
    say: Callable[[str], None] = print,
    complain: Callable[[str], None] | None = None,
) -> int:
    """The command line, with both streams passed in so a run can be checked."""
    complain = say if complain is None else complain
    if len(argv) != 3:
        complain("usage: shinakuma.py <source-rom> <output-rom>")
        return 2

    source, output = Path(argv[1]), Path(argv[2])
    if source.resolve() == output.resolve():
        complain("refusing to patch the source ROM in place")
        return 1

    rom = source.read_bytes()
    patched = apply(rom)
    output.write_bytes(patched)

    gate = find_gate(rom)
    if gate is None:
        say("unlock gate   already removed, so this image was patched before")
    else:
        say(f"unlock gate   {gate:#08x}")
        say(f"branch site   {gate + PRECONDITION:#08x}  {BRANCH.hex(' ')}")
    say(f"[done] {output} ({len(patched):,} bytes)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
