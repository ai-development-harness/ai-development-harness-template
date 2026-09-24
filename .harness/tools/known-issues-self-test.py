#!/usr/bin/env python3
"""Known-issue regressions и release freeze для ещё не исправленных defects.

Каждый known case описывает **правильное** поведение и сейчас обязан падать
ровно известным symptom-ом (XFAIL). Если case начинает проходить (XPASS),
self-test падает: defect исправлен, и case нужно перенести в постоянный
regression suite, удалив его из KNOWN_ISSUES вместе с соответствующим
release freeze ниже. Любой другой исход (сломанный fixture, новый symptom)
является обычным FAIL.

Release freeze запрещает изменения, которые текущий updater применяет
некорректно, пока соответствующий defect не исправлен. Иначе следующий
release сломает update существующих проектов ещё до исправления engine.
"""
from __future__ import annotations

from pathlib import Path
import hashlib
import json
import re
import shutil
import subprocess
import tempfile
import tomllib
from typing import Callable

import harness_update
import template_contract
from harness_update import UpdateError, apply_update


SOURCE_ROOT = Path(__file__).resolve().parents[2]
ISSUE_URL = "https://github.com/ai-development-harness/ai-development-harness-template/issues/"


class KnownFailure(Exception):
    """Наблюдаемый symptom совпал с known defect."""


def run(root: Path, *args: str, check: bool = True) -> subprocess.CompletedProcess[str]:
    proc = subprocess.run(args, cwd=root, text=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
    if check and proc.returncode:
        raise AssertionError(f"{' '.join(args)} failed ({proc.returncode}):\n{proc.stdout}\n{proc.stderr}")
    return proc


def write(root: Path, path: str, text: str) -> None:
    target = root / path
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(text, encoding="utf-8", newline="\n")


def git_init(root: Path) -> None:
    run(root, "git", "init", "-q", "-b", "main")
    run(root, "git", "config", "user.email", "known-issues@example.invalid")
    run(root, "git", "config", "user.name", "Known Issues")


def commit_all(root: Path, message: str) -> None:
    run(root, "git", "add", "-A")
    run(root, "git", "commit", "-qm", message)


# --- Synthetic minimal release pair ------------------------------------------

def synthetic_policy(*, harness_owned: list[str], markers: dict[str, list[str]]) -> str:
    owned = "\n".join(f'  "{item}",' for item in harness_owned)
    marker_paths = ", ".join(f'"{path}"' for path in markers)
    marker_tables = "\n".join(
        f'[markers."{path}"]\nblocks = [{", ".join(json.dumps(b) for b in blocks)}]\n'
        for path, blocks in markers.items()
    )
    return f'''[source]
repository = "example/harness"
default_branch = "main"
tag_pattern = '^v\\d+\\.\\d+\\.\\d+$'
update_manifest = ".harness/harness-update-graph.json"

[state]
lock_file = ".harness/harness.lock.json"
report_directory = "reports"

[ownership]
harness_owned = [
  ".harness/harness-update-graph.json",
  ".harness/harness-update.toml",
  ".harness/tools/**",
{owned}
]
shared = [".harness/manifest.yaml"]
marker_merge = [{marker_paths}]

{marker_tables}'''


def synthetic_manifest(release: str) -> str:
    return f'''harness:
  version: "1"
  release: "{release}"
project:
  initialized: true
repository:
  harnessUpdatePolicy: .harness/harness-update.toml
'''


def synthetic_graph(latest: str, transitions: list[tuple[str, str]]) -> str:
    return json.dumps(
        {
            "schemaVersion": 1,
            "latest": latest,
            "transitions": [
                {"from": a, "to": b, "kind": "standard", "reloadRequired": False}
                for a, b in transitions
            ],
        },
        indent=2,
    ) + "\n"


PASS_VALIDATOR = 'print("HARNESS VALIDATION: PASS")\n'


def synthetic_pair(
    tmp: Path,
    *,
    base: dict[str, str],
    target: dict[str, str | None],
    project_overrides: dict[str, str] | None = None,
) -> tuple[Path, Path]:
    """Source v1.0.0 → v1.1.0 (standard, без reload) и project на v1.0.0."""
    source = tmp / "source"
    source.mkdir()
    git_init(source)
    base_files = {
        ".harness/manifest.yaml": synthetic_manifest("1.0.0"),
        ".harness/harness-update-graph.json": synthetic_graph("v1.0.0", []),
        ".harness/tools/validate.py": PASS_VALIDATOR,
        **base,
    }
    for path, text in base_files.items():
        write(source, path, text)
    commit_all(source, "v1.0.0")
    run(source, "git", "tag", "v1.0.0")

    target_files: dict[str, str | None] = {
        ".harness/manifest.yaml": synthetic_manifest("1.1.0"),
        ".harness/harness-update-graph.json": synthetic_graph("v1.1.0", [("v1.0.0", "v1.1.0")]),
        **target,
    }
    for path, text in target_files.items():
        if text is None:
            (source / path).unlink()
        else:
            write(source, path, text)
    commit_all(source, "v1.1.0")
    run(source, "git", "tag", "v1.1.0")

    project = tmp / "project"
    project.mkdir()
    for path, text in {**base_files, **(project_overrides or {})}.items():
        write(project, path, text)
    write(
        project,
        ".harness/harness.lock.json",
        json.dumps(
            {
                "schemaVersion": 1,
                "harnessVersion": "1",
                "release": "1.0.0",
                "source": {"repository": "example/harness", "ref": "v1.0.0"},
                "updatedAt": None,
            },
            indent=2,
        )
        + "\n",
    )
    git_init(project)
    commit_all(project, "project base")
    return source, project


def case_update_executes_target_code(tmp: Path) -> None:
    """#98: APPLY не должен исполнять код target-релиза до инспекции diff."""
    base_policy = synthetic_policy(harness_owned=[], markers={})
    source, project = synthetic_pair(
        tmp,
        base={".harness/harness-update.toml": base_policy},
        target={
            ".harness/tools/validate.py": (
                "from pathlib import Path\n"
                "Path('.target-code-ran').write_text('x')\n"
                + PASS_VALIDATOR
            ),
        },
    )
    try:
        apply_update(project, source_url=str(source))
    except UpdateError:
        pass
    if (project / ".target-code-ran").exists():
        raise KnownFailure("target validate.py executed during APPLY")


def case_retired_path_deleted(tmp: Path) -> None:
    """#99: path, переданный из harness_owned проекту, должен сохраниться."""
    source, project = synthetic_pair(
        tmp,
        base={
            ".harness/harness-update.toml": synthetic_policy(
                harness_owned=["docs/notes.md"], markers={}
            ),
            "docs/notes.md": "handed over to project\n",
        },
        target={
            ".harness/harness-update.toml": synthetic_policy(harness_owned=[], markers={}),
        },
    )
    result = apply_update(project, source_url=str(source))
    if result.get("status") != "UPDATED":
        raise AssertionError(f"unexpected APPLY result: {result}")
    if not (project / "docs/notes.md").is_file():
        raise KnownFailure("docs/notes.md deleted although present in target tree")


def agents_text(project_body: str, *, badges: bool) -> str:
    extra = "\n<!-- BADGES:START -->\ntarget badges\n<!-- BADGES:END -->\n" if badges else ""
    return f"# Agents\n\n<!-- PROJECT:START -->{project_body}<!-- PROJECT:END -->\n{extra}"


def case_new_marker_block(tmp: Path) -> None:
    """#100: новый marker block target-релиза не должен блокировать update."""
    source, project = synthetic_pair(
        tmp,
        base={
            ".harness/harness-update.toml": synthetic_policy(
                harness_owned=[], markers={"AGENTS.md": ["PROJECT"]}
            ),
            "AGENTS.md": agents_text("\ntemplate\n", badges=False),
        },
        target={
            ".harness/harness-update.toml": synthetic_policy(
                harness_owned=[], markers={"AGENTS.md": ["PROJECT", "BADGES"]}
            ),
            "AGENTS.md": agents_text("\ntemplate\n", badges=True),
        },
        project_overrides={"AGENTS.md": agents_text("\nLOCAL PROJECT\n", badges=False)},
    )
    try:
        result = apply_update(project, source_url=str(source))
    except UpdateError as exc:
        if exc.code == "MARKER_DRIFT" and "BADGES" in exc.message:
            raise KnownFailure(f"{exc.code}: {exc.message}") from exc
        raise
    text = (project / "AGENTS.md").read_text(encoding="utf-8")
    if result.get("status") != "UPDATED" or "LOCAL PROJECT" not in text or "BADGES:START" not in text:
        raise AssertionError(f"unexpected marker merge result: {result}\n{text}")


# --- Real template copy -------------------------------------------------------

def copy_tracked(target: Path) -> None:
    raw = run(SOURCE_ROOT, "git", "ls-files", "-z").stdout
    for rel in raw.split("\0"):
        if not rel:
            continue
        source = SOURCE_ROOT / rel
        if not source.is_file():
            continue
        destination = target / rel
        destination.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(source, destination)


def set_release(root: Path, release: str, edge: tuple[str, str]) -> None:
    manifest = root / ".harness/manifest.yaml"
    manifest.write_text(
        re.sub(r'release: "[0-9.]+"', f'release: "{release}"', manifest.read_text(encoding="utf-8"), count=1),
        encoding="utf-8",
    )
    lock_path = root / ".harness/harness.lock.json"
    lock = json.loads(lock_path.read_text(encoding="utf-8"))
    lock["release"] = release
    lock["source"]["ref"] = f"v{release}"
    lock_path.write_text(json.dumps(lock, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    graph_path = root / ".harness/harness-update-graph.json"
    graph = json.loads(graph_path.read_text(encoding="utf-8"))
    graph["latest"] = f"v{release}"
    graph["transitions"].append(
        {"from": edge[0], "to": edge[1], "kind": "standard", "reloadRequired": False}
    )
    graph_path.write_text(json.dumps(graph, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def case_preinit_template_non_reload_hop(tmp: Path) -> None:
    """#101: UPDATED обязан оставлять pre-INIT project проходимым для GIT CHECK."""
    graph = json.loads((SOURCE_ROOT / ".harness/harness-update-graph.json").read_text(encoding="utf-8"))
    current = graph["latest"]
    major, minor, _patch = (int(part) for part in current.removeprefix("v").split("."))
    first = f"{major}.{minor + 1}.0"
    second = f"{major}.{minor + 2}.0"

    source = tmp / "source"
    source.mkdir()
    copy_tracked(source)
    git_init(source)
    set_release(source, first, (current, f"v{first}"))
    commit_all(source, f"v{first}")
    run(source, "git", "tag", f"v{first}")

    project = tmp / "project"
    shutil.copytree(source, project, ignore=shutil.ignore_patterns(".git"))
    git_init(project)
    commit_all(project, "project baseline")

    # Target release добавляет additive section в ADR template без reload.
    contract_path = source / ".harness/tools/template_contract.py"
    contract = contract_path.read_text(encoding="utf-8")
    start = contract.index('ADR_TEMPLATE = """')
    end = contract.index('"""', start + len('ADR_TEMPLATE = """'))
    contract = contract[:end].rstrip("\n") + "\n\n## Follow-up\n\n- ...\n" + contract[end:]
    contract_path.write_text(contract, encoding="utf-8")
    adr_template = source / "docs/adr/TEMPLATE.md"
    adr_template.write_text(
        adr_template.read_text(encoding="utf-8").rstrip("\n") + "\n\n## Follow-up\n\n- ...\n",
        encoding="utf-8",
    )
    set_release(source, second, (f"v{first}", f"v{second}"))
    commit_all(source, f"v{second}")
    run(source, "git", "tag", f"v{second}")

    result = apply_update(project, source_url=str(source))
    if result.get("status") != "UPDATED":
        return
    gate = run(project, "python3", ".harness/tools/validate.py", "--mode", "commit", check=False)
    if gate.returncode == 0:
        return
    if "template baseline drift before PROJECT INIT" in gate.stdout:
        raise KnownFailure("UPDATED left pre-INIT template drift; GIT CHECK fails")
    raise AssertionError(gate.stdout + gate.stderr)


def case_setext_heading_merge_marker(tmp: Path) -> None:
    """#110: Markdown setext heading не является merge-conflict marker."""
    copy_tracked(tmp)
    git_init(tmp)
    write(tmp, "docs/setext.md", "Title\n=======\n\ntext\n")
    commit_all(tmp, "baseline with setext heading")
    proc = run(tmp, "python3", ".harness/tools/validate.py", "--mode", "manual", check=False)
    if proc.returncode == 0:
        return
    if "merge-conflict marker detected: docs/setext.md" in proc.stdout:
        raise KnownFailure("setext heading reported as merge-conflict marker")
    raise AssertionError(proc.stdout + proc.stderr)


KNOWN_ISSUES: list[tuple[int, str, Callable[[Path], None]]] = [
    (98, "APPLY executes target release code", case_update_executes_target_code),
    (99, "retired harness_owned path is deleted", case_retired_path_deleted),
    (100, "new marker block blocks update", case_new_marker_block),
    (101, "pre-INIT non-reload template hop breaks GIT CHECK", case_preinit_template_non_reload_hop),
    (110, "setext heading reported as merge marker", case_setext_heading_merge_marker),
]


# --- Release freeze -----------------------------------------------------------
# Snapshot v0.8.0. Снимать вместе с исправлением соответствующего issue.

# #99: удаление harness_owned pattern сейчас удаляет файлы у проектов.
FROZEN_HARNESS_OWNED = {
    ".harness/harness-update-graph.json",
    ".harness/command-transitions.json",
    ".harness/reasoning-boundaries.json",
    ".agents/skills/README.md",
    ".agents/skills/init-project/**",
    ".agents/skills/add-plan-step/**",
    ".agents/skills/find-skill/**",
    ".agents/skills/install-skill/**",
    ".agents/skills/create-skill/**",
    ".agents/skills/plan-step/**",
    ".agents/skills/implement-step/**",
    ".agents/skills/review-step/**",
    ".agents/skills/fix-step/**",
    ".agents/skills/run-step/**",
    ".agents/skills/audit-step/**",
    ".agents/skills/project-status/**",
    ".agents/skills/reconcile-project/**",
    ".agents/skills/release-check/**",
    ".agents/skills/requirements-review/**",
    ".agents/skills/architecture-change/**",
    ".agents/skills/documentation-sync/**",
    ".agents/skills/code-review/**",
    ".agents/skills/security-review/**",
    ".agents/skills/write-tests/**",
    ".agents/skills/git-workflow/**",
    ".agents/skills/quick-fix/**",
    ".agents/skills/generate-github-templates/**",
    ".agents/skills/update-harness/**",
    ".codex/README.md",
    ".claude/README.md",
    ".harness/README.md",
    ".harness/harness-policy.toml",
    ".harness/harness-update.toml",
    ".harness/docs/**",
    "planning/harness-updates/README.md",
    ".harness/tools/**",
}

# #100: новый marker_merge path или block сейчас даёт MARKER_DRIFT у проектов.
FROZEN_MARKERS = {
    "AGENTS.md": {"PROJECT-CONTEXT", "SKILL-ROUTING"},
    "README.md": {"PROJECT"},
}

# #101: изменение template definitions ломает pre-INIT проекты после UPDATED.
FROZEN_TEMPLATE_SHA256 = {
    "STEP_TEMPLATE": "2805ed635ce4226e42e389272c544dc0729133a42addd79702da75ff60aa9ed0",
    "REQ_TEMPLATE": "170598877e69690a5804176f425ccb292b988f51c1f54b9118e0862d2bf2176d",
    "ADR_TEMPLATE": "100caccd1e18cf14949a2517a208ace366661d621b144423ab841743b5b120ab",
    "OQ_TEMPLATE": "baf2a4cf5029d0edea3cfa7d3a4e24f936589d79ccf59f53be079ca40d5ad261",
    "REVIEW_TEMPLATE": "eb245b7ede055ef4fcaa35783d6f980b3ea2e14678b8351cbe80b11c806dfe2b",
    "PLAN_REVIEW_TEMPLATE": "140a89358948d3752756f8cefbe1ddd45d59cb20c4b792301119e9d7ecea6619",
    "INIT_REVIEW_TEMPLATE": "1ebff693148ee7c714abc14c2c7262303d4906591901accbcbe9b3b0aae3d970",
    "AUDIT_TEMPLATE": "bd425e8eecf3703afd90c9a044d49b3eb4e2994a678aac4dd86db40e4812da47",
    "RELEASE_TEMPLATE": "f35fc40bad1eac2a3d5c8331f7180783051a155c52de072ac546b5218978e1a0",
    "SKILL_SEARCH_TEMPLATE": "0a4e518806dbfb317d94df0ab17beadd135998c15e8d420eb33ca7f5e291d74a",
}


def release_freeze_errors() -> list[str]:
    known = {number for number, _title, _case in KNOWN_ISSUES}
    policy = tomllib.loads((SOURCE_ROOT / harness_update.UPDATE_POLICY_PATH).read_text(encoding="utf-8"))
    ownership = policy.get("ownership", {})
    errors: list[str] = []

    if 99 in known:
        removed = sorted(FROZEN_HARNESS_OWNED - set(ownership.get("harness_owned", [])))
        if removed:
            errors.append(
                f"harness_owned patterns removed while {ISSUE_URL}99 is open: {removed}"
            )

    if 100 in known:
        markers = {
            path: set(item.get("blocks", []))
            for path, item in policy.get("markers", {}).items()
        }
        for path in ownership.get("marker_merge", []):
            added = sorted(markers.get(path, set()) - FROZEN_MARKERS.get(path, set()))
            if path not in FROZEN_MARKERS:
                errors.append(f"new marker_merge path while {ISSUE_URL}100 is open: {path}")
            elif added:
                errors.append(
                    f"new marker blocks for {path} while {ISSUE_URL}100 is open: {added}"
                )

    if 101 in known:
        for name, expected in FROZEN_TEMPLATE_SHA256.items():
            actual = hashlib.sha256(getattr(template_contract, name).encode("utf-8")).hexdigest()
            if actual != expected:
                errors.append(
                    f"template_contract.{name} changed while {ISSUE_URL}101 is open"
                )
    return errors


def main() -> int:
    failed = False
    for number, title, case in KNOWN_ISSUES:
        label = f"#{number} {title}"
        with tempfile.TemporaryDirectory(prefix=f"harness-known-{number}-") as tmp:
            try:
                case(Path(tmp))
            except KnownFailure as exc:
                print(f"XFAIL {label}: {exc}")
                continue
            except Exception as exc:  # noqa: BLE001 - любой другой исход = broken case
                failed = True
                print(f"FAIL {label}: unexpected outcome: {type(exc).__name__}: {exc}")
                continue
        failed = True
        print(
            f"XPASS {label}: defect no longer reproduces; move the case to a permanent "
            "regression suite and remove it and its release freeze from known-issues-self-test.py"
        )

    freeze = release_freeze_errors()
    for item in freeze:
        failed = True
        print(f"RELEASE FREEZE: {item}")

    print(f"KNOWN ISSUES SELF-TEST: {'FAIL' if failed else 'PASS'}")
    return 1 if failed else 0


if __name__ == "__main__":
    raise SystemExit(main())
