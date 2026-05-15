"""rvnx — run a tool in an isolated, ephemeral environment.

Similar to uvx, pipx run, or npx.  On first use, the requested package is
installed into a persistent venv under ~/.rvn/tools/{tool}/.venv/.
Subsequent calls reuse the cached environment (fast).

    rvnx black myfile.py
    rvnx ruff check .
    rvnx --from black@23.1 black myfile.py
    rvnx --python 3.14 mypy src/
    rvnx --reinstall ruff check .

Python runtime resolution order:
  1. rvn-managed Python (~/.rvn/runtimes/python/) — newest matching version
  2. Python running rvn itself (sys.executable)

Usage as a console script entry point (defined in pyproject.toml):
    [project.scripts]
    rvnx = "rvn.rvnx:entry_point"
"""

from __future__ import annotations

import importlib.metadata
import os
import subprocess
import sys
from pathlib import Path


_TOOLS_DIR = Path.home() / ".rvn" / "tools"
_PY_RUNTIMES = Path.home() / ".rvn" / "runtimes" / "python"


# ── helpers ───────────────────────────────────────────────────────────────────


def _rvn_version() -> str:
    try:
        return importlib.metadata.version("rvn")
    except importlib.metadata.PackageNotFoundError:
        return "dev"


def _find_python(version_prefix: str | None = None) -> str:
    """Return the path to a usable Python interpreter.

    Priority: rvn-managed Python (newest) → sys.executable.
    """
    if _PY_RUNTIMES.exists():
        candidates = sorted(
            (p for p in _PY_RUNTIMES.iterdir() if p.is_dir()),
            reverse=True,
        )
        for c in candidates:
            if version_prefix and not c.name.startswith(version_prefix.rstrip(".")):
                continue
            for name in (f"python{'.'.join(c.name.split('.')[:2])}", "python3", "python"):
                bin_py = c / "bin" / name
                if bin_py.exists():
                    return str(bin_py)
    return sys.executable


def _find_managed_python(version_prefix: str) -> str | None:
    """Return rvn-managed Python for the given prefix, or None."""
    if not _PY_RUNTIMES.exists():
        return None
    vp = version_prefix.rstrip(".")
    for c in sorted(_PY_RUNTIMES.iterdir(), reverse=True):
        if not c.is_dir():
            continue
        if c.name == vp or c.name.startswith(vp + "."):
            for name in (f"python{'.'.join(c.name.split('.')[:2])}", "python3", "python"):
                p = c / "bin" / name
                if p.exists():
                    return str(p)
    return None


def _ensure_tool(tool_name: str, package_spec: str, python: str) -> Path:
    """Create (or reuse) the isolated venv for *tool_name*; return its bin dir."""
    venv = _TOOLS_DIR / tool_name / ".venv"
    bin_dir = venv / "bin"

    if not venv.exists():
        _TOOLS_DIR.mkdir(parents=True, exist_ok=True)
        print(f"rvnx: creating isolated environment for '{tool_name}' ...", flush=True)
        subprocess.run([python, "-m", "venv", str(venv)], check=True)

    venv_python = bin_dir / "python3"
    if not venv_python.exists():
        venv_python = bin_dir / "python"

    if not (bin_dir / tool_name).exists():
        print(f"rvnx: installing {package_spec} ...", flush=True)
        subprocess.run(
            [str(venv_python), "-m", "pip", "install", "--quiet", package_spec],
            check=True,
        )

    return bin_dir


# ── CLI parser ────────────────────────────────────────────────────────────────


def _usage() -> str:
    v = _rvn_version()
    return f"""\
rvnx {v} — run tools in isolated environments (like uvx / pipx run)

Usage: rvnx [options] <tool> [tool-args...]

Options:
  --from <pkg_spec>   Package spec to install (default: same as tool name).
                      Supports PEP 508 syntax: black, black==23.1, black>=23
  --python <version>  Python version to use (must be installed via rvn system install python)
  --reinstall         Force reinstall — remove existing tool environment first
  --version           Print rvnx version
  -h, --help          Show this help

Examples:
  rvnx black myfile.py
  rvnx ruff check .
  rvnx --from black@23.1 black myfile.py   # pip-style: black==23.1
  rvnx --python 3.12 mypy src/
  rvnx --reinstall ruff check .
"""


def _normalise_spec(spec: str) -> str:
    """Normalise `pkg@version` → `pkg==version` for pip compatibility."""
    if "@" in spec and "==" not in spec and ">=" not in spec:
        name, _, ver = spec.partition("@")
        return f"{name}=={ver}"
    return spec


def main(argv: list[str] | None = None) -> int:
    if argv is None:
        argv = sys.argv[1:]

    if not argv or argv[0] in ("-h", "--help"):
        print(_usage())
        return 0

    if argv[0] == "--version":
        print(f"rvnx {_rvn_version()}")
        return 0

    # Parse rvnx flags (stop at first non-flag positional = tool name)
    package_spec: str | None = None
    python_ver: str | None = None
    reinstall = False
    tool_args: list[str] = []

    i = 0
    while i < len(argv):
        arg = argv[i]
        if arg == "--from":
            if i + 1 >= len(argv):
                print("rvnx: --from requires an argument.", file=sys.stderr)
                return 1
            i += 1
            package_spec = _normalise_spec(argv[i])
        elif arg.startswith("--from="):
            package_spec = _normalise_spec(arg[len("--from=") :])
        elif arg == "--python":
            if i + 1 >= len(argv):
                print("rvnx: --python requires an argument.", file=sys.stderr)
                return 1
            i += 1
            python_ver = argv[i]
        elif arg.startswith("--python="):
            python_ver = arg[len("--python=") :]
        elif arg == "--reinstall":
            reinstall = True
        elif arg == "--version":
            print(f"rvnx {_rvn_version()}")
            return 0
        elif arg.startswith("-") and arg not in ("-h", "--help"):
            print(f"rvnx: unknown option '{arg}'. Run `rvnx --help`.", file=sys.stderr)
            return 1
        else:
            # First non-flag argument: the tool name and its args
            tool_args = argv[i:]
            break
        i += 1

    if not tool_args:
        print("rvnx: no tool specified.  Run `rvnx --help`.", file=sys.stderr)
        return 1

    tool_name = tool_args[0]
    if package_spec is None:
        package_spec = tool_name

    # Resolve Python interpreter
    if python_ver:
        python = _find_managed_python(python_ver)
        if python is None:
            print(
                f"rvnx: Python {python_ver} is not installed via rvn.\n"
                f"      Install it with:  rvn system install python {python_ver}",
                file=sys.stderr,
            )
            return 1
    else:
        python = _find_python()

    # Reinstall: wipe existing environment
    if reinstall:
        import shutil

        env_dir = _TOOLS_DIR / tool_name
        if env_dir.exists():
            print(f"rvnx: removing {env_dir} ...", flush=True)
            shutil.rmtree(env_dir)

    # Ensure tool is installed
    try:
        bin_dir = _ensure_tool(tool_name, package_spec, python)
    except subprocess.CalledProcessError as exc:
        print(f"rvnx: failed to install '{package_spec}': {exc}", file=sys.stderr)
        return 1

    # Find the tool binary
    tool_bin = bin_dir / tool_name
    if not tool_bin.exists():
        # Scan for any matching executable
        installed = [p.name for p in bin_dir.iterdir() if not p.name.startswith("_")]
        print(
            f"rvnx: '{tool_name}' binary not found in the installed environment.\n"
            f"      Available scripts: {installed}",
            file=sys.stderr,
        )
        return 1

    env = {
        **os.environ,
        "PATH": f"{bin_dir}:{os.environ.get('PATH', '')}",
    }
    result = subprocess.run([str(tool_bin), *tool_args[1:]], env=env)
    return result.returncode


def entry_point() -> None:
    """Console script entry point."""
    sys.exit(main())


if __name__ == "__main__":
    entry_point()
