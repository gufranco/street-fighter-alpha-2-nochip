import sys
from collections.abc import Callable
from pathlib import Path

ROOT = Path(__file__).resolve().parent

TABLE_ADDRESS = 0x5F0000
TABLE_SIZE = 0xC1 * 0x40 * 2
TABLE_DESTINATION = 0x9440

TABLE_START = 0x004B7A00
TABLE_STEP = 0x00011820
TABLE_ROWS = 0xC1
TABLE_COLUMNS = 0x40
TABLE_START_STRIDE = 0x8C10
TABLE_STEP_STRIDE = 0x02EB

BUILDER_SIGNATURE = bytes.fromhex(
    "08c230a20000a9007a8510a94b008512a92018 8514a90100 8516".replace(" ", "")
)

FILLER_FILE = 0x07F593
FILLER_END = 0x07F600
FILLER_SIZE = FILLER_END - FILLER_FILE
ROUTINE_ADDRESS = 0xC00000 + FILLER_FILE

ROUTINE = bytes.fromhex(
    "0878c230a940948f812100e220a9008f8321008f004300a9808f014300a95f8f044300"
    "c220a900008f024300a980608f054300e220a9018f0b420028 6b".replace(" ", "")
)

JSL = 0x22
WINDOW_FIRST_BANK = 0xC0


def table() -> bytes:
    out = bytearray()
    start = TABLE_START
    step = TABLE_STEP
    for _ in range(TABLE_ROWS):
        value = start
        for _ in range(TABLE_COLUMNS):
            out += ((value >> 16) & 0xFFFF).to_bytes(2, "little")
            value = (value - step) & 0xFFFFFFFF
        start = (start + TABLE_START_STRIDE) & 0xFFFFFFFF
        step = (step - TABLE_STEP_STRIDE) & 0xFFFFFFFF
    return bytes(out)


def routine() -> bytes:
    return ROUTINE


def find_builder(rom: bytes | bytearray) -> int | None:
    at = rom.find(BUILDER_SIGNATURE)
    if at == -1:
        return None
    if rom.find(BUILDER_SIGNATURE, at + 1) != -1:
        raise ValueError("the pre-fight table builder appears more than once")
    return at


def call_to(address: int) -> bytes:
    return bytes([JSL, address & 0xFF, (address >> 8) & 0xFF, (address >> 16) & 0xFF])


def find_callers(rom: bytes | bytearray, at: int | None = None) -> list[int]:
    at = find_builder(rom) if at is None else at
    if at is None:
        return []
    window = WINDOW_FIRST_BANK + (at >> 16)
    wanted = call_to((window << 16) | (at & 0xFFFF))
    found, position = [], rom.find(wanted)
    while position != -1:
        found.append(position)
        position = rom.find(wanted, position + 1)
    return found


def is_patched(rom: bytes | bytearray) -> bool:
    if rom[FILLER_FILE : FILLER_FILE + len(ROUTINE)] != ROUTINE:
        return False
    return not find_callers(rom)


def apply(rom: bytes | bytearray) -> bytes:
    if is_patched(rom):
        return bytes(rom)

    at = find_builder(rom)
    if at is None:
        raise ValueError("no pre-fight table builder found")
    callers = find_callers(rom, at)
    if not callers:
        raise ValueError("the builder is never called, so there is nothing to redirect")
    if set(rom[FILLER_FILE:FILLER_END]) != {0xFF}:
        raise ValueError("the filler the routine needs is not free")

    patched = bytearray(rom)
    patched[FILLER_FILE : FILLER_FILE + len(ROUTINE)] = ROUTINE
    redirect = call_to(ROUTINE_ADDRESS)
    for site in callers:
        patched[site : site + len(redirect)] = redirect
    return bytes(patched)


def report(rom: bytes | bytearray, say: Callable[[str], None] = print) -> None:
    """What the patch found in this cartridge, or that it found nothing.

    The stream is a parameter so a run can be read back rather than watched.
    """
    at = find_builder(rom)
    if at is None:
        say("  no pre-fight table builder in this ROM")
        return
    say(f"  builder   ${WINDOW_FIRST_BANK + (at >> 16):02X}:{at & 0xFFFF:04X}  file ${at:06X}")
    for site in find_callers(rom, at):
        say(f"  caller    ${WINDOW_FIRST_BANK + (site >> 16):02X}:{site & 0xFFFF:04X}")
    say(f"  routine   ${ROUTINE_ADDRESS:06X}  {len(ROUTINE)} bytes")
    say(
        f"  table     ${TABLE_ADDRESS:06X}  "
        f"{TABLE_SIZE:,} bytes to work RAM ${TABLE_DESTINATION:04X}"
    )


def main(
    argv: list[str],
    say: Callable[[str], None] = print,
    complain: Callable[[str], None] | None = None,
) -> int:
    """The command line, with both streams passed in so a run can be checked."""
    complain = say if complain is None else complain
    if len(argv) != 3:
        complain("usage: prefight.py <source-rom> <output-rom>")
        return 2

    source, output = Path(argv[1]), Path(argv[2])
    if source.resolve() == output.resolve():
        complain("refusing to patch the source ROM in place")
        return 1

    rom = source.read_bytes()
    report(rom, say)
    output.write_bytes(apply(rom))
    say(f"[done] {output} ({output.stat().st_size:,} bytes)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
