"""Git and filesystem helpers shared by the harness scripts and hooks."""

from __future__ import annotations

import os
import shutil
import subprocess
import sys
import tempfile
from dataclasses import dataclass
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]

# Harness messages use non-ASCII characters (—, →, §). Windows consoles default to cp1252.
for _stream in (sys.stdout, sys.stderr):
    if hasattr(_stream, "reconfigure"):
        _stream.reconfigure(encoding="utf-8", errors="replace")

WALK_SKIP = {".git", ".venv", "venv", "__pycache__", ".harness", ".mypy_cache", ".ruff_cache", ".pytest_cache", "data"}


@dataclass
class GitResult:
    ok: bool
    stdout: str
    stderr: str


def root_from_args(argv: list[str] | None = None) -> Path:
    """`--root <dir>` or HARNESS_ROOT let the scripts run on another tree (used by the harness tests)."""
    argv = sys.argv if argv is None else argv
    if "--root" in argv:
        i = argv.index("--root")
        if i + 1 < len(argv):
            return Path(argv[i + 1]).resolve()
    if os.environ.get("HARNESS_ROOT"):
        return Path(os.environ["HARNESS_ROOT"]).resolve()
    return ROOT


def arg_value(argv: list[str], flag: str) -> str | None:
    if flag in argv:
        i = argv.index(flag)
        if i + 1 < len(argv):
            return argv[i + 1]
    return None


def git(root: Path, args: list[str], env: dict[str, str] | None = None) -> GitResult:
    r = subprocess.run(
        ["git", *args],
        cwd=root,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        env=env,
        check=False,
    )
    return GitResult(r.returncode == 0, (r.stdout or "").strip(), (r.stderr or "").strip())


def _canonical(p: str | Path) -> str:
    s = str(Path(p).resolve())
    return s.lower() if sys.platform == "win32" else s


def is_git_repo(root: Path) -> bool:
    """Only counts if `root` is the top of the working tree (never inherit a parent repo)."""
    r = git(root, ["rev-parse", "--show-toplevel"])
    return r.ok and _canonical(r.stdout) == _canonical(root)


def current_branch(root: Path) -> str:
    if os.environ.get("GITHUB_HEAD_REF"):
        return os.environ["GITHUB_HEAD_REF"]
    if os.environ.get("GITHUB_ACTIONS") and os.environ.get("GITHUB_REF_NAME"):
        return os.environ["GITHUB_REF_NAME"]
    r = git(root, ["branch", "--show-current"])
    return r.stdout if r.ok else ""


def tree_fingerprint(root: Path) -> str | None:
    """Tree id a commit of everything tracked + new non-ignored files would have. Never touches the real index."""
    if not is_git_repo(root):
        return None
    index = git(root, ["rev-parse", "--git-path", "index"])
    if not index.ok:
        return None
    tmp = tempfile.mkdtemp(prefix="harness-index-")
    try:
        tmp_index = Path(tmp) / "index"
        real_index = (root / index.stdout).resolve()
        if real_index.exists():
            shutil.copyfile(real_index, tmp_index)
        env = {**os.environ, "GIT_INDEX_FILE": str(tmp_index)}
        if not git(root, ["add", "-A"], env=env).ok:
            return None
        tree = git(root, ["write-tree"], env=env)
        return tree.stdout if tree.ok else None
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


def list_repo_files(root: Path) -> list[str]:
    """Repo files as relative `/` paths: tracked + new non-ignored."""
    if is_git_repo(root):
        r = git(root, ["ls-files", "-co", "--exclude-standard", "-z"])
        if r.ok:
            files = {f for f in r.stdout.split("\0") if f}
            return sorted(f for f in files if (root / f).exists())
    out: list[str] = []
    for dirpath, dirnames, filenames in os.walk(root):
        dirnames[:] = [d for d in dirnames if d not in WALK_SKIP]
        for name in filenames:
            out.append(Path(dirpath, name).relative_to(root).as_posix())
    return sorted(out)


def to_repo_path(root: Path, file_path: str | Path) -> str:
    p = Path(file_path)
    if not p.is_absolute():
        p = root / p
    try:
        return Path(os.path.relpath(p.resolve(), root.resolve())).as_posix()
    except ValueError:  # different drive on Windows
        return "../" + p.as_posix()


def venv_python(root: Path) -> str:
    """The project's virtualenv interpreter if there is one; otherwise the current interpreter."""
    for candidate in (root / ".venv" / "Scripts" / "python.exe", root / ".venv" / "bin" / "python"):
        if candidate.exists():
            return str(candidate)
    return sys.executable
