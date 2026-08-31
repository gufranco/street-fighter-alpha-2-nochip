import importlib.util
import json
import sys
from collections import namedtuple
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parent.parent
ROMS = ROOT / "roms"
MANIFEST_PATH = ROOT / "artifacts.manifest.json"


def _load(name: str) -> Any:
    spec = importlib.util.spec_from_file_location(name, ROOT / f"{name}.py")
    assert spec is not None and spec.loader is not None, "no loader for that path"
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


hardware = _load("hardware")
romimage = hardware.load("romimage")

Identity = namedtuple("Identity", "size crc32 md5 sha1 sha256")
Finding = namedtuple("Finding", "name filename state detail identity form")

STATE_OK = "ok"
STATE_MISSING = "missing"
STATE_UNDECLARED = "no digest published"
STATE_WRONG_SIZE = "wrong size"
STATE_WRONG_CONTENT = "wrong content"
STATE_KNOWN_BAD = "known bad dump"
STATE_OTHER_ENTRY = "another entry"

BLOCKING_STATES = frozenset(
    {STATE_WRONG_SIZE, STATE_WRONG_CONTENT, STATE_KNOWN_BAD, STATE_OTHER_ENTRY}
)

DIGEST_COMMANDS = (
    ("macOS and Linux", "shasum -a 256 roms/{filename}"),
    ("Linux, coreutils", "sha256sum roms/{filename}"),
    ("Windows PowerShell", "Get-FileHash -Algorithm SHA256 roms\\{filename}"),
)


def digests(data):
    return Identity(**romimage.identity.measure(data))


def read_manifest(path=MANIFEST_PATH):
    return json.loads(Path(path).read_text())


def accepted_digests(manifest):
    return {
        accepted["sha256"]: artifact
        for artifact in manifest["artifacts"]
        for accepted in artifact["accepted"]
    }


def known_bad_digests(manifest):
    return {entry["sha256"]: entry for entry in manifest.get("known_bad", [])}


def source_form(raw):
    return "copier header, stripped" if romimage.dump.has_copier_stub(raw) else "bare"


def diagnose(artifact, manifest, roms=ROMS):
    name = artifact["name"]
    filename = artifact["filename"]
    path = Path(roms) / filename

    if not artifact["accepted"]:
        return Finding(name, filename, STATE_UNDECLARED, "no dump measured yet", None, None)

    if not path.exists():
        return Finding(name, filename, STATE_MISSING, f"{path} is not there", None, None)

    raw = path.read_bytes()
    form = source_form(raw)
    identity = digests(romimage.dump.strip_copier_stub(raw))

    if any(identity.sha256 == accepted["sha256"] for accepted in artifact["accepted"]):
        return Finding(name, filename, STATE_OK, "", identity, form)

    bad = known_bad_digests(manifest).get(identity.sha256)
    if bad is not None:
        return Finding(name, filename, STATE_KNOWN_BAD, bad["why"], identity, form)

    other = accepted_digests(manifest).get(identity.sha256)
    if other is not None:
        return Finding(
            name, filename, STATE_OTHER_ENTRY, f"this is {other['name']}", identity, form
        )

    sizes = {accepted["size"] for accepted in artifact["accepted"]}
    if identity.size not in sizes:
        wanted = ", ".join(f"{size:,}" for size in sorted(sizes))
        detail = f"{identity.size:,} bytes, expected {wanted}"
        return Finding(name, filename, STATE_WRONG_SIZE, detail, identity, form)

    detail = "right size, different bytes"
    return Finding(name, filename, STATE_WRONG_CONTENT, detail, identity, form)


def repair_hint(finding):
    if finding.state == STATE_WRONG_SIZE:
        return "if this came from a copier or a split set, join or strip it and try again"
    if finding.state == STATE_WRONG_CONTENT:
        return "a different revision, a translation, an already patched image, or a bad dump"
    if finding.state == STATE_OTHER_ENTRY:
        return "rename it to the filename that entry expects"
    if finding.state == STATE_KNOWN_BAD:
        return "this dump is corrupt, find another copy"
    return ""


def explain(finding):
    lines = [f"  {finding.filename}: {finding.state}  [{finding.name}]"]
    if finding.detail:
        lines.append(f"      {finding.detail}")
    if finding.identity is not None:
        lines.append(f"      read as {finding.form}, {finding.identity.size:,} bytes")
        lines.append(f"      crc32  {finding.identity.crc32}")
        lines.append(f"      sha256 {finding.identity.sha256}")
    hint = repair_hint(finding)
    if hint:
        lines.append(f"      {hint}")
    if finding.state in BLOCKING_STATES or finding.state == STATE_MISSING:
        for label, command in DIGEST_COMMANDS:
            lines.append(f"      {label}: {command.format(filename=finding.filename)}")
    return "\n".join(lines)


def blocking(finding):
    return finding.state in BLOCKING_STATES


def run(manifest, roms=ROMS, wanted=()):
    return [
        diagnose(artifact, manifest, roms)
        for artifact in manifest["artifacts"]
        if not wanted or artifact["filename"] in wanted
    ]


def main(argv, manifest=None, say=print, complain=None):
    """Every declared dump checked, with both streams passed in so a run can be tested."""
    complain = say if complain is None else complain
    manifest = read_manifest() if manifest is None else manifest

    findings = run(manifest, wanted=tuple(argv[1:]))
    if not findings:
        complain("  no artifact in the manifest matches that name")
        return 2

    usable = 0
    failed = False
    for finding in findings:
        say(explain(finding))
        usable += finding.state == STATE_OK
        failed = failed or blocking(finding)

    say(f"\n  {usable} of {len(findings)} declared dumps present and correct")
    return 1 if failed or usable == 0 else 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
