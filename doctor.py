"""Look at this machine and say what is actually here, so a report can be believed.

This project is the end of a chain. It rebuilds a cartridge without its
decompressor, using models that live in other repositories and a dump that
belongs to whoever made the game. Any link can be missing on a given machine, and
from outside they all look the same: it does not work.

So this looks, and prints what it found in a form that can be pasted into an
issue as it stands.

It asks the models it is built on for their own reports too, and files what comes
back under their names. That is recursive by construction: whatever they examine,
including anything they are built on in turn, arrives with it. A project can be
entirely well while the thing underneath it is stale, and a report that looked
only here would come back clean in exactly that case.

Two rules shape the rest. Nothing is hidden: a check that fails says what it saw,
and a check that itself throws is reported as what it threw, named by type.
Nothing is inferred: every line is something looked at on this machine just now.

No byte of anybody's cartridge is printed. The digest of a dump identifies it
without carrying it, which is the whole reason digests are published.
"""

import importlib
import platform
import shutil
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent

sys.path.insert(0, str(ROOT))

import hardware  # noqa: E402
from version import VERSION  # noqa: E402

sys.path.insert(0, str(ROOT / "tools"))

identify = importlib.import_module("identify")

OLDEST_PYTHON = (3, 12)

PROJECT = "street-fighter-alpha-2-nochip"

PART = "sdd1"
"""The coprocessor this cartridge carries, and the model a check runs against."""

TOOLS = ("docker",)
"""What a build shells out to. Nothing here needs them; the build does."""


class Finding:
    """One thing that was looked at, and what was there."""

    def __init__(self, name, ok, detail, advice=None):
        self.name = name
        self.ok = ok
        self.detail = detail
        self.advice = advice

    @property
    def line(self):
        """The one-line form, which is what a reader scans."""
        return f"  {'ok  ' if self.ok else '   !'}  {self.name}: {self.detail}"

    @property
    def report(self):
        """The same, with what to do about it when there is something to do."""
        if self.ok or not self.advice:
            return self.line
        return f"{self.line}\n         {self.advice}"

    def __repr__(self) -> str:
        return f"<Finding {self.name} {'ok' if self.ok else 'not ok'}>"


def _python():
    return Finding(
        "python",
        sys.version_info[:2] >= OLDEST_PYTHON,
        f"{platform.python_version()} on {platform.system()} {platform.machine()}",
        f"this project needs {OLDEST_PYTHON[0]}.{OLDEST_PYTHON[1]} or newer",
    )


def _project():
    return Finding(PROJECT, True, f"version {VERSION}")


def _default_import(package):
    hardware.install()
    return importlib.import_module(package)


def _model(package, where, load):
    """Whether that model is checked out and imports, and which version it is."""
    if not Path(where).is_dir() or not any(Path(where).iterdir()):
        return Finding(
            package,
            False,
            f"{Path(where).name} is not checked out",
            "the models live in their own repositories and are pinned here as"
            " submodules; run git submodule update --init --recursive",
        )
    try:
        found = load(package)
    except Exception as trouble:
        return Finding(
            package,
            False,
            f"{type(trouble).__name__}: {trouble}",
            "the model is here and will not import, which is the line above"
            " rather than a missing checkout",
        )
    return Finding(package, True, f"version {getattr(found, 'VERSION', 'not stated')}")


def _default_cartridges():
    manifest = identify.read_manifest()
    return [identify.diagnose(one, manifest) for one in manifest["artifacts"]]


def _cartridges(diagnose=_default_cartridges):
    """Every dump this project reads, and whether the one here is the one it wants.

    A region with no digests published yet is reported and is not a failure. It
    says something true about the project rather than about the machine running
    it, and a report that came back unwell on every machine would stop being read.
    """
    try:
        found = list(diagnose())
    except Exception as trouble:
        return [
            Finding(
                "cartridge",
                False,
                f"{type(trouble).__name__}: {trouble}",
                "the manifest could not be read, so nothing here says which dump"
                " this project wants",
            )
        ]
    lines = []
    for one in found:
        digest = f", sha256 {one.identity.sha256}" if one.identity else ""
        lines.append(
            Finding(
                f"cartridge {one.filename}",
                one.state in (identify.STATE_OK, identify.STATE_UNDECLARED),
                f"{one.state}{': ' + one.detail if one.detail else ''}{digest}",
                "the digests this project accepts are published in"
                " artifacts.manifest.json; nothing here says where to obtain a dump",
            )
        )
    return lines


def _default_decompress():
    stream = bytes(range(256))
    return _default_import("sdd1").decompress(stream, 0, 8)


def _decompressor(decompress=_default_decompress):
    """That the decompressor is wired here, rather than merely importable.

    Every image this project builds is an expansion of streams that came out of
    this part, so a decompressor that will not run is the one failure that stops
    everything, and it is worth one call to find out before anything else does.
    """
    try:
        found = decompress()
    except Exception as trouble:
        return Finding(
            "decompressor",
            False,
            f"{type(trouble).__name__}: {trouble}",
            "the S-DD1 model is here and will not decode, which is the line above",
        )
    return Finding("decompressor", True, f"decoded {len(found)} bytes of a stream nobody owns")


def _tools(named=TOOLS, look=shutil.which):
    """What a build shells out to, and whether this machine has it.

    Absent, the analysis still runs and the build does not. That is worth saying
    plainly rather than leaving to the first subprocess that fails.
    """
    lines = []
    for one in named:
        where = look(one)
        lines.append(
            Finding(
                one,
                bool(where),
                where or "not on the path",
                f"the build runs its toolchain through {one}; the analysis here does not need it",
            )
        )
    return lines


def _default_beneath():
    """Every model that carries a doctor, asked for its own report.

    A model with no doctor is passed over rather than reported: not every one of
    them has grown one yet, and a line saying so on every run would be noise. A
    model whose doctor is here and will not run is a different thing entirely and
    is left to raise, because that is a real fault on this machine.
    """
    return _ask_each(sorted(hardware.PACKAGES), hardware.root_of, importlib.import_module)


def _ask_each(packages, locate, load):
    """Each named model asked for its report, skipping the ones that have none."""
    found = []
    for package in packages:
        where = Path(locate(package))
        if not where.is_dir():
            continue
        if str(where) not in sys.path:
            sys.path.insert(0, str(where))
        try:
            underneath = load(f"{package}.doctor")
        except ModuleNotFoundError:
            continue
        found.extend((where.name, one) for one in underneath.examine())
    return found


def _default_unused():
    """Findings from a model that are about something this cartridge does not carry."""
    return ()


def _beneath(beneath, unused=_default_unused):
    """Everything the models found, each filed under the name of its repository.

    One adjustment is made on the way through, and it is worth saying exactly
    what it is. The coprocessor model covers six parts and reports a missing
    image for each. This cartridge carries one of them. A missing image for the
    other five is a true statement about this machine and not a fault of it, so
    the line is kept, in full, and stops being counted as a failure. Nothing is
    removed: a report that hid those lines would be hiding the one thing somebody
    checking a digest needs to see.
    """
    try:
        found = list(beneath())
    except Exception as trouble:
        return [
            Finding(
                "the models underneath",
                False,
                f"{type(trouble).__name__}: {trouble}",
                "one of the models could not be examined; it is either not checked"
                " out or older than this project expects, and both are fixed by"
                " running git submodule update --init --recursive",
            )
        ]
    elsewhere = set(unused())
    lines = []
    for where, one in found:
        spare = one.name in elsewhere and not one.ok
        lines.append(
            Finding(
                f"{where} / {one.name}",
                one.ok or spare,
                f"{one.detail}, and this cartridge does not carry it" if spare else one.detail,
                None if spare else one.advice,
            )
        )
    return lines


def examine(load=_default_import, beneath=_default_beneath):
    """Everything worth looking at on this machine, in the order a reader wants it."""
    found = [_python(), _project()]
    found.extend(
        _model(package, hardware.root_of(package), load) for package in sorted(hardware.PACKAGES)
    )
    found.extend(_cartridges())
    found.append(_decompressor())
    found.extend(_tools())
    found.extend(_beneath(beneath))
    return found


def report(found):
    """The lines a person pastes into an issue."""
    unwell = [one for one in found if not one.ok]
    lines = [f"{PROJECT} {VERSION} on {platform.python_version()}, {platform.system()}", ""]
    lines.extend(one.report for one in found)
    lines.append("")
    if unwell:
        lines.append(f"  {len(unwell)} of {len(found)} checks did not pass")
    else:
        lines.append(f"  {len(found)} checks, nothing to report")
    return lines


def main(argv=(), examine=examine, say=print):
    found = examine()
    for line in report(found):
        say(line)
    return 1 if any(not one.ok for one in found) else 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
