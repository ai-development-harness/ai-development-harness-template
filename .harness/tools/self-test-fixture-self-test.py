#!/usr/bin/env python3
"""Regression effective Harness checkout copy after HARNESS UPDATE."""
from __future__ import annotations

from pathlib import Path
import subprocess
import importlib.util
import json
import stat
import sys
import tempfile

from self_test_fixture import (copy_effective_harness_checkout, isolate_project_artifacts,
                               set_fixture_verification)
from harness_config import load_manifest, task_directory
from projection_contract import write_projections
from verification import run_step_verification
from verification_incremental import validate_impact_map


def run(root: Path, *args: str) -> None:
    proc = subprocess.run(
        args,
        cwd=root,
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        check=False,
    )
    if proc.returncode != 0:
        raise AssertionError(
            f"{' '.join(args)} failed ({proc.returncode}): "
            f"{proc.stdout}\n{proc.stderr}"
        )


def write(path: Path, content: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")


def verification_host(source: Path, root: Path, map_path: str) -> None:
    """Создать initialized downstream с двумя STEP и настоящей project policy.

    Runtime копируется из effective проверяемого checkout. Нестандартный путь
    карты, staged/unstaged файлы и режим executable моделируют исходный #387.
    """
    spec = importlib.util.spec_from_file_location("fixture_verification", source / ".harness/tools/verification-self-test.py")
    assert spec and spec.loader
    fixture = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(fixture)
    root.mkdir(parents=True, exist_ok=True)
    fixture.prepare(root)
    (task_directory(root) / "STEP-001.md").unlink()
    placeholder = root / "docs/requirements/REQ-001-template.md"
    placeholder.unlink(missing_ok=True)
    write(root / "docs/requirements/REQ-901-fixture.md", """---
schema: 1
id: REQ-901
priority: medium
source: issue-387
steps:
  - STEP-971
  - STEP-972
adrs: []
---

# REQ-901 — Изолированная политика Verification

## Requirement

Локальные команды подтверждают контракт без утечки host policy в другие fixtures.

## Rationale

Проверить регрессию изоляции #387 на initialized downstream.

## Acceptance

- Проверки двух STEP проходят с собственной картой проекта.
""")
    checks = {}
    for number in (971, 972):
        sid = f"STEP-{number}"
        command = f'python3 -c "print({number})"'
        write(task_directory(root) / f"{sid}.md",
              fixture.task(fixture.command_line(command)).replace("STEP-001", sid)
              .replace("status: in_progress", "status: planned")
              .replace("requirements: []", "requirements:\n  - REQ-901"))
        checks[sid] = {"checks": [{"id": "local", "command": command,
                       "inputs": ["host/**"], "dependsOn": [],
                       "acceptance": ["Verification PASS."], "reusable": True}],
                       "infrastructure": [".harness/manifest.yaml", map_path]}
    write(root / map_path, json.dumps({"schemaVersion": 1, "steps": checks}) + "\n")
    write(root / "host/source.txt", "Данные исходного проекта.\n")
    write(root / "host/executable.sh", "#!/bin/sh\n# Исполняемый вход исходного проекта.\nexit 0\n")
    (root / "host/executable.sh").chmod(0o755)
    manifest = root / ".harness/manifest.yaml"
    write(manifest, manifest.read_text(encoding="utf-8")
          .replace("  initialized: false", "  initialized: true")
          .replace("  name: null", "  name: verification-fixture-host")
          .replace("  initializedAt: null", '  initializedAt: "2026-11-05T12:00:00Z"'))
    set_fixture_verification(root, {"impactMap": map_path, "manualContinuation": {
        "STEP-971": {"readOnly": True, "localCommands": [checks["STEP-971"]["checks"][0]["command"]],
                     "repeatCommands": []},
    }})
    write_projections(root)
    run(root, "git", "add", ".")
    run(root, "git", "commit", "-qm", "Настроить initialized host с Verification policy")
    write(root / "host/source.txt", "Staged изменение исходного проекта.\n")
    run(root, "git", "add", "host/source.txt")
    write(root / "host/source.txt", "Unstaged изменение исходного проекта.\n")


def snapshot(root: Path) -> dict:
    """Сравнить содержимое/modes исходного дерева и Git index после изоляции копий."""
    result = {path.relative_to(root).as_posix(): (path.read_bytes(), stat.S_IMODE(path.stat().st_mode))
              for path in root.rglob("*") if path.is_file() and ".git" not in path.relative_to(root).parts}
    result[".git/index"] = (root / ".git/index").read_bytes()
    return result


def verification_isolation(source: Path, base: Path) -> None:
    """Проверить host policy, оба copy режима и собственную карту после isolation."""
    for number, map_path in enumerate(("docs/verification/impact-map.json", "policies/custom/host-map.json")):
        host = base / f"host-{number}"
        verification_host(source, host, map_path)
        assert not validate_impact_map(host)
        assert run_step_verification(host, "STEP-971")["status"] == "PASS"
        steady = run_step_verification(host, "STEP-971")
        assert steady["status"] == "PASS" and steady["verificationMode"] == "incremental", steady
        run(host, sys.executable, ".harness/tools/validate.py", "--mode", "ci")
        original = snapshot(host)
        for minimal in (False, True):
            target = base / f"isolated-{number}-{minimal}"
            copy_effective_harness_checkout(host, target, protocol_only=minimal)
            assert load_manifest(target)["verification"]["impactMap"] == map_path
            isolate_project_artifacts(target)
            assert "verification" not in load_manifest(target)
            assert not list(task_directory(target).glob("STEP-*.md"))
            assert not validate_impact_map(target)
            assert (target / ".harness/tools/verification.py").read_bytes() == (host / ".harness/tools/verification.py").read_bytes()
            clean = (target / ".harness/manifest.yaml").read_bytes()
            isolate_project_artifacts(target)
            assert (target / ".harness/manifest.yaml").read_bytes() == clean
            # Карта исходного проекта может быть скопирована как инертный файл;
            # runtime больше не читает её и не требует отсутствующие host STEP.
            config = {"impactMap": "fixture/own-map.json"}
            set_fixture_verification(target, config)
            own = (target / ".harness/manifest.yaml").read_bytes()
            set_fixture_verification(target, config)
            assert (target / ".harness/manifest.yaml").read_bytes() == own
            assert load_manifest(target)["verification"] == config
            # Собственная карта выполняет intended сценарий на candidate runtime,
            # включая реальный incremental PASS вместо одного parser assertion.
            own_sid = "STEP-001"
            write(task_directory(target) / f"{own_sid}.md",
                  (task_directory(host) / "STEP-971.md").read_text(encoding="utf-8")
                  .replace("STEP-971", own_sid)
                  .replace("requirements:\n  - REQ-901", "requirements: []"))
            host_map = json.loads((host / map_path).read_text(encoding="utf-8"))
            write(target / "fixture/own-map.json", json.dumps({
                "schemaVersion": 1, "steps": {own_sid: host_map["steps"]["STEP-971"]},
            }) + "\n")
            for args in (("init", "-q", "-b", "main"),
                         ("config", "user.name", "Fixture"),
                         ("config", "user.email", "fixture@example.invalid"),
                         ("add", "."), ("commit", "-qm", "Настроить собственную fixture карту")):
                run(target, "git", *args)
            assert not validate_impact_map(target)
            assert run_step_verification(target, own_sid)["status"] == "PASS"
            resumed = run_step_verification(target, own_sid)
            assert resumed["status"] == "PASS" and resumed["verificationMode"] == "incremental", resumed
            set_fixture_verification(target, None)
            set_fixture_verification(target, None)
            assert "verification" not in load_manifest(target)
        assert snapshot(host) == original


def verification_section_update(root: Path) -> None:
    """Замена узла в середине manifest сохраняет соседние values и отвергает duplicate."""
    manifest = root / ".harness/manifest.yaml"
    write(manifest, "before: true\nverification:\n  impactMap: old.json\nafter:\n  literal: '001'\n")
    set_fixture_verification(root, {"impactMap": "new.json"})
    parsed = load_manifest(root)
    assert parsed == {"before": True, "verification": {"impactMap": "new.json"}, "after": {"literal": "001"}}
    current = manifest.read_bytes()
    set_fixture_verification(root, {"impactMap": "new.json"})
    assert manifest.read_bytes() == current
    write(manifest, manifest.read_text(encoding="utf-8") + "verification:\n  impactMap: duplicate.json\n")
    invalid = manifest.read_bytes()
    try:
        set_fixture_verification(root, None)
    except ValueError:
        pass
    else:
        raise AssertionError("Duplicate manifest принят как валидный")
    assert manifest.read_bytes() == invalid


def main() -> int:
    with tempfile.TemporaryDirectory(prefix="harness-effective-fixture-") as td:
        base = Path(td)
        source = base / "source"
        target = base / "target"
        source.mkdir()
        target.mkdir()

        write(
            source / ".harness/manifest.yaml",
            (Path(__file__).resolve().parents[2] / ".harness/manifest.yaml").read_text(encoding="utf-8"),
        )
        write(
            source / ".harness/harness-update.toml",
            "[source]\nupdate_manifest = 'config/update-graph.json'\n"
            "[state]\nlock_file = '.harness/harness.lock.json'\nreport_directory = 'work/updates'\n"
            "[ownership]\n"
            "harness_owned = [\n  \".harness/tools/**\",\n]\n"
            "shared = [\n  \".github/**\",\n]\n"
            "marker_merge = [\n  \"README.md\",\n]\n",
        )
        manifest = source / ".harness/manifest.yaml"
        manifest.write_text(manifest.read_text(encoding="utf-8").replace("gitPolicy: .harness/git-policy.toml", "gitPolicy: config/git-policy.toml"), encoding="utf-8")
        write(source / "config/git-policy.toml", "version = 1\n")
        write(source / "config/update-graph.json", "{}\n")
        write(source / "work/updates/README.md", "отчёты\n")
        write(source / "README.md", "tracked\n")
        write(source / "apps/product.txt", "продуктовый файл\n")
        write(source / "docs/skills/REGISTRY.md", "реестр\n")
        write(source / "planning/tasks/TEMPLATE.md", "проектный шаблон\n")
        write(source / ".harness/harness.lock.json", "{}\n")

        run(source, "git", "init", "-q", "-b", "main")
        run(source, "git", "config", "user.email", "fixture@example.invalid")
        run(source, "git", "config", "user.name", "Fixture")
        run(source, "git", "add", ".")
        run(source, "git", "commit", "-qm", "baseline")

        write(source / ".harness/tools/new-tool.py", "print('managed')\n")
        write(source / "notes/local.txt", "project untracked\n")

        copy_effective_harness_checkout(source, target)

        assert (target / "README.md").read_text(encoding="utf-8") == "tracked\n"
        assert (target / ".harness/tools/new-tool.py").read_text(
            encoding="utf-8"
        ) == "print('managed')\n"
        assert not (target / "notes/local.txt").exists()
        assert (target / "apps/product.txt").is_file()

        minimal = base / "minimal"
        copy_effective_harness_checkout(source, minimal, protocol_only=True)
        assert not (minimal / "apps/product.txt").exists()
        assert (minimal / "config/git-policy.toml").is_file()
        assert (minimal / "config/update-graph.json").is_file()
        assert (minimal / "work/updates/README.md").is_file()
        assert (minimal / ".harness/tools/new-tool.py").is_file()
        assert (minimal / ".harness/harness.lock.json").is_file()
        assert (minimal / "docs/skills/REGISTRY.md").is_file()
        assert (minimal / "planning/tasks/TEMPLATE.md").read_text(encoding="utf-8") == "проектный шаблон\n"
        assert (source / "apps/product.txt").read_text(encoding="utf-8") == "продуктовый файл\n"

    with tempfile.TemporaryDirectory(prefix="harness-verification-isolation-") as td:
        verification_isolation(Path(__file__).resolve().parents[2], Path(td))
        verification_section_update(Path(td) / "section-update")
    print("self-test fixture effective checkout and Verification isolation: PASS")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
