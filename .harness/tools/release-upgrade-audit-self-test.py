#!/usr/bin/env python3
"""One-off audit: real v0.8.0 -> synthetic next release through release/updater flow.

This file lives only on the audit branch. It intentionally uses the real v0.8.0
tag and current branch tree, then prepares a synthetic v0.9.0 with pinned
maintainer-tools release helper. Both release-snapshot and source.commit-pinned
project locks are exercised.
"""
from __future__ import annotations

from io import BytesIO
import json
import os
from pathlib import Path
import shutil
import subprocess
import tarfile
import tempfile

SOURCE_ROOT = Path(__file__).resolve().parents[2]
CURRENT = "v0.8.0"
TARGET = "v0.9.0"
MAINTAINER_TOOLS_SHA = "932b37ad177af0051ed9ccb614c1a13ef3845178"
SELF_PATH = ".harness/tools/release-upgrade-audit-self-test.py"


def run(
    root: Path,
    *args: str,
    check: bool = True,
    env: dict[str, str] | None = None,
) -> subprocess.CompletedProcess[str]:
    proc = subprocess.run(
        args,
        cwd=root,
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        check=False,
        env=env,
    )
    if check and proc.returncode:
        raise AssertionError(
            f"{' '.join(args)} failed ({proc.returncode})\n"
            f"stdout:\n{proc.stdout}\nstderr:\n{proc.stderr}"
        )
    return proc


def git(root: Path, *args: str, check: bool = True) -> str:
    return run(root, "git", *args, check=check).stdout.strip()


def prepare_source(tmp: Path) -> tuple[Path, str, str]:
    source = tmp / "source"
    source.mkdir()
    git(source, "init", "-q", "-b", "main")
    git(source, "config", "user.email", "upgrade-audit@example.invalid")
    git(source, "config", "user.name", "Upgrade Audit")

    git(source, "fetch", "-q", str(SOURCE_ROOT), "HEAD")
    git(source, "reset", "--hard", "FETCH_HEAD")
    git(
        source,
        "fetch",
        "-q",
        str(SOURCE_ROOT),
        f"refs/tags/{CURRENT}:refs/tags/{CURRENT}",
    )

    audit_path = source / SELF_PATH
    if audit_path.is_file():
        audit_path.unlink()
        git(source, "add", "-A")
        git(source, "commit", "-qm", "audit: exclude one-off test from target release")

    maintainer = tmp / "maintainer-tools"
    run(
        tmp,
        "git",
        "clone",
        "-q",
        "https://github.com/ai-development-harness/maintainer-tools.git",
        str(maintainer),
    )
    git(maintainer, "checkout", "-q", MAINTAINER_TOOLS_SHA)

    release_py = maintainer / "scripts/release.py"
    release_config = maintainer / "config/release.json"
    run(
        tmp,
        "python3",
        str(release_py),
        "--config",
        str(release_config),
        "prepare",
        "--repo-dir",
        str(source),
        "--version",
        TARGET,
        "--reload-required",
        "--transition-kind",
        "standard",
    )
    run(
        tmp,
        "python3",
        str(release_py),
        "--config",
        str(release_config),
        "verify",
        "--repo-dir",
        str(source),
        "--version",
        TARGET,
    )

    run(source, "python3", ".harness/tools/validate.py", "--mode", "ci")
    git(source, "add", ".harness/manifest.yaml", ".harness/harness.lock.json",
        ".harness/harness-update-graph.json")
    git(source, "commit", "-qm", f"chore: prepare synthetic release {TARGET}")
    git(source, "tag", TARGET)

    base_oid = git(source, "rev-parse", f"{CURRENT}^{{commit}}")
    target_oid = git(source, "rev-parse", f"{TARGET}^{{commit}}")

    graph = json.loads(
        (source / ".harness/harness-update-graph.json").read_text(encoding="utf-8")
    )
    edge = next(
        item for item in graph["transitions"]
        if item["from"] == CURRENT and item["to"] == TARGET
    )
    assert edge == {
        "from": CURRENT,
        "to": TARGET,
        "kind": "standard",
        "reloadRequired": True,
    }, edge
    return source, base_oid, target_oid


def extract_release(source: Path, destination: Path) -> None:
    destination.mkdir()
    proc = subprocess.run(
        ["git", "-C", str(source), "archive", CURRENT],
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        check=False,
    )
    if proc.returncode:
        raise AssertionError(proc.stderr.decode("utf-8", errors="replace"))
    with tarfile.open(fileobj=BytesIO(proc.stdout), mode="r:") as archive:
        archive.extractall(destination)


def project_from_release(
    root: Path,
    source: Path,
    *,
    base_oid: str,
    pin_source_commit: bool,
) -> Path:
    extract_release(source, root)

    local_probe = root / ".harness/local/upgrade-audit.txt"
    local_probe.parent.mkdir(parents=True, exist_ok=True)
    local_probe.write_text("keep-local-state\n", encoding="utf-8")

    lock_path = root / ".harness/harness.lock.json"
    lock = json.loads(lock_path.read_text(encoding="utf-8"))
    assert lock["source"]["ref"] == CURRENT, lock
    assert "commit" not in lock["source"], lock
    if pin_source_commit:
        lock["source"]["commit"] = base_oid
        lock_path.write_text(
            json.dumps(lock, ensure_ascii=False, indent=2) + "\n",
            encoding="utf-8",
        )

    git(root, "init", "-q", "-b", "main")
    git(root, "config", "user.email", "project@example.invalid")
    git(root, "config", "user.name", "Upgrade Project")
    git(root, "add", ".")
    git(root, "commit", "-qm", "project from real v0.8.0")
    return root


def rewrite_env(source: Path) -> dict[str, str]:
    env = dict(os.environ)
    env.update(
        {
            "GIT_CONFIG_COUNT": "2",
            "GIT_CONFIG_KEY_0": (
                "url.file://" + str(source.resolve()) + ".insteadOf"
            ),
            "GIT_CONFIG_VALUE_0": (
                "https://github.com/"
                "ai-development-harness/ai-development-harness-template.git"
            ),
            "GIT_CONFIG_KEY_1": "protocol.file.allow",
            "GIT_CONFIG_VALUE_1": "always",
        }
    )
    return env


def dispatch(project: Path, command: str, env: dict[str, str]) -> dict:
    proc = run(
        project,
        "python3",
        ".harness/tools/harness-dispatch.py",
        "start",
        "--command",
        command,
        check=False,
        env=env,
    )
    try:
        data = json.loads(proc.stdout)
    except json.JSONDecodeError as exc:
        raise AssertionError(
            f"dispatcher returned non-JSON ({proc.returncode})\n"
            f"stdout:\n{proc.stdout}\nstderr:\n{proc.stderr}"
        ) from exc
    data["_exitCode"] = proc.returncode
    data["_stderr"] = proc.stderr
    return data


def assert_check_is_read_only(project: Path, env: dict[str, str]) -> None:
    before = git(project, "status", "--porcelain=v1", "--untracked-files=all")
    result = dispatch(project, f"HARNESS UPDATE CHECK TO {TARGET}", env)
    assert result["_exitCode"] == 0, result
    assert result["status"] == "DONE", result
    engine = result["result"]
    assert engine["status"] == "PASS", result
    assert engine["current"] == CURRENT, result
    assert engine["resolvedTarget"] == TARGET, result
    assert engine["route"] == [CURRENT, TARGET], result
    assert engine["checkedThrough"] == TARGET, result
    assert engine["reloadBoundary"] == TARGET, result
    after = git(project, "status", "--porcelain=v1", "--untracked-files=all")
    assert before == after, (before, after)


def assert_apply_and_reload(
    project: Path,
    env: dict[str, str],
    *,
    target_oid: str,
) -> None:
    result = dispatch(
        project,
        f"HARNESS UPDATE CHECK TO {TARGET} > APPLY",
        env,
    )
    assert result["_exitCode"] == 0, result
    assert result["status"] == "DONE", result
    engine = result["result"]
    assert engine["status"] == "SUCCESS", result
    assert engine["engineStatus"] == "UPDATER_RELOAD_REQUIRED", result
    assert engine["current"] == TARGET, result
    assert engine["resolvedTarget"] == TARGET, result
    assert engine["nextAction"] == {
        "kind": "reload-and-repeat",
        "command": f"HARNESS UPDATE APPLY TO {TARGET}",
    }, result

    manifest = (project / ".harness/manifest.yaml").read_text(encoding="utf-8")
    assert 'release: "0.9.0"' in manifest, manifest
    lock = json.loads(
        (project / ".harness/harness.lock.json").read_text(encoding="utf-8")
    )
    assert lock["release"] == "0.9.0", lock
    assert lock["source"]["ref"] == TARGET, lock
    assert lock["source"]["commit"] == target_oid, lock
    assert (
        project / ".harness/local/upgrade-audit.txt"
    ).read_text(encoding="utf-8") == "keep-local-state\n"

    reloaded = dispatch(project, f"HARNESS UPDATE APPLY TO {TARGET}", env)
    assert reloaded["_exitCode"] == 0, reloaded
    assert reloaded["status"] == "DONE", reloaded
    second = reloaded["result"]
    assert second["status"] == "SUCCESS", reloaded
    assert second["engineStatus"] == "NO_UPDATE", reloaded
    assert second["repositoryMutated"] is True, reloaded
    assert "planning/reviews/TEMPLATE.md" in second["projectTemplateAlignment"]["changed"], reloaded
    assert second["nextAction"] == {
        "kind": "command",
        "command": "GIT CHECK",
    }, reloaded

    stable = dispatch(project, f"HARNESS UPDATE APPLY TO {TARGET}", env)
    assert stable["_exitCode"] == 0, stable
    assert stable["status"] == "DONE", stable
    third = stable["result"]
    assert third["status"] == "SUCCESS", stable
    assert third["engineStatus"] == "NO_UPDATE", stable
    assert third["repositoryMutated"] is False, stable
    assert third["projectTemplateAlignment"]["changed"] == [], stable
    assert third["nextAction"] is None, stable

    state = json.loads(
        (
            project
            / ".harness/local/execution/execution-status.json"
        ).read_text(encoding="utf-8")
    )
    assert state["schemaVersion"] == 2, state

    validation = run(
        project,
        "python3",
        ".harness/tools/validate.py",
        "--mode",
        "manual",
        check=False,
        env=env,
    )
    assert validation.returncode == 0, (
        validation.stdout,
        validation.stderr,
    )


def assert_custom_template_not_overwritten_after_reload(
    project: Path,
    env: dict[str, str],
    *,
    target_oid: str,
) -> None:
    first = dispatch(
        project,
        f"HARNESS UPDATE CHECK TO {TARGET} > APPLY",
        env,
    )
    assert first["_exitCode"] == 0, first
    assert first["status"] == "DONE", first
    result = first["result"]
    assert result["engineStatus"] == "UPDATER_RELOAD_REQUIRED", first

    template = project / "planning/reviews/TEMPLATE.md"
    original_target = template.read_text(encoding="utf-8")
    custom = (
        original_target.rstrip()
        + "\n\nПользовательская pre-init заметка, которую updater не имеет права затирать.\n"
    )
    assert custom != original_target
    template.write_text(custom, encoding="utf-8", newline="\n")
    custom_bytes = template.read_bytes()

    blocked = dispatch(project, f"HARNESS UPDATE APPLY TO {TARGET}", env)
    assert blocked["_exitCode"] != 0 or blocked["status"] == "BLOCKED", blocked
    assert template.read_bytes() == custom_bytes, (
        "reload alignment overwrote user-modified project template",
        blocked,
    )

    lock = json.loads(
        (project / ".harness/harness.lock.json").read_text(encoding="utf-8")
    )
    assert lock["release"] == "0.9.0", lock
    assert lock["source"]["ref"] == TARGET, lock
    assert lock["source"]["commit"] == target_oid, lock
    assert (
        project / ".harness/local/upgrade-audit.txt"
    ).read_text(encoding="utf-8") == "keep-local-state\n"


def scenario(
    tmp: Path,
    source: Path,
    *,
    base_oid: str,
    target_oid: str,
    pin_source_commit: bool,
) -> None:
    name = "pinned" if pin_source_commit else "release-snapshot"
    project = project_from_release(
        tmp / f"project-{name}",
        source,
        base_oid=base_oid,
        pin_source_commit=pin_source_commit,
    )
    env = rewrite_env(source)
    assert_check_is_read_only(project, env)
    assert_apply_and_reload(project, env, target_oid=target_oid)


def main() -> int:
    with tempfile.TemporaryDirectory(prefix="harness-real-release-upgrade-") as raw:
        tmp = Path(raw)
        source, base_oid, target_oid = prepare_source(tmp)
        scenario(
            tmp,
            source,
            base_oid=base_oid,
            target_oid=target_oid,
            pin_source_commit=False,
        )
        scenario(
            tmp,
            source,
            base_oid=base_oid,
            target_oid=target_oid,
            pin_source_commit=True,
        )

        negative_project = project_from_release(
            tmp / "project-custom-template-drift",
            source,
            base_oid=base_oid,
            pin_source_commit=False,
        )
        assert_custom_template_not_overwritten_after_reload(
            negative_project,
            rewrite_env(source),
            target_oid=target_oid,
        )
    print("REAL v0.8.0 -> synthetic v0.9.0 UPDATE AUDIT: PASS")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
