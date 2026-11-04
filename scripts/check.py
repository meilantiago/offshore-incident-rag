"""Single gate runner. "Done" = this is green (constitution §2).

python scripts/check.py --all        every gate (CI, /sdd-verify)
python scripts/check.py --fast       fast gates only (hook gate_on_stop)
python scripts/check.py --only a,b   specific gates
--no-cache                           with --fast, run even if the tree did not change since the last green
"""

from __future__ import annotations

import datetime as dt
import json
import os
import subprocess
import sys
import time
from collections.abc import Callable, Sequence
from dataclasses import dataclass
from pathlib import Path

import harness_config as config
from lib.repo import arg_value, current_branch, root_from_args, tree_fingerprint, venv_python

OUTPUT_TAIL = 40
FAST_OK_FILE = "fast-ok.json"


@dataclass
class GateResult:
    id: str
    ok: bool
    ms: int
    output: str


def _tail(text: str, n: int) -> str:
    lines = text.strip().splitlines()
    return "\n".join(["…", *lines[-n:]] if len(lines) > n else lines)


def run_gate(gate: config.Gate, root: Path) -> tuple[bool, str]:
    python = venv_python(root)
    cmd = [python if part == "{python}" else part for part in gate.cmd]
    env = {**os.environ, "NO_COLOR": "1", "PYTHONIOENCODING": "utf-8"}
    try:
        r = subprocess.run(
            cmd, cwd=root, capture_output=True, text=True, encoding="utf-8", errors="replace", env=env, check=False
        )
    except OSError as e:
        return False, f"could not run {cmd[0]}: {e}"
    return r.returncode in gate.ok_codes, f"{r.stdout or ''}{r.stderr or ''}"


def _write_state(root: Path, name: str, data: dict) -> None:
    d = root / ".harness"
    d.mkdir(exist_ok=True)
    (d / name).write_text(json.dumps(data, indent=2), encoding="utf-8")


def _fast_key(root: Path) -> str | None:
    """Fast gates depend on the tree and the branch (approval). If neither changed since the last green, skip them."""
    tree = tree_fingerprint(root)
    return f"{current_branch(root)}:{tree}" if tree else None


def _last_fast_ok(root: Path) -> str | None:
    f = root / ".harness" / FAST_OK_FILE
    if not f.exists():
        return None
    try:
        return json.loads(f.read_text(encoding="utf-8")).get("key")
    except (json.JSONDecodeError, OSError):
        return None


def run_gates(
    root: Path,
    mode: str = "all",
    only: Sequence[str] | None = None,
    gates: Sequence[config.Gate] = config.GATES,
    log: Callable[[str], None] = print,
    cache: bool = True,
) -> tuple[bool, list[GateResult]]:
    key = None if only else _fast_key(root)
    if mode == "fast" and cache and key and _last_fast_ok(root) == key:
        log(
            "check (fast): the tree has not changed since the last green fast run; not re-running (--no-cache forces it)"
        )
        return True, []

    selected = [g for g in gates if (g.id in only if only else (g.fast if mode == "fast" else True))]
    results: list[GateResult] = []
    for gate in selected:
        start = time.monotonic()
        ok, output = run_gate(gate, root)
        ms = int((time.monotonic() - start) * 1000)
        log(f"{'[ok]  ' if ok else '[FAIL]'} {gate.id} ({ms} ms)")
        if not ok:
            log("\n".join("       " + ln for ln in _tail(output, OUTPUT_TAIL).splitlines()))
        results.append(GateResult(gate.id, ok, ms, "" if ok else _tail(output, OUTPUT_TAIL)))

    failed = [r.id for r in results if not r.ok]
    log(
        f"\ncheck ({mode}): FAILED in {', '.join(failed)}"
        if failed
        else f"\ncheck ({mode}): {len(results)} gate(s) green"
    )
    now = dt.datetime.now(dt.UTC).isoformat(timespec="seconds")
    try:
        _write_state(root, "last-check.json", {"mode": mode, "at": now, "results": [r.__dict__ for r in results]})
        fast_green = all(any(r.id == g.id and r.ok for r in results) for g in gates if g.fast)
        if key and fast_green:
            _write_state(root, FAST_OK_FILE, {"key": key, "at": now})
    except OSError as e:
        log(f"(could not save state in .harness/: {e})")
    return not failed, results


def main(argv: list[str]) -> int:
    only_arg = arg_value(argv, "--only")
    only = only_arg.split(",") if only_arg else None
    mode = "only" if only else ("fast" if "--fast" in argv else "all")
    ok, _ = run_gates(root_from_args(argv), mode=mode, only=only, cache="--no-cache" not in argv)
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main(sys.argv))
