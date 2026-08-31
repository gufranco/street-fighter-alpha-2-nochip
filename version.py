VERSION = "1.4.0"

UNRELEASED = "0.0.0"
EXTENSION = ".sfc"


def stamped(name: str, release: str | None = None) -> str:
    release = VERSION if release is None else release
    suffix = "-dev" if release == UNRELEASED else ""
    return f"{name}-v{release}{suffix}{EXTENSION}"
