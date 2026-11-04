"""Reading and parsing specs: docs/specs/NNN-slug/{spec,plan,tasks}.md."""

from __future__ import annotations

import hashlib
import re
from dataclasses import dataclass, field
from pathlib import Path

SPECS_DIR = "docs/specs"
SPEC_DIR_RE = re.compile(r"^(\d{3})-[a-z0-9]+(?:-[a-z0-9]+)*$")
AC_ID_RE = re.compile(r"\bAC-(\d{3})-(\d{2})\b")
STATUSES = ("draft", "approved", "superseded")
APPROVAL_FIELDS = ("status", "approved_hash", "approved_at", "approved_by")

AC_SECTION = "Acceptance criteria"
QUESTIONS_SECTION = "Open questions"
TEST_STRATEGY_SECTION = "Test strategy"
SPEC_SECTIONS = (
    "Problem",
    "Users",
    "Stories",
    AC_SECTION,
    "Non-goals",
    "Data and provenance",
    "Metrics",
    QUESTIONS_SECTION,
)
PLAN_SECTIONS = (
    "Design",
    "Data model",
    "Contracts",
    TEST_STRATEGY_SECTION,
    "Evaluation impact",
    "Risks",
    "ADRs",
)
TASK_FIELDS = ("AC", "Files", "Test first", "Done when")
MILESTONE_FIELDS = ("Agent", "Model", "Context")

FRONTMATTER_RE = re.compile(r"^---\n([\s\S]*?)\n---(?:\n|$)")
FENCE_RE = re.compile(r"^\s*```")


def normalize(text: str) -> str:
    return text.replace("\r\n", "\n").replace("\r", "\n")


def _unquote(s: str) -> str:
    if len(s) >= 2 and s[0] == s[-1] and s[0] in "\"'":
        return s[1:-1]
    return s


def _parse_value(raw: str) -> str | list[str]:
    if raw.startswith("[") and raw.endswith("]"):
        inner = raw[1:-1].strip()
        return [_unquote(x.strip()) for x in inner.split(",")] if inner else []
    return _unquote(raw)


def parse_frontmatter(text: str) -> tuple[dict[str, str | list[str]] | None, str]:
    src = normalize(text)
    m = FRONTMATTER_RE.match(src)
    if not m:
        return None, src
    data: dict[str, str | list[str]] = {}
    for line in m.group(1).split("\n"):
        kv = re.match(r"^([A-Za-z_][\w-]*):\s*(.*)$", line)
        if kv:
            data[kv.group(1)] = _parse_value(kv.group(2).strip())
    return data, src[m.end() :]


def set_frontmatter_fields(text: str, fields: dict[str, str]) -> str:
    """Rewrite frontmatter fields, keeping the rest of the file byte for byte."""
    src = normalize(text)
    m = FRONTMATTER_RE.match(src)
    if not m:
        raise ValueError("the file has no frontmatter")
    lines = m.group(1).split("\n")
    for key, value in fields.items():
        line = f"{key}: {value}"
        idx = next((i for i, item in enumerate(lines) if item.startswith(f"{key}:")), -1)
        if idx >= 0:
            lines[idx] = line
        else:
            lines.append(line)
    return "---\n" + "\n".join(lines) + "\n---\n" + src[m.end() :]


def split_sections(body: str) -> dict[str, str]:
    """`## Title` -> content (`###` stay inside their section)."""
    sections: dict[str, str] = {}
    current: str | None = None
    buf: list[str] = []
    in_fence = False
    for line in normalize(body).split("\n"):
        if FENCE_RE.match(line):
            in_fence = not in_fence
        h = None if in_fence else re.match(r"^##\s+(.+?)\s*$", line)
        if h:
            if current is not None:
                sections[current] = "\n".join(buf)
            current, buf = h.group(1), []
        elif current is not None:
            buf.append(line)
    if current is not None:
        sections[current] = "\n".join(buf)
    return sections


def top_level_bullets(text: str) -> list[str]:
    """Top-level list items; indented lines are glued to the previous item."""
    items: list[str] = []
    cur: str | None = None
    for line in normalize(text).split("\n"):
        b = re.match(r"^[-*]\s+(.*)$", line)
        if b:
            if cur is not None:
                items.append(cur)
            cur = b.group(1)
        elif cur is not None and re.match(r"^\s+\S", line):
            cur += "\n" + line.strip()
        elif cur is not None:
            items.append(cur)
            cur = None
    if cur is not None:
        items.append(cur)
    return items


@dataclass
class AcceptanceCriterion:
    id: str
    text: str


def parse_acceptance_criteria(section: str) -> tuple[list[AcceptanceCriterion], list[str]]:
    acs: list[AcceptanceCriterion] = []
    malformed: list[str] = []
    for item in top_level_bullets(section):
        m = re.match(r"^\*\*(AC-\d{3}-\d{2})\*\*\s*[—–-]\s*([\s\S]+)$", item)
        if m:
            acs.append(AcceptanceCriterion(m.group(1), re.sub(r"\s+", " ", m.group(2)).strip()))
        else:
            malformed.append(item.split("\n")[0])
    return acs, malformed


@dataclass
class Task:
    id: str
    done: bool
    title: str
    fields: dict[str, str]
    raw: str


def parse_tasks(text: str) -> tuple[list[Task], list[str]]:
    tasks: list[Task] = []
    malformed: list[str] = []
    cur: dict | None = None
    for line in normalize(text).split("\n"):
        t = re.match(r"^- \[( |x|X)\]\s+\*\*(T\d{2,3})\*\*\s*(.*)$", line)
        if t:
            cur = {
                "id": t.group(2),
                "done": t.group(1) != " ",
                "title": t.group(3).strip(),
                "fields": {},
                "lines": [line],
            }
            tasks.append(cur)  # type: ignore[arg-type]
            continue
        if re.match(r"^- \[( |x|X)\]", line):
            malformed.append(line)
            cur = None
            continue
        if cur is not None and re.match(r"^\s+\S", line):
            cur["lines"].append(line)
        f = re.match(r"^\s+[-*]\s+([^:]+):\s*(.*)$", line) if cur is not None else None
        if f and cur is not None:
            cur["fields"][f.group(1).strip()] = f.group(2).strip()
        elif re.match(r"^\S", line):
            cur = None
    parsed = [
        Task(t["id"], t["done"], t["title"], t["fields"], "\n".join(t["lines"]))  # type: ignore[index]
        for t in tasks
    ]
    return parsed, malformed


@dataclass
class Milestone:
    id: str
    title: str
    fields: dict[str, str] = field(default_factory=dict)
    task_ids: list[str] = field(default_factory=list)


def parse_milestones(text: str) -> list[Milestone]:
    """`## H1 — Title` with its fields (`- Agent:`, `- Model:`, `- Context:`) before the tasks it groups."""
    milestones: list[Milestone] = []
    cur: Milestone | None = None
    for line in normalize(text).split("\n"):
        h = re.match(r"^##\s+(.+?)\s*$", line)
        if h:
            m = re.match(r"^(H\d+)\s*[—–-]\s*(.+)$", h.group(1))
            cur = Milestone(m.group(1), m.group(2)) if m else None
            if cur:
                milestones.append(cur)
            continue
        if cur is None:
            continue
        t = re.match(r"^- \[(?: |x|X)\]\s+\*\*(T\d{2,3})\*\*", line)
        if t:
            cur.task_ids.append(t.group(1))
            continue
        f = re.match(r"^-\s+([^:]+):\s*(.*)$", line) if not cur.task_ids else None
        if f:
            cur.fields[f.group(1).strip()] = f.group(2).strip()
    return milestones


@dataclass
class ContextRef:
    ref: str
    file: str
    heading: str


def context_refs(field_value: str | None) -> list[ContextRef]:
    """`Context` lists sections in backticks: `plan.md#Data model`. No `/` = file of the spec folder."""
    refs = []
    for m in re.finditer(r"`([^`]+)`", field_value or ""):
        file, _, heading = m.group(1).partition("#")
        refs.append(ContextRef(m.group(1), file.strip(), heading.strip()))
    return refs


def extract_section(text: str, heading: str) -> str | None:
    """Section of a markdown file by its exact heading (any level), up to the next heading of equal or higher level."""
    lines = normalize(text).split("\n")
    start, level, in_fence = -1, 0, False
    for i, line in enumerate(lines):
        if FENCE_RE.match(line):
            in_fence = not in_fence
        h = None if in_fence else re.match(r"^(#{1,6})\s+(.+?)\s*$", line)
        if not h:
            continue
        if start >= 0 and len(h.group(1)) <= level:
            return "\n".join(lines[start:i]).rstrip()
        if start < 0 and h.group(2) == heading:
            start, level = i, len(h.group(1))
    return "\n".join(lines[start:]).rstrip() if start >= 0 else None


def ac_ids_in(text: str | None) -> list[str]:
    seen: dict[str, None] = {}
    for m in AC_ID_RE.finditer(text or ""):
        seen.setdefault(m.group(0), None)
    return list(seen)


@dataclass
class Spec:
    dir_name: str
    dir_id: str | None
    rel_dir: str
    spec_text: str | None
    plan_text: str | None
    tasks_text: str | None
    meta: dict[str, str | list[str]] | None
    sections: dict[str, str]
    acs: list[AcceptanceCriterion]
    malformed_acs: list[str]
    plan_sections: dict[str, str] | None
    tasks: list[Task] | None
    malformed_tasks: list[str]
    milestones: list[Milestone]

    def meta_str(self, key: str) -> str:
        value = (self.meta or {}).get(key, "")
        return value if isinstance(value, str) else ""


def resolve_context_ref(root: Path, spec: Spec, ref: ContextRef) -> tuple[str | None, str | None]:
    """Returns (text, error)."""
    if not ref.heading:
        return None, f'"{ref.ref}" does not name a section (format: `plan.md#Section title`)'
    path = root / ref.file if "/" in ref.file else root / spec.rel_dir / ref.file
    if not path.exists():
        return None, f'"{ref.ref}": {ref.file} does not exist'
    text = extract_section(path.read_text(encoding="utf-8"), ref.heading)
    if text is None:
        return None, f'"{ref.ref}": {ref.file} has no section "{ref.heading}"'
    return text, None


def load_spec(root: Path, dir_name: str) -> Spec:
    base = root / SPECS_DIR / dir_name

    def read(name: str) -> str | None:
        p = base / name
        return normalize(p.read_text(encoding="utf-8")) if p.exists() else None

    spec_text, plan_text, tasks_text = read("spec.md"), read("plan.md"), read("tasks.md")
    meta, body = parse_frontmatter(spec_text) if spec_text else (None, "")
    sections = split_sections(body)
    acs, malformed_acs = parse_acceptance_criteria(sections[AC_SECTION]) if AC_SECTION in sections else ([], [])
    tasks, malformed_tasks = parse_tasks(tasks_text) if tasks_text else (None, [])
    m = SPEC_DIR_RE.match(dir_name)
    return Spec(
        dir_name=dir_name,
        dir_id=m.group(1) if m else None,
        rel_dir=f"{SPECS_DIR}/{dir_name}",
        spec_text=spec_text,
        plan_text=plan_text,
        tasks_text=tasks_text,
        meta=meta,
        sections=sections,
        acs=acs,
        malformed_acs=malformed_acs,
        plan_sections=split_sections(plan_text) if plan_text else None,
        tasks=tasks,
        malformed_tasks=malformed_tasks,
        milestones=parse_milestones(tasks_text) if tasks_text else [],
    )


def load_specs(root: Path) -> list[Spec]:
    d = root / SPECS_DIR
    if not d.exists():
        return []
    names = sorted(p.name for p in d.iterdir() if p.is_dir() and not p.name.startswith("_"))
    return [load_spec(root, n) for n in names]


def _canonical(text: str) -> str:
    return "\n".join(line.rstrip() for line in normalize(text).split("\n")).rstrip()


def _strip_approval_fields(spec_text: str) -> str:
    src = normalize(spec_text)
    m = FRONTMATTER_RE.match(src)
    if not m:
        return src
    kept = [line for line in m.group(1).split("\n") if not any(line.startswith(f"{k}:") for k in APPROVAL_FIELDS)]
    return "---\n" + "\n".join(kept) + "\n---\n" + src[m.end() :]


def approval_hash(spec: Spec) -> str:
    """The approval hash covers spec.md (without the approval fields) and plan.md.

    tasks.md is left out on purpose: tasks get adjusted during the build without changing the contract.
    """
    h = hashlib.sha256()
    h.update(_canonical(_strip_approval_fields(spec.spec_text or "")).encode("utf-8"))
    h.update(b"\n\x00plan\x00\n")
    h.update(_canonical(spec.plan_text or "").encode("utf-8"))
    return "sha256:" + h.hexdigest()


def is_approved(spec: Spec) -> bool:
    return spec.meta_str("status") == "approved"


def hash_matches(spec: Spec) -> bool:
    return spec.meta_str("approved_hash") == approval_hash(spec)


def derive_status(spec: Spec, covered_ids: set[str]) -> str:
    """Derived status (docs/workflow.md). Nobody writes it by hand."""
    status = spec.meta_str("status")
    if status == "superseded":
        return "superseded"
    if status != "approved":
        return "draft"
    if not hash_matches(spec):
        return "stale"
    tasks = spec.tasks or []
    done = sum(1 for t in tasks if t.done)
    all_covered = all(a.id in covered_ids for a in spec.acs)
    if tasks and done == len(tasks) and all_covered:
        return "done"
    if done > 0:
        return "in-progress"
    return "approved"
