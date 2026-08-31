"""What this machine is, checked rather than assumed, on any of the three systems.

Most reports that begin "it does not work here" are not about the code. They are
about a machine that differs from the one the author had, and the differences
that matter are nearly always the same handful. This looks for those, and it
looks the same way on Windows, macOS and Linux, because it asks the machine
rather than branching on a name.

**Why this file exists separately.** Every member of the family has its own
doctor, and each of those knows about its own part. None of them knew about the
machine underneath. This is the part that is identical everywhere, so it is
written once and carried unchanged, exactly like the shared half of `FAMILY.md`.

**What it looks for, and why each one bites.**

The interpreter is first because the instructions used to be wrong. `python3` is
what macOS and Linux call it and it is frequently absent on Windows, where the
name is `python` or the launcher is `py`. A reporter who is told to run a command
that does not exist reports the wrong problem.

Output encoding matters because the point of a doctor is that its output gets
pasted. A terminal still on a legacy code page cannot print what the report
contains, so the run dies part way through and the paste is a traceback.

Line endings matter because git can be configured to rewrite them on checkout.
Every digest over a text file then disagrees, every formatter reports the whole
tree as unformatted, and none of it is the repository's fault.

Path length matters because Windows refuses paths past 260 characters unless the
machine has been told otherwise, and members here nest submodules three deep.

The rest are the ordinary ones: is the tool installed, is there room on the disk,
and does the filesystem tell `A.py` from `a.py`, which decides whether a wrong
import passes locally and fails in CI.

**What it never does.** It does not repair anything, it does not guess, and it
does not fail a machine for being what it is. A case insensitive filesystem is
reported and is not a fault. A check that throws is caught and reported as what
it threw: a doctor that dies while examining is worse than no doctor.
"""

import contextlib
import locale
import platform
import shutil
import sys
from collections.abc import Callable
from pathlib import Path
from typing import NamedTuple


class Observation(NamedTuple):
    """One thing looked at, and what was there."""

    name: str
    ok: bool
    detail: str
    advice: str | None


INTERPRETERS = ("python3", "python", "py")
"""The names an interpreter answers to, in the order they are worth trying.

`python3` first because it is unambiguous where it exists. `python` second
because it is what a Windows installer provides. `py` last because the launcher
needs an argument to choose a version, so a caller has to be told to write
`py -3` rather than `py`.
"""

UTF8_NAMES = ("utf-8", "utf8", "utf_8", "cp65001")
"""Spellings of the one encoding that can print anything this reports."""

WINDOWS_PATH_LIMIT = 260
"""Where Windows stops, unless the machine has been told to allow more."""

CHECKOUT_ROOM = 60
"""How much of the budget a checkout path is assumed to want.

`C:\\Users\\somebody\\projects\\` is about forty characters before the repository
name is added, so sixty is the point below which an ordinary clone stops fitting.
Stated rather than tuned, and it is the number the report subtracts against.
"""

ROOM_WANTED = 2 * 1024**3
"""Enough space to hold a build and its inputs, which is the usual reason to run out."""

GENERATED = frozenset(
    {
        "node_modules",
        ".git",
        ".venv",
        "venv",
        "__pycache__",
        ".mypy_cache",
        ".ruff_cache",
        "dist",
        "build",
        ".pytest_cache",
    }
)
"""Directories a tool made rather than the repository carrying them.

A path this deep is still worth reporting, because a Windows user will meet it,
and it is not something the repository can be edited to fix.
"""

TEXT_SUFFIXES = (".md", ".py", ".yml", ".yaml", ".json", ".toml", ".txt", ".cfg")

SAMPLE = 200
"""How many text files the line ending check reads before it stops.

The question is whether the checkout was rewritten, which is a property of the
whole tree rather than of one file, so a sample answers it. Reading every file in
a repository that carries a corpus would make the doctor slow enough that people
stop running it, and a doctor nobody runs reports nothing.
"""


def interpreter(look: Callable[[str], bool] | None = None) -> Observation:
    """Which command runs Python here, so instructions can name the right one."""
    resolve = (lambda name: shutil.which(name) is not None) if look is None else look
    for name in INTERPRETERS:
        if resolve(name):
            spoken = "py -3" if name == "py" else name
            return Observation("interpreter", True, f"{spoken} runs this Python", None)
    return Observation(
        "interpreter",
        False,
        "none of python3, python or py resolved on PATH",
        "Install Python from python.org and tick the box that adds it to PATH.",
    )


DISCOVER = "<discover>"
"""Asks a check to look at this machine rather than take what it was handed.

A plain `None` cannot mean this, because `None` is a real answer: it is what a
terminal reports when it will not say what encoding it uses, and that case has to
stay distinguishable from nobody having passed anything.
"""


def output_encoding(encoding: str | None = DISCOVER) -> Observation:
    """Whether this terminal can print what the report contains."""
    found = sys.stdout.encoding if encoding == DISCOVER else encoding
    if found is None:
        return Observation(
            "output encoding",
            False,
            "this terminal does not say what encoding it uses",
            "Set PYTHONUTF8=1 before running, so the output is UTF-8 whatever the terminal says.",
        )
    if found.lower().replace("-", "").replace("_", "") in {
        one.replace("-", "").replace("_", "") for one in UTF8_NAMES
    }:
        return Observation("output encoding", True, found, None)
    return Observation(
        "output encoding",
        False,
        f"{found}, which cannot print everything this reports",
        "Set PYTHONUTF8=1, or run `chcp 65001` first on Windows.",
    )


def line_endings(root: Path, sample: int = SAMPLE) -> Observation:
    """Whether the checkout was rewritten to carriage returns on the way in."""
    looked = converted = 0
    for path in sorted(root.rglob("*")):
        if looked >= sample:
            break
        if not path.is_file() or path.suffix.lower() not in TEXT_SUFFIXES:
            continue
        if any(part.startswith(".") or part == "node_modules" for part in path.parts):
            continue
        try:
            head = path.read_bytes()[:4096]
        except OSError:
            continue
        looked += 1
        if b"\r\n" in head:
            converted += 1
    if not looked:
        return Observation("line endings", True, "nothing here to read", None)
    if converted:
        return Observation(
            "line endings",
            False,
            f"{converted} of {looked} sampled text files use carriage returns",
            "git config core.autocrlf false, then delete the checkout and clone again. "
            "Every digest and every formatter check disagrees while this is set.",
        )
    return Observation("line endings", True, f"line feeds in {looked} sampled files", None)


def filesystem_case(root: Path, insensitive: bool | None = None) -> Observation:
    """Whether this filesystem tells one spelling from another, which is not a fault.

    The answer is taken rather than probed when a caller supplies one, because a
    machine can only be one of the two and the other branch would otherwise be
    unreachable wherever the check happens to run.
    """
    if insensitive is not None:
        return _case_verdict(insensitive)
    probe = root / ".doctor-case-probe"
    try:
        probe.write_bytes(b"")
        insensitive = (root / ".DOCTOR-CASE-PROBE").exists()
    except OSError as thrown:
        return Observation("filesystem case", True, f"could not probe: {thrown!r}", None)
    finally:
        with contextlib.suppress(OSError):
            probe.unlink()
    return _case_verdict(insensitive)


def _case_verdict(insensitive: bool) -> Observation:
    """One reading turned into a line. Neither answer is a fault."""
    if insensitive:
        return Observation(
            "filesystem case",
            True,
            "case insensitive, so a wrongly cased import passes here and fails on Linux",
            None,
        )
    return Observation("filesystem case", True, "case sensitive", None)


def path_budget(root: Path, windows: bool | None = None, longest: int | None = None) -> Observation:
    """How much room a Windows checkout would have left, which is the portable question.

    The raw length of a path on this machine says nothing a reader can act on,
    because it includes wherever they happened to clone. What matters is the
    longest path measured from the repository root: subtract that from what
    Windows allows and the remainder is how deep a checkout directory may be
    before anything breaks.

    This is reported on every system rather than only on Windows. The tree is
    shared, so a layout that cannot be checked out there is a fact about the
    repository rather than about the machine that noticed.

    Generated directories are measured and reported and do not fail the check.
    A package manager that nests its own directories deeply is a real problem on
    Windows and it is not this repository's layout, so a reader is told about it
    and is not told their checkout is broken. Failing on it would make every
    member report a fault forever, which is how a check stops being read.
    """
    on_windows = platform.system() == "Windows" if windows is None else windows
    if longest is not None:
        return _budget_verdict(longest, "", on_windows, generated=False)

    tracked = generated = 0
    where_generated = ""
    for one in root.rglob("*"):
        parts = one.relative_to(root).parts
        length = len(str(one.relative_to(root)))
        if any(part in GENERATED for part in parts):
            if length > generated:
                generated, where_generated = length, parts[0]
            continue
        tracked = max(tracked, length)
    if generated > tracked:
        return _budget_verdict(generated, where_generated, on_windows, generated=True)
    return _budget_verdict(tracked, "", on_windows, generated=False)


def _budget_verdict(longest: int, where: str, on_windows: bool, generated: bool) -> Observation:
    """One reading turned into a line, with the same wording on every system."""
    room = WINDOWS_PATH_LIMIT - longest
    named = f", deepest under {where}" if where else ""
    detail = (
        f"{longest} characters from the repository root{named}, leaving {room} for a checkout path"
    )
    if room > CHECKOUT_ROOM:
        return Observation("path length", True, detail, None)
    if generated:
        return Observation(
            "path length",
            True,
            detail + ", all of it generated rather than tracked",
            None,
        )
    if on_windows:
        return Observation(
            "path length",
            False,
            detail,
            "Windows stops at 260 characters. Enable LongPathsEnabled in the registry, "
            "or clone somewhere short such as C:\\src.",
        )
    return Observation(
        "path length",
        False,
        detail,
        "This machine does not care, but Windows stops at 260 characters, so a checkout "
        "there would need a very short path. Enable LongPathsEnabled or clone to C:\\src.",
    )


def tool(
    name: str,
    look: Callable[[str], str | None] | None = None,
    required: bool = True,
) -> Observation:
    """Whether one command line tool is here, and where."""
    resolve = shutil.which if look is None else look
    where = resolve(name)
    if where:
        return Observation(f"tool {name}", True, str(where), None)
    if required:
        return Observation(
            f"tool {name}",
            False,
            "not found on PATH",
            f"Install {name} and make sure the shell can see it.",
        )
    return Observation(f"tool {name}", True, "not found on PATH, and not needed to run", None)


def free_space(root: Path, measure: Callable[[Path], int] | None = None) -> Observation:
    """Whether there is room for a build and what it reads."""
    read = (lambda path: shutil.disk_usage(path).free) if measure is None else measure
    try:
        free = read(root)
    except OSError as thrown:
        return Observation(
            "free space",
            False,
            f"could not be measured: {thrown!r}",
            "Check the drive is mounted and readable.",
        )
    gigabytes = free / 1024**3
    if free < ROOM_WANTED:
        return Observation(
            "free space",
            False,
            f"{gigabytes:.1f} GB free",
            f"Free up space: a build wants about {ROOM_WANTED / 1024**3:.0f} GB.",
        )
    return Observation("free space", True, f"{gigabytes:.1f} GB free", None)


def machine() -> Observation:
    """What this is, said plainly, because every other line is read against it."""
    return Observation(
        "machine",
        True,
        f"{platform.system()} {platform.release()} on {platform.machine()}, "
        f"{platform.python_implementation()} {platform.python_version()} "
        f"({'64' if sys.maxsize > 2**32 else '32'} bit)",
        None,
    )


def locale_setting(preferred: str | None = None, utf8: int | None = None) -> Observation:
    """The encoding Python reads files with when nobody names one."""
    preferred = locale.getpreferredencoding(False) if preferred is None else preferred
    utf8 = getattr(sys.flags, "utf8_mode", 0) if utf8 is None else utf8
    detail = f"{preferred}, UTF-8 mode {'on' if utf8 else 'off'}"
    if utf8 or preferred.lower().replace("-", "") == "utf8":
        return Observation("default encoding", True, detail, None)
    return Observation(
        "default encoding",
        False,
        detail,
        "Set PYTHONUTF8=1. Reading a UTF-8 file without naming the encoding fails here.",
    )


def guarded(name: str, check: Callable[[Path], Observation], root: Path) -> Observation:
    """One check, run so that its failure is reported rather than ending the run."""
    try:
        return check(root)
    except Exception as thrown:
        return Observation(
            name,
            False,
            f"the check itself raised {type(thrown).__name__}: {thrown}",
            "This is a fault in the doctor rather than in your machine. Please report it.",
        )


CHECKS: tuple[tuple[str, Callable[[Path], Observation]], ...] = (
    ("machine", lambda _root: machine()),
    ("interpreter", lambda _root: interpreter()),
    ("output encoding", lambda _root: output_encoding()),
    ("default encoding", lambda _root: locale_setting()),
    ("filesystem case", filesystem_case),
    ("line endings", line_endings),
    ("path length", path_budget),
    ("free space", free_space),
    ("tool git", lambda _root: tool("git")),
)


def observations(root: Path) -> list[Observation]:
    """Everything about the machine, in the order a reader wants it."""
    return [guarded(name, check, root) for name, check in CHECKS]


def lines(root: Path, found: list[Observation] | None = None) -> list[str]:
    """The same, ready to paste.

    The readings are taken rather than gathered when a caller supplies them, so
    the advice a failing check prints can be exercised on a machine where every
    check happens to pass.
    """
    found = observations(root) if found is None else found
    out = [f"  {'ok  ' if one.ok else '   !'}  {one.name}: {one.detail}" for one in found]
    for one in found:
        if not one.ok and one.advice:
            out.append(f"         {one.name}: {one.advice}")
    return out


def main() -> int:
    root = Path(__file__).resolve().parent.parent
    for line in lines(root):
        print(line)
    return 0 if all(one.ok for one in observations(root)) else 1


if __name__ == "__main__":
    raise SystemExit(main())
