import shutil
import subprocess
import sys
from collections.abc import Callable
from pathlib import Path

ROOT = Path(__file__).resolve().parent
ASM_DIR = ROOT / "asm"
IMAGE = "street-fighter-alpha-2-nochip/asar:1.81"


class ToolchainMissing(Exception):
    """The program that builds and runs the container is not on PATH."""


def build_image_command() -> list[str]:
    return [
        "docker",
        "build",
        "--tag",
        IMAGE,
        str(ASM_DIR),
    ]


def patch_command(work_dir: Path | str, patch_name: str, rom_name: str) -> list[str]:
    return [
        "docker",
        "run",
        "--rm",
        "--network=none",
        "--volume",
        f"{work_dir}:/work",
        IMAGE,
        patch_name,
        rom_name,
    ]


def stage_rom(source: Path | str, work_dir: Path | str, output_name: str) -> Path:
    target = Path(work_dir) / output_name
    if target.resolve() == Path(source).resolve():
        raise ValueError("refusing to patch the source ROM in place")
    shutil.copy2(source, target)
    return target


def missing_message(program: str) -> str:
    return (
        f"{program} is not on PATH, and this build needs it. "
        f"The assembler runs in a container so its version is pinned; "
        f"nothing is assembled on the host. "
        f"Install Docker, start it, and check it answers with: {program} --version"
    )


def run(
    args: list[str],
    execute: Callable[[list[str]], int] | None = None,
    say: Callable[[str], None] = print,
) -> int:
    """One command, printed before it runs so a failing build says what it ran."""
    say("  $ " + " ".join(args))
    if execute is None:
        execute = _shell_out
    try:
        return execute(args)
    except FileNotFoundError as absent:
        raise ToolchainMissing(missing_message(args[0])) from absent


def _shell_out(args: list[str]) -> int:
    return subprocess.run(args, text=True, check=False).returncode


def wants_image_only(argv: list[str]) -> bool:
    return len(argv) == 2 and argv[1] == "--image"


def main(
    argv: list[str] | None = None,
    execute: Callable[[list[str]], int] | None = None,
    say: Callable[[str], None] = print,
    complain: Callable[[str], None] | None = None,
) -> int:
    """The command line, with the shelling out passed in so it can be checked."""
    argv = sys.argv if argv is None else argv
    complain = say if complain is None else complain

    if wants_image_only(argv):
        return run(build_image_command(), execute, say)

    if len(argv) < 4:
        complain("usage: build.py <patch.asm> <source-rom> <output-rom>")
        complain("       build.py --image        (build the toolchain image only)")
        return 2

    patch, source, output = argv[1], Path(argv[2]), argv[3]
    work = Path(patch).resolve().parent

    if run(build_image_command(), execute, say) != 0:
        complain("toolchain image failed to build")
        return 1

    staged = stage_rom(source, work, output)
    say(f"  staged {source} -> {staged}")

    code = run(patch_command(work, Path(patch).name, output), execute, say)
    if code == 0:
        say(f"[done] {staged} ({staged.stat().st_size:,} bytes)")
    return code


def cli() -> int:
    try:
        return main()
    except ToolchainMissing as absent:
        print(absent, file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(cli())
