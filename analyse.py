import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

import hardware

dump = hardware.load("romimage").dump


BLOCK = 65536
COMPRESSED_RATIO = 0.85


def compressed_share(data, block=BLOCK, threshold=COMPRESSED_RATIO):
    ratios = dump.block_ratios(data, block)
    hits = sum(1 for r in ratios if r > threshold)
    return hits, len(ratios), ratios


def novelty(candidate, reference, chunk=1024):
    index = dump.chunk_index(reference, chunk=chunk, stride=512)
    new = total = 0
    for i in range(0, len(candidate) - chunk + 1, chunk):
        total += 1
        if candidate[i : i + chunk] not in index:
            new += 1
    return new, total


def estimate_expanded(compressed_bytes, total_bytes, ratio):
    return int(total_bytes + compressed_bytes * (ratio - 1))


def mbit(size):
    return size * 8 / 1048576


def report(label, data):
    hits, blocks, _ = compressed_share(data)
    comp_bytes = hits * BLOCK
    print(
        f"  {label:34} {len(data):>11,} bytes ({mbit(len(data)):>5.1f} Mbit)   "
        f"compressed-looking {hits:>3}/{blocks:<3} = {comp_bytes:>10,} bytes"
    )
    return comp_bytes


def main() -> int:
    roms = {}
    for name, path in [
        ("so_orig", sys.argv[1]),
        ("so_patched", sys.argv[2]),
        ("sfa2_final", sys.argv[3]),
        ("sfa2_proto", sys.argv[4]),
    ]:
        p = Path(path)
        roms[name] = dump.read(p)

    print("== size and compressed-region profile")
    report("Star Ocean original (chip)", roms["so_orig"])
    report("Star Ocean patched (no chip)", roms["so_patched"])
    sfa_comp = report("SFA2 final (chip)", roms["sfa2_final"])
    report("SFA2 prototype (no chip)", roms["sfa2_proto"])

    print("\n== what the Star Ocean patch actually added")
    new, total = novelty(roms["so_patched"], roms["so_orig"])
    new_bytes = new * 1024
    print(f"  1K chunks in the patched build absent from the original: {new:,}/{total:,}")
    print(f"  new data: {new_bytes:,} bytes ({mbit(new_bytes):.1f} Mbit)")

    whole_rom = len(roms["so_patched"]) / len(roms["so_orig"])
    print(f"  whole-ROM growth factor: {whole_rom:.2f}x  (48 Mbit -> 96 Mbit)")
    print("  note: the patch KEEPS the compressed data and appends the decompressed copy,")
    print(
        f"        so new data ({new_bytes:,} bytes) is the decompressed output, not a replacement."
    )

    print("\n== projection for SFA2")
    print(f"  whole-ROM analogue: {mbit(len(roms['sfa2_final']) * whole_rom):.1f} Mbit")
    for ratio in (2.0, 2.5, 3.0):
        out = estimate_expanded(sfa_comp, len(roms["sfa2_final"]), ratio)
        print(
            f"  at {ratio:.2f}x -> {out:>11,} bytes ({mbit(out):>5.1f} Mbit)"
            f"   fits 128 Mbit: {'yes' if mbit(out) <= 128 else 'NO'}"
        )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
