import re
import sys
from collections import defaultdict
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent

HDR = re.compile(r"^HDR pc=(\w+) src=(\w\w):(\w{4}) len=(\d+) dest=(\w{4})")
GROUP = re.compile(
    r"^GROUP frame=(\d+) pc=(\w+) group=(\w\w) ids=(\w\w),(\w\w),(\w\w) alloc=(\w{4}) key=(\w\w)"
    r"(?: list=(\w\w))?"
)

APU_RAM = 0x10000
SAMPLE_BASE = 0x1500
LOAD_START = 0xC70074
WALK_START = 0xC70103
GROUP_END = 0xC7018F
LONGEST_BLOCK = 0x8000
SPC_CYCLES_PER_BYTE = 16.3
SPC_CLOCK = 1024000


def events(lines):
    for line in lines:
        match = GROUP.match(line)
        if match:
            yield {
                "kind": "mark",
                "frame": int(match.group(1)),
                "pc": int(match.group(2), 16),
                "group": int(match.group(3), 16),
                "ids": tuple(int(match.group(n), 16) for n in (4, 5, 6)),
                "alloc": int(match.group(7), 16),
                "key": int(match.group(8), 16),
                "list": int(match.group(9), 16) if match.group(9) else None,
            }
            continue
        match = HDR.match(line)
        if match:
            yield {
                "kind": "block",
                "pc": int(match.group(1), 16),
                "bank": int(match.group(2), 16),
                "src": int(match.group(3), 16),
                "length": int(match.group(4)),
                "dest": int(match.group(5), 16),
            }


def loads(stream):
    current = None
    tail = []
    for event in stream:
        if event["kind"] == "block":
            if current is not None:
                tail.append(event)
            continue
        if event["pc"] == LOAD_START:
            if current is not None:
                yield current
            current = {"frame": event["frame"], "marks": [event], "blocks": [], "spans": []}
            tail = []
            continue
        if current is None:
            continue
        previous = current["marks"][-1]
        width = (event["alloc"] - previous["alloc"]) & 0xFFFF
        current["spans"].append(
            {
                "name": "base" if event["pc"] == WALK_START else event["group"],
                "width": 0 if width > LONGEST_BLOCK else width,
                "blocks": tail,
            }
        )
        current["blocks"].extend(tail)
        tail = []
        current["marks"].append(event)
    if current is not None:
        yield current


def spans(load):
    return [(span["name"], span["width"]) for span in load["spans"]]


def request(load):
    for mark in load["marks"]:
        if mark["pc"] == WALK_START:
            return mark["ids"]
    return None


def replay(runs):
    provenance = [None] * APU_RAM
    totals = {"loads": 0, "blocks": 0, "bytes": 0, "resident_blocks": 0, "resident_bytes": 0}
    per_load = []
    for run in runs:
        moved = 0
        resident = 0
        for span in run["spans"]:
            span["bytes"] = 0
            span["resident"] = 0
            for block in span["blocks"]:
                length = block["length"]
                if length == 0 or length > LONGEST_BLOCK:
                    continue
                tags = [(block["bank"], (block["src"] + step) & 0xFFFF) for step in range(length)]
                slots = [(block["dest"] + step) & 0xFFFF for step in range(length)]
                same = all(provenance[slot] == tag for slot, tag in zip(slots, tags, strict=True))
                for slot, tag in zip(slots, tags, strict=True):
                    provenance[slot] = tag
                moved += length
                span["bytes"] += length
                totals["blocks"] += 1
                totals["bytes"] += length
                if same:
                    resident += length
                    span["resident"] += length
                    totals["resident_blocks"] += 1
                    totals["resident_bytes"] += length
        totals["loads"] += 1
        per_load.append(
            {
                "frame": run["frame"],
                "bytes": moved,
                "resident": resident,
                "ids": request(run),
                "spans": spans(run),
            }
        )
    return totals, per_load


def group_costs(runs):
    costs = defaultdict(lambda: {"walks": 0, "bytes": 0})
    for run in runs:
        for name, width in spans(run):
            costs[name]["walks"] += 1
            costs[name]["bytes"] += width
    return costs


def base_span(run):
    for span in run["spans"]:
        if span["name"] == "base":
            return span
    return None


def base_identity(span):
    return tuple(
        (block["bank"], block["src"], block["length"], block["dest"]) for block in span["blocks"]
    )


def base_repeats(runs):
    found = {
        "loads": 0,
        "repeats": 0,
        "repeats_same_id": 0,
        "bytes": 0,
        "resident": 0,
        "resident_not_repeat": 0,
        "repeat_not_resident": 0,
    }
    previous = None
    previous_id = None
    for run in runs:
        span = base_span(run)
        if span is None or not span["bytes"]:
            continue
        found["loads"] += 1
        identity = base_identity(span)
        list_id = run["marks"][0]["list"]
        repeat = previous is not None and identity == previous
        resident = span["resident"] == span["bytes"]
        if repeat:
            found["repeats"] += 1
            found["bytes"] += span["bytes"]
            if list_id is not None and list_id == previous_id:
                found["repeats_same_id"] += 1
        if resident:
            found["resident"] += 1
        if resident and not repeat:
            found["resident_not_repeat"] += 1
        if repeat and not resident:
            found["repeat_not_resident"] += 1
        previous = identity
        previous_id = list_id
    return found


def seconds(count):
    return count * SPC_CYCLES_PER_BYTE / SPC_CLOCK


def report(name, text):
    runs = list(loads(events(text.splitlines())))
    totals, per_load = replay(runs)
    carrying = [entry for entry in per_load if entry["bytes"]]
    heavy = [entry for entry in carrying if entry["bytes"] >= 20000]
    heavy_resident = [entry for entry in heavy if entry["bytes"] == entry["resident"]]
    repeats = 0
    previous = None
    for entry in carrying:
        if (
            previous is not None
            and entry["ids"] == previous["ids"]
            and entry["bytes"] == entry["resident"]
        ):
            repeats += 1
        previous = entry
    share = 100.0 * totals["resident_bytes"] / totals["bytes"] if totals["bytes"] else 0.0
    print(f"  {name}")
    print(f"    engine loads {totals['loads']}, of which {len(carrying)} moved bytes")
    print(
        f"    blocks {totals['blocks']}, bytes {totals['bytes']}, "
        f"{seconds(totals['bytes']):.1f} s of driver time"
    )
    print(
        f"    already resident: {totals['resident_bytes']} bytes, {share:.1f}%, "
        f"{seconds(totals['resident_bytes']):.1f} s"
    )
    print(
        f"    pre-fight sized loads (>=20000 bytes) {len(heavy)}, "
        f"fully resident {len(heavy_resident)}, "
        f"{seconds(sum(entry['bytes'] for entry in heavy_resident)):.1f} s"
    )
    print(f"    fully resident and identical to the load before it: {repeats}")
    again = base_repeats(runs)
    print(
        f"    base lists carrying bytes {again['loads']}, "
        f"same as the one before {again['repeats']}, of those with the same list id "
        f"{again['repeats_same_id']}, still resident {again['resident']}, "
        f"disagreements {again['resident_not_repeat'] + again['repeat_not_resident']}, "
        f"{again['bytes']} bytes, {seconds(again['bytes']):.1f} s"
    )
    costs = group_costs(runs)
    skippable = defaultdict(lambda: {"spans": 0, "bytes": 0})
    for run in runs:
        for span in run["spans"]:
            if span["bytes"] and span["bytes"] == span["resident"]:
                skippable[span["name"]]["spans"] += 1
                skippable[span["name"]]["bytes"] += span["bytes"]
    for group in sorted(costs, key=str):
        entry = costs[group]
        free = skippable[group]
        print(
            f"      {group}: {entry['walks']} walks, {entry['bytes']} bytes, "
            f"{entry['bytes'] / max(entry['walks'], 1):.0f} per walk; "
            f"entirely resident on {free['spans']} of them, {free['bytes']} bytes, "
            f"{seconds(free['bytes']):.1f} s"
        )
    return totals


def main(argv: list[str]) -> int:
    paths = [Path(name) for name in argv[1:]]
    if not paths:
        paths = sorted((ROOT / "build" / "soundwalk").glob("grp-*.txt"))
    for path in paths:
        report(path.stem, path.read_text(errors="replace"))
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
