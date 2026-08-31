import importlib.util
import sys
from collections import namedtuple
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

Fix = namedtuple("Fix", "name regions stock patched note")

FIXES = (
    Fix(
        name="thrown father sprite",
        regions=("usa", "jp"),
        stock=bytes.fromhex("fe280e00fe300f0020341c00203c0a01103808010628060107180401"),
        patched=bytes.fromhex("fe280e00fe300f0020301c0020380a01103408010628060107180401"),
        note=(
            "Sprite layout for the frame where Sagat holds Dan's father, at file $3EA95E, "
            "byte identical in both regional ROMs. Each record is four bytes: X offset, Y "
            "offset, tile number, attributes. Three of the six records sit four pixels below "
            "where they belong, so the held body separates from the arms. The three Y offsets "
            "$34, $3C and $38 become $30, $38 and $34. Nothing else in the run changes, and "
            "the run is carried whole so a mismatch anywhere in it refuses the patch rather "
            "than writing into the wrong table."
        ),
    ),
    Fix(
        name="sodom name on the life bar",
        regions=("usa",),
        stock=bytes.fromhex("1300061910046d0006231004270006"),
        patched=bytes.fromhex("1300061910041d0006231004270006"),
        note=(
            "Name plate records under the life bar, at file $0088C0. Each record is a video "
            "memory address and a length in tiles. The USA build points Sodom's plate at tile "
            "$6D, which is the name that release shipped him under; the Japanese build points "
            "at $1D and needs no change, which is why this fix reads as already applied there. "
            "Only the one record moves. The Charlie plate is deliberately left alone, since "
            "that name is the one the USA arcade release used."
        ),
    ),
    Fix(
        name="sodom name on the select screen",
        regions=("usa",),
        stock=bytes.fromhex("2700062d01046d0006350006"),
        patched=bytes.fromhex("2700062d01041d0006350006"),
        note=(
            "The same name plate on the character select screen, at file $00D68C. The table "
            "has the same record shape and the same asymmetry between the regions: the USA "
            "build points at tile $6D and the Japanese one already at $1D."
        ),
    ),
    Fix(
        name="sodom name on the vs screen",
        regions=("usa",),
        stock=bytes.fromhex(
            "5c25142515250025012526252725002501251a251b25002501255c255c25"
            "48254925342535255a255b25342535254e254f25342535255c25"
        ),
        patched=bytes.fromhex(
            "5c255c25242525251c251d25062507251c251d25182519255c255c255c25"
            "5c2558255925502551253a253b25502551254c254d255c255c25"
        ),
        note=(
            "The name under the portrait on the screen that introduces the match, at file "
            "$002260. Unlike the two plates above this is not a pointer but the drawn name "
            "itself, a tilemap of sixteen-bit entries whose low byte is a tile and whose high "
            "byte is $25 throughout. Each letter is two tiles, a top and a bottom, so the "
            "fourteen entries of the first row and the fourteen of the second are read "
            "together. The USA build spells the six-letter name that release used and the "
            "replacement spells the five-letter one, which is why two more entries become the "
            "blank tile $5C. The Japanese build already carries the replacement byte for byte, "
            "so this fix reads as already applied there, exactly like the two plates."
        ),
    ),
    Fix(
        name="sodom name on the vs results screen",
        regions=("usa",),
        stock=bytes.fromhex(
            "30f000c0000000000000000000d52ab3b9feddd7cf8893dffb8c2432f766efda"
            "084ffdff30a4fe9fe6d66b63aaed40b5fe1c47f4862c5f4fd444000000332885"
            "1edfdf1f67e0137265ffbb5f779600924c6df9df1bdebe3ffd691f01cc892b5b"
            "f9ebf9ffcf807c92da79dff8b380849f76f7bcaffecfee5fc01cf276e5f5dc4e"
            "c034e39ff3b7ffcfebd2f90ed603c52782f85dfb3fbd8bd5bc002d7acdd9ff28"
            "d71e040e513c3ffcdcb7f7e7f63000758e3978ffba4fe400d896bf75f7f9c03e"
            "12acde3ebd5cbdf2f6ce80353b15dbf38ebdd1dbe5de0037bebfe7ff5e00ba8e"
            "6bf4ffd7c755fcff7804e85372b75fd7eab7ade0ed5fc00000001cf5f453bff8"
            "fd78beeb400000000000"
        ),
        patched=bytes.fromhex(
            "30f000c0000000000000000000d52ab3b9feddd7cf8893dffb8c2432f766efda"
            "084ffdff30a4fe9fe6d66b63aaed40b5fe1c47f4862c5f4fd444000000332885"
            "1edfdf1f67e0137265ffbb5f779600924c6df9df1bdebe3ffd691f01cc892b5b"
            "f9ebf9ffcf807c92da79dff8b380849f76f7bcaffecfee5fc01cf276e5f5dc5e"
            "c01c73bfe7e7e6fff47f4034db6f2fdf6e1fa7d6f8bfbc00ec8569f8e2fd77de"
            "070b2bff787f6fbe66f9f87e0095f5537bf87e5d7c01918e6bedfe7f00c18d44"
            "f1f75eff36f9b23a0105ee4f6fc8d7bb1f6f96fc003bebf97ffd7802ea39afd9"
            "ffaf1c5fe7ef004e853e95b5fd7eab7ade0eedfc000000004a3ab797bfe3f5e1"
            "ff5fa000000000000000"
        ),
        note=(
            "The names on the screen of statistics that follows a match, at file $1AB82E. "
            "This one is compressed, so the run carried here is the compressed stream rather "
            "than the drawn text, and what it decodes to is six characters of plain text "
            "inside 2,048 bytes: the six-letter name becomes the five-letter one and a space. "
            "Two lengths bound this run and neither is the one the decoder reports. The "
            "replacement occupies 260 bytes and the decoder reads 264 of them, so the six "
            "bytes past the replacement are read as compressed data and have to be written as "
            "zero rather than left alone: leaving the original bytes decodes 160 later bytes "
            "wrongly and filling with $FF decodes 243 wrongly, while zero decodes all 2,048 "
            "exactly as intended. The run then stops at 266 bytes because the next stream "
            "begins there, and a run of 267 would write a zero over its first byte. The "
            "Japanese build carries a different stream here with its own names, so this fix "
            "does not reach it and reads as absent rather than as already applied."
        ),
    ),
    Fix(
        name="object table overflow",
        regions=("usa", "jp"),
        stock=bytes.fromhex("a628a0000c8420b5a1f005a0000e8420"),
        patched=bytes.fromhex("a628a0000cd687b5a1f003a0000e8420"),
        note=(
            "The path taken when the game wants a ninth shadow frame and all eight slots are "
            "full, at file $057537 in the USA ROM and $057546 in the Japanese one. It gives up "
            "on finding a free slot and overwrites the first, but the routine goes on to "
            "increment the count of live objects as though it had added one. The count then "
            "exceeds the number of objects that actually exist, and the projectile against "
            "player collision search walks past the end of the table it is scanning. The "
            "increment is real and reachable: it sits at $0575AA here and $0575B9 there, the "
            "same distance past the site in both. The fix decrements the count here so the "
            "later increment leaves it where it started. Three bytes move inside sixteen, and "
            "the run stays its own length: the first of the two stores is dropped to make room "
            "for the decrement, the remaining store moves below the branch, and the branch "
            "shortens from five to three to match."
        ),
    ),
    Fix(
        name="akuma win pose order",
        regions=("usa", "jp"),
        stock=bytes.fromhex("90039e03c403da03"),
        patched=bytes.fromhex("260490039e03da03"),
        note=(
            "Which pose Akuma strikes after a win, at file $020048 in both regions. Four "
            "sixteen-bit entries pick the animation. The arcade opens with the taunt, so $0426 "
            "goes in front and the three that follow shift down by one, which pushes the entry "
            "the release never reaches out of the table. The two the arcade repeats in the "
            "fifth and sixth slots are already the taunt, so nothing past this run moves. Both "
            "regional ROMs carry this table byte for byte at the same address."
        ),
    ),
    Fix(
        name="akuma silent win pose index",
        regions=("usa", "jp"),
        stock=bytes.fromhex("b578c901f004"),
        patched=bytes.fromhex("b578c902f004"),
        note=(
            "The one byte that has to move with the table above, at file $01E946 in the USA "
            "ROM and $01E95F in the Japanese one. The pose that shushes without a sound needs "
            "separate handling, and the code finds it by index rather than by pointer: it "
            "loads the pose number and compares against a literal. Reordering the table moves "
            "that pose from second to third, so the literal goes from $01 to $02. Applying "
            "either of these two fixes without the other leaves the code special-casing the "
            "wrong pose, which is why the run carries the load and the branch around the "
            "compare rather than the compare alone."
        ),
    ),
)

VS_RESULTS_LENGTH = 2048

EmptyCall = namedtuple("EmptyCall", "name target note")

JSL = 0x22
RTS = 0x60
RTL = 0x6B

EMPTY_CALLS = (
    EmptyCall(
        name="empty routine at $FF:FF4D",
        target=0xFFFF4D,
        note=(
            "The routine at $FF:FF4D is a single rtl and does nothing else. Every one of the "
            "42 jsl instructions that reach it is immediately followed by rts, so the call "
            "and its return are the only work either instruction performs. Replacing the jsl "
            "opcode with rts returns from the caller at that point instead, which is where "
            "control was going anyway, and saves the eight cycles of the call plus the six of "
            "the return. The three operand bytes are left where they are, so any branch that "
            "targets the rts after them still lands on an rts."
        ),
    ),
    EmptyCall(
        name="empty routine at $F0:1EEF",
        target=0xF01EEF,
        note=(
            "A third empty routine, found by searching for every long call in the ROM whose "
            "target byte is rtl and whose own next byte is rts, rather than by taking the two "
            "gizaha names. One call site reaches it in each region. The search also asked the "
            "same question of short calls within a bank and found none."
        ),
    ),
    EmptyCall(
        name="empty routine at $FF:FEA1",
        target=0xFFFEA1,
        note=(
            "The same shape at a second empty routine. Three jsl instructions reach it and "
            "two of them are followed by rts; only those two are rewritten. The third is left "
            "alone because what follows it is not a return, so the call there is not the whole "
            "of what the instruction does."
        ),
    ),
)

APPLIED = "applied"
ALREADY = "already"
ABSENT = "absent"


WINDOW_FIRST_BANK = 0xC0


def long_to_file(address: int) -> int:
    bank = ((address >> 16) & 0xFF) - WINDOW_FIRST_BANK
    return (bank << 16) | (address & 0xFFFF)


def call_run(target: int) -> bytes:
    return bytes([JSL, target & 0xFF, (target >> 8) & 0xFF, (target >> 16) & 0xFF, RTS])


def retired_run(target: int) -> bytes:
    return bytes([RTS]) + call_run(target)[1:]


def empty_call_sites(rom: bytes | bytearray, call: EmptyCall) -> list[int]:
    run = call_run(call.target)
    found, position = [], rom.find(run)
    while position != -1:
        found.append(position)
        position = rom.find(run, position + 1)
    if not found:
        return found
    at = long_to_file(call.target)
    if at >= len(rom) or rom[at] != RTL:
        raise ValueError(f"{call.name} is not a bare rtl, so its calls are not free to retire")
    return found


def retired_sites(rom: bytes | bytearray, call: EmptyCall) -> list[int]:
    run = retired_run(call.target)
    found, position = [], rom.find(run)
    while position != -1:
        found.append(position)
        position = rom.find(run, position + 1)
    return found


def locate(rom: bytes | bytearray, run: bytes) -> int | None:
    first = rom.find(run)
    if first == -1:
        return None
    if rom.find(run, first + 1) != -1:
        raise ValueError(f"the run {run.hex()} appears more than once")
    return first


def survey(rom: bytes | bytearray) -> dict[str, str]:
    found = {}
    for fix in FIXES:
        if locate(rom, fix.stock) is not None:
            found[fix.name] = APPLIED
        elif locate(rom, fix.patched) is not None:
            found[fix.name] = ALREADY
        else:
            found[fix.name] = ABSENT
    for call in EMPTY_CALLS:
        if empty_call_sites(rom, call):
            found[call.name] = APPLIED
        elif retired_sites(rom, call):
            found[call.name] = ALREADY
        else:
            found[call.name] = ABSENT
    return found


def changed_bytes(rom: bytes | bytearray) -> int:
    total = 0
    for fix in FIXES:
        if locate(rom, fix.stock) is None:
            continue
        total += sum(
            1 for before, after in zip(fix.stock, fix.patched, strict=True) if before != after
        )
    for call in EMPTY_CALLS:
        total += len(empty_call_sites(rom, call))
    return total


def apply(rom: bytes | bytearray, found: dict[str, str] | None = None) -> bytes:
    """Apply every fix this cartridge can take, and refuse if it can take none.

    The survey is a parameter so the guard against a run that was there when the
    cartridge was surveyed and is not there when it is patched can be driven. One
    fix overwriting another's stock bytes is the way that happens for real.
    """
    found = survey(rom) if found is None else found
    if all(state == ABSENT for state in found.values()):
        raise ValueError("this ROM carries none of the sites these fixes name")
    if all(state != APPLIED for state in found.values()):
        return bytes(rom)

    patched = bytearray(rom)
    for fix in FIXES:
        if found[fix.name] != APPLIED:
            continue
        at = locate(patched, fix.stock)
        if at is None:
            raise ValueError(f"the run {fix.name} names was there at survey and is not now")
        patched[at : at + len(fix.stock)] = fix.patched
    for call in EMPTY_CALLS:
        for at in empty_call_sites(patched, call):
            patched[at] = RTS
    return bytes(spcfast.write_checksum(patched))


def report(rom: bytes | bytearray, say: Callable[[str], None] = print) -> None:
    found = survey(rom)
    for fix in FIXES:
        at = locate(rom, fix.stock) or locate(rom, fix.patched)
        where = f"{at:#08x}" if at is not None else "not present"
        say(f"  {fix.name:<32} {found[fix.name]:<8} {where}  regions {', '.join(fix.regions)}")
    for call in EMPTY_CALLS:
        sites = empty_call_sites(rom, call) or retired_sites(rom, call)
        say(f"  {call.name:<32} {found[call.name]:<8} {len(sites)} call sites")
    say(f"  {changed_bytes(rom)} bytes to change across {len(FIXES) + len(EMPTY_CALLS)} entries")


def main(
    argv: list[str],
    say: Callable[[str], None] = print,
    complain: Callable[[str], None] | None = None,
) -> int:
    """The command line, with both streams passed in so a run can be checked."""
    complain = say if complain is None else complain
    if len(argv) != 3:
        complain("usage: gamefixes.py <source-rom> <output-rom>")
        return 2

    source, output = Path(argv[1]), Path(argv[2])
    if source.resolve() == output.resolve():
        complain("refusing to patch the source ROM in place")
        return 1

    rom = source.read_bytes()
    report(rom, say)
    patched = apply(rom)
    output.write_bytes(patched)
    say(f"[done] {output} ({len(patched):,} bytes)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
