"""Put the hardware models this project is checked against on the import path.

The models used to live in this repository as loose modules, imported by file
path. They are now separate repositories, pinned here as submodules at the
root, so that the thing this project is measured against is measured itself: the processor and the
audio processor each against a per-opcode suite, the decompressor against the
chip's own reference implementation, and the cartridge map and the image handling
against a library of real cartridges.

Two consequences are worth stating, because both change what code here must do.

The models start unclean. Their memory and registers hold arbitrary but
reproducible values rather than zeroes, because hardware does. Anything here that
relied on a register being zero without setting it was relying on the model being
tidier than the machine, and now has to say what it wants.

The audio mixer is played rather than merely pinned. The sample-upload and
repeat-load patches change what reaches it, and a patch to audio code checked
only against a listing has been checked for shape and not for effect. The whole
audio unit is here for the same reason one step further out: the processor, the
mixer and the boot ROM composed as the cartridge meets them, so the ports the
upload driver talks through are the hardware's own rather than a stand-in
written to the reading of the driver being tested.

And nothing is loaded by file path any more. `load()` returns a model by the name
it is published under, which reads the same way at the top of a module as the
file-path helper it replaces and does not need an import to be moved below a
statement to work.

The third consequence is the one that reaches whoever clones this. A submodule is
a pinned commit, not content, so `git clone` on its own leaves every named
directory empty. Everything here imports through `load()`, so `load()` is where
that has to be said, rather than leaving a bare import error to stand in for the
explanation.
"""

import importlib
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent

ORIGIN = "https://github.com/gufranco/street-fighter-alpha-2-nochip.git"
"""Where a clone comes from, named so a broken tree can be told how to fix itself."""

PACKAGES = {
    "mos65xx": "mos65xx-python",
    "spc700": "sony-spc700-python",
    "sdd1": "snes-sdd1-python",
    "sdsp": "sony-s-dsp-python",
    "mapper": "snes-mapper-python",
    "romimage": "snes-rom-image-python",
    "ssmp": "sony-s-smp-python",
    "snesgfx": "snes-graphics-python",
    "snesdriver": "snes-driver-python",
}
"""The package each submodule provides, and the directory it lives in.

The directories sit at the root of this repository under the names of the
repositories they are, rather than under a folder that hides them. Anybody who
opens this project sees what it is built on without going looking, which is the
point: each of those is a project in its own right and is held to its own oracle.
"""


class UnknownPackage(Exception):
    pass


class ModelMissing(Exception):
    """A model is pinned here but its submodule was never checked out."""


def root_of(package):
    """Where a vendored model lives, by the name it is imported under."""
    directory = PACKAGES.get(package)
    if directory is None:
        raise UnknownPackage(
            f"{package} is not vendored here; this project carries {', '.join(sorted(PACKAGES))}"
        )
    return ROOT / directory


def install():
    """Make every vendored model importable, without stacking the path."""
    for package in PACKAGES:
        entry = str(root_of(package))
        if entry not in sys.path:
            sys.path.insert(0, entry)


def is_checked_out(package):
    """Whether a pinned model has content and not just a directory."""
    directory = root_of(package)
    return directory.is_dir() and any(directory.iterdir())


def missing_models():
    """Every model that is pinned here and not checked out."""
    return [package for package in PACKAGES if not is_checked_out(package)]


def is_git_checkout():
    """Whether this tree carries the git metadata a submodule needs to be filled in."""
    return any((folder / ".git").exists() for folder in (ROOT, *ROOT.parents))


def checkout_message(missing, from_git):
    named = ", ".join(sorted(missing))
    subject = "model is" if len(missing) == 1 else "models are"
    said = (
        f"the {named} {subject} pinned here but not checked out. "
        "A submodule is a pinned commit rather than content, so the directory is "
        "empty and nothing here can import."
    )
    if from_git:
        return f"{said}\n    git submodule update --init --recursive\nfills them in."
    return (
        f"{said}\n"
        "This tree has no git metadata, so it came from a downloaded archive. A source "
        "zip never carries submodule content and nothing can fill it in afterwards, so "
        "there is no repair for this copy. Clone instead:\n"
        f"    git clone --recurse-submodules {ORIGIN}"
    )


def load(package):
    """A model, by the name it is published under."""
    if not is_checked_out(package):
        raise ModelMissing(checkout_message(missing_models(), is_git_checkout()))
    install()
    return importlib.import_module(package)
