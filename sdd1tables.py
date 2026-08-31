from collections import namedtuple
from typing import Any

SLOTS = 0x10000
EMPTY = 0x00
WINDOW_BASE = 0xC0
MAX_REPAIRS = 64

Tables = namedtuple("Tables", "key dest_low dest_high dest_bank slots")


class PlacementError(Exception):
    pass


def source_key(offset: int) -> tuple[int, int]:
    return WINDOW_BASE + (offset >> 16), offset & 0xFFFF


def _first_free(taken: dict[int, int], start: int) -> int:
    slot = start
    for _ in range(SLOTS):
        if slot not in taken:
            return slot
        slot = (slot + 1) & 0xFFFF
    raise PlacementError("the key table is full")


def _scan(table: dict[int, int], bank: int, addr: int) -> int | None:
    slot = addr
    for _ in range(SLOTS):
        if table.get(slot) == bank:
            return slot
        slot = (slot + 1) & 0xFFFF
    return None


def allocate(keys: list[tuple[int, int]]) -> list[int]:
    if len(keys) > SLOTS:
        raise PlacementError(f"{len(keys)} streams do not fit in {SLOTS} slots")

    order = sorted(range(len(keys)), key=lambda i: keys[i][1])
    placed: list[int] = [0] * len(keys)
    table: dict[int, int] = {}
    for index in order:
        bank, addr = keys[index]
        slot = _first_free(table, addr)
        table[slot] = bank
        placed[index] = slot

    for _ in range(MAX_REPAIRS):
        broken = [
            index
            for index, (bank, addr) in enumerate(keys)
            if _scan(table, bank, addr) != placed[index]
        ]
        if not broken:
            return placed
        for index in broken:
            bank, addr = keys[index]
            found = _scan(table, bank, addr)
            if found is None:
                continue
            del table[placed[index]]
            slot = _first_free(table, (found + 1) & 0xFFFF)
            table[slot] = bank
            placed[index] = slot

    raise PlacementError("could not find a placement where every scan is unambiguous")


def verify(keys: list[tuple[int, int]], placed: list[int]) -> None:
    table = {}
    for (bank, _), slot in zip(keys, placed, strict=True):
        if slot in table:
            raise PlacementError(f"slot {slot:#06x} used twice")
        table[slot] = bank

    for index, (bank, addr) in enumerate(keys):
        found = _scan(table, bank, addr)
        if found != placed[index]:
            raise PlacementError(
                f"stream {index} at ${bank:02X}:{addr:04X} scans to "
                f"{found if found is None else hex(found)}, not {placed[index]:#06x}"
            )


def build(pairs: list[tuple[Any, int]]) -> Tables:
    keys = [source_key(entry.source) for entry, _ in pairs]
    slots = allocate(keys)
    verify(keys, slots)

    key = bytearray(SLOTS)
    dest_low = bytearray(SLOTS)
    dest_high = bytearray(SLOTS)
    dest_bank = bytearray(SLOTS)

    for (bank, _), slot, (_, destination) in zip(keys, slots, pairs, strict=True):
        target_bank = destination >> 16
        if target_bank == 0:
            raise ValueError(
                f"destination {destination:#08x} is in bank $00, which the scan "
                "cannot tell from an empty slot"
            )
        key[slot] = bank
        dest_low[slot] = destination & 0xFF
        dest_high[slot] = (destination >> 8) & 0xFF
        dest_bank[slot] = target_bank

    return Tables(bytes(key), bytes(dest_low), bytes(dest_high), bytes(dest_bank), slots)
