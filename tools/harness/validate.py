#!/usr/bin/env python3
"""Dependency-free integrity/safety validator for AI Development Harness."""
from __future__ import annotations

import argparse
import fnmatch
import json
import os
from pathlib import Path
import re
import subprocess
import sys

if sys.version_info < (3, 11):
    print("ERROR: Harness validation requires Python 3.11+ (stdlib tomllib).", file=sys.stderr)
    raise SystemExit(2)

import tomllib


def run_git(root: Path, *args: str) -> tuple[int, str]:
    try:
        proc = subprocess.run(["git", *args], cwd=root, text=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
    except OSError:
        return 127, ""
    return proc.returncode, proc.stdout


def repo_root() -> Path:
    here = Path(__file__).resolve()
    code, out = run_git(here.parent, "rev-parse", "--show-toplevel")
    if code == 0 and out.strip():
        return Path(out.strip())
    return here.parents[2]


def load_toml(path: Path) -> dict:
    with path.open("rb") as fh:
        return tomllib.load(fh)


def tracked_files(root: Path) -> tuple[list[str], str | None]:
    code, out = run_git(root, "ls-files", "-z")
    if code != 0:
        return [], "Git index unavailable; tracked-file integrity checks require a Git working tree"
    return [p for p in out.split("\0") if p], None


def match_any(path: str, patterns: list[str]) -> bool:
    return any(fnmatch.fnmatch(path, pat) for pat in patterns)


def is_under(path: str, configured: list[str]) -> bool:
    p = path.replace("\\", "/")
    for item in configured:
        item = item.rstrip("/")
        if p == item or p.startswith(item + "/"):
            return True
    return False


def text_file(path: Path) -> bool:
    try:
        data = path.read_bytes()
    except OSError:
        return False
    if b"\0" in data[:8192]:
        return False
    return True


def parse_markdown_frontmatter(path: Path) -> dict[str, str]:
    """Parse the simple top-level scalar subset used by Harness skill/agent frontmatter."""
    try:
        text = path.read_text(encoding="utf-8")
    except Exception:
        return {}
    if not text.startswith("---\n"):
        return {}
    end = text.find("\n---\n", 4)
    if end < 0:
        return {}
    result: dict[str, str] = {}
    for line in text[4:end].splitlines():
        if not line or line[0].isspace() or ":" not in line:
            continue
        key, value = line.split(":", 1)
        value = value.strip().strip('"').strip("'")
        if value:
            result[key.strip()] = value
    return result


def parse_skill_frontmatter(path: Path) -> tuple[str | None, str | None]:
    fields = parse_markdown_frontmatter(path)
    return fields.get("name"), fields.get("description")


def preceding_comment_block(lines: list[str], index: int) -> list[str]:
    """Return contiguous comment lines immediately preceding a config parameter."""
    comments: list[str] = []
    i = index - 1
    while i >= 0:
        stripped = lines[i].strip()
        if not stripped:
            if comments:
                break
            i -= 1
            continue
        if stripped.startswith("#"):
            comments.append(stripped[1:].strip())
            i -= 1
            continue
        break
    comments.reverse()
    return comments


def config_parameter_lines(path: Path) -> list[tuple[int, str]]:
    """Find YAML/TOML parameter lines while skipping tables, list items and multiline TOML bodies."""
    lines = path.read_text(encoding="utf-8").splitlines()
    result: list[tuple[int, str]] = []
    in_toml_multiline = False
    suffix = path.suffix.lower()
    for idx, line in enumerate(lines):
        stripped = line.strip()
        if not stripped or stripped.startswith("#"):
            continue
        if suffix == ".toml":
            if in_toml_multiline:
                if '"""' in stripped:
                    in_toml_multiline = False
                continue
            if stripped.startswith("["):
                continue
            m = re.match(r"^([A-Za-z0-9_.-]+)\s*=", stripped)
            if m:
                result.append((idx, m.group(1)))
                if stripped.count('"""') == 1:
                    in_toml_multiline = True
            continue
        if suffix in {".yaml", ".yml"}:
            # Mapping key, including list-item mappings such as `- name:`.
            m = re.match(r"^\s*(?:-\s+)?([A-Za-z0-9_.-]+):(?:\s|$)", line)
            if m:
                result.append((idx, m.group(1)))
    return result


SEMVER_TAG_RE = re.compile(r"^v(\d+)\.(\d+)\.(\d+)$")


def semver_tag_tuple(tag: str) -> tuple[int, int, int] | None:
    match = SEMVER_TAG_RE.fullmatch(tag)
    if not match:
        return None
    return tuple(int(part) for part in match.groups())


def validate_update_graph(root: Path, errors: list[str]) -> None:
    path = root / ".project" / "harness-update-graph.json"
    if not path.is_file():
        return
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except Exception as exc:
        errors.append(f"invalid .project/harness-update-graph.json: {exc}")
        return

    if not isinstance(data, dict):
        errors.append(".project/harness-update-graph.json root must be an object")
        return
    if data.get("schemaVersion") != 1:
        errors.append(".project/harness-update-graph.json schemaVersion must be 1")

    latest = data.get("latest")
    if not isinstance(latest, str) or semver_tag_tuple(latest) is None:
        errors.append(".project/harness-update-graph.json latest must be vMAJOR.MINOR.PATCH")
        latest = None

    transitions = data.get("transitions")
    if not isinstance(transitions, list):
        errors.append(".project/harness-update-graph.json transitions must be an array")
        return

    outgoing: dict[str, str] = {}
    nodes: set[str] = set()
    if latest:
        nodes.add(latest)

    for index, transition in enumerate(transitions):
        prefix = f".project/harness-update-graph.json transitions[{index}]"
        if not isinstance(transition, dict):
            errors.append(f"{prefix} must be an object")
            continue

        source = transition.get("from")
        target = transition.get("to")
        source_v = semver_tag_tuple(source) if isinstance(source, str) else None
        target_v = semver_tag_tuple(target) if isinstance(target, str) else None

        if source_v is None:
            errors.append(f"{prefix}.from must be vMAJOR.MINOR.PATCH")
        if target_v is None:
            errors.append(f"{prefix}.to must be vMAJOR.MINOR.PATCH")
        if source_v is not None and target_v is not None and target_v <= source_v:
            errors.append(f"{prefix} must move strictly forward")
        if transition.get("kind") not in {"standard", "bridge"}:
            errors.append(f"{prefix}.kind must be standard or bridge")
        if not isinstance(transition.get("reloadRequired"), bool):
            errors.append(f"{prefix}.reloadRequired must be boolean")
        if transition.get("kind") == "bridge":
            reason = transition.get("reason")
            if not isinstance(reason, str) or not reason.strip():
                errors.append(f"{prefix}.reason is required for bridge")

        if isinstance(source, str) and isinstance(target, str):
            if source in outgoing:
                errors.append(f".project/harness-update-graph.json ambiguous route: multiple transitions from {source}")
            else:
                outgoing[source] = target
            nodes.update({source, target})

    if latest and latest in outgoing:
        errors.append(".project/harness-update-graph.json latest must be terminal (no outgoing transition)")

    if latest:
        for start in sorted(nodes):
            current = start
            seen: set[str] = set()
            while current != latest:
                if current in seen:
                    errors.append(f".project/harness-update-graph.json cycle detected from {start}")
                    break
                seen.add(current)
                nxt = outgoing.get(current)
                if nxt is None:
                    errors.append(f".project/harness-update-graph.json release {start} cannot reach latest {latest}")
                    break
                current = nxt

        manifest_path = root / ".project" / "manifest.yaml"
        if manifest_path.is_file():
            try:
                manifest_text = manifest_path.read_text(encoding="utf-8")
                manifest_release = None
                for line in manifest_text.splitlines():
                    if line.startswith("  release:"):
                        manifest_release = line.split(":", 1)[1].split("#", 1)[0].strip().strip("\"'")
                        break
                if manifest_release and latest != f"v{manifest_release}":
                    errors.append(
                        f".project/harness-update-graph.json latest {latest} does not match manifest harness.release v{manifest_release}"
                    )
            except UnicodeDecodeError:
                pass


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--mode", choices=["ci", "commit", "manual"], default="manual")
    args = parser.parse_args()

    root = repo_root()
    policy_path = root / ".project" / "harness-policy.toml"
    errors: list[str] = []
    warnings: list[str] = []

    if not policy_path.exists():
        print("ERROR: missing .project/harness-policy.toml", file=sys.stderr)
        return 2

    try:
        policy = load_toml(policy_path)
    except Exception as exc:
        print(f"ERROR: invalid harness policy TOML: {exc}", file=sys.stderr)
        return 2

    validate_update_graph(root, errors)

    # Core files.
    for rel in policy.get("required_files", []):
        if not (root / rel).is_file():
            errors.append(f"required file missing: {rel}")

    # Required skills + minimal frontmatter.
    seen_skill_names: dict[str, str] = {}
    for skill in policy.get("required_skills", []):
        p = root / ".agents" / "skills" / skill / "SKILL.md"
        if not p.is_file():
            errors.append(f"required skill missing: {skill}")
    skills_root = root / ".agents" / "skills"
    if skills_root.exists():
        for p in sorted(skills_root.glob("*/SKILL.md")):
            name, desc = parse_skill_frontmatter(p)
            rel = str(p.relative_to(root))
            if not name:
                errors.append(f"skill frontmatter missing name: {rel}")
            elif name in seen_skill_names:
                errors.append(f"duplicate skill name '{name}': {seen_skill_names[name]} and {rel}")
            else:
                seen_skill_names[name] = rel
            if not desc:
                errors.append(f"skill frontmatter missing description: {rel}")

    # TOML syntax and runtime agent bindings.
    for p in root.rglob("*.toml"):
        if ".git" in p.parts:
            continue
        try:
            load_toml(p)
        except Exception as exc:
            errors.append(f"invalid TOML {p.relative_to(root)}: {exc}")

    required_agents = policy.get("required_agents", [])

    codex_cfg_path = root / ".codex" / "config.toml"
    if codex_cfg_path.exists():
        try:
            codex_cfg = load_toml(codex_cfg_path)
            agents = codex_cfg.get("agents", {})
            for agent in required_agents:
                entry = agents.get(agent)
                if not isinstance(entry, dict):
                    errors.append(f"required Codex agent binding missing: {agent}")
                    continue
                config_file = entry.get("config_file")
                if not config_file:
                    errors.append(f"Codex agent {agent} missing config_file")
                    continue
                resolved = (root / ".codex" / config_file).resolve()
                if not resolved.is_file():
                    errors.append(f"Codex agent {agent} config missing: {config_file}")
        except Exception:
            pass

    claude_settings_path = root / ".claude" / "settings.json"
    if claude_settings_path.exists():
        try:
            claude_settings = json.loads(claude_settings_path.read_text(encoding="utf-8"))
            if not isinstance(claude_settings.get("model"), str) or not claude_settings["model"].strip():
                errors.append("Claude settings missing non-empty model")
            effort = claude_settings.get("effortLevel")
            if effort not in {"low", "medium", "high", "xhigh", "max"}:
                errors.append("Claude settings effortLevel must be low/medium/high/xhigh/max")
            permissions = claude_settings.get("permissions", {})
            if permissions and permissions.get("defaultMode") not in {
                "default", "acceptEdits", "auto", "dontAsk", "bypassPermissions", "plan"
            }:
                errors.append("Claude settings permissions.defaultMode is invalid")
        except Exception as exc:
            errors.append(f"invalid Claude settings JSON: {exc}")

    claude_agents_root = root / ".claude" / "agents"
    seen_claude_names: dict[str, str] = {}
    if claude_agents_root.exists():
        for p in sorted(claude_agents_root.glob("*.md")):
            fields = parse_markdown_frontmatter(p)
            rel = str(p.relative_to(root))
            name = fields.get("name")
            if not name:
                errors.append(f"Claude agent frontmatter missing name: {rel}")
                continue
            if name in seen_claude_names:
                errors.append(f"duplicate Claude agent name '{name}': {seen_claude_names[name]} and {rel}")
            else:
                seen_claude_names[name] = rel
            if not fields.get("description"):
                errors.append(f"Claude agent frontmatter missing description: {rel}")
            if not fields.get("model"):
                errors.append(f"Claude agent frontmatter missing model: {rel}")
            if fields.get("effort") not in {"low", "medium", "high", "xhigh", "max"}:
                errors.append(f"Claude agent invalid effort: {rel}")
            permission_mode = fields.get("permissionMode")
            if permission_mode not in {"default", "manual", "acceptEdits", "auto", "dontAsk", "bypassPermissions", "plan"}:
                errors.append(f"Claude agent invalid permissionMode: {rel}")

    for agent in required_agents:
        claude_name = agent.replace("_", "-")
        p = claude_agents_root / f"{claude_name}.md"
        if not p.is_file():
            errors.append(f"required Claude agent missing: {claude_name}")
            continue
        fields = parse_markdown_frontmatter(p)
        if fields.get("name") != claude_name:
            errors.append(f"Claude agent name mismatch: {p.relative_to(root)}")

    claude_md = root / "CLAUDE.md"
    if claude_md.exists():
        try:
            if "@AGENTS.md" not in claude_md.read_text(encoding="utf-8"):
                errors.append("CLAUDE.md must import @AGENTS.md")
        except UnicodeDecodeError:
            errors.append("CLAUDE.md is not UTF-8")

    # Required command surface in all canonical routing docs.
    command_files = [root / "AGENTS.md", root / "docs/harness/COMMANDS.md", root / "planning/EXECUTION_PROTOCOL.md"]
    for command in policy.get("required_commands", []):
        for p in command_files:
            if p.exists() and command not in p.read_text(encoding="utf-8"):
                errors.append(f"command '{command}' missing from {p.relative_to(root)}")

    # Generated markers + ignore rule.
    agents_text = (root / "AGENTS.md").read_text(encoding="utf-8") if (root / "AGENTS.md").exists() else ""
    for start, end in [
        ("<!-- PROJECT-CONTEXT:START -->", "<!-- PROJECT-CONTEXT:END -->"),
        ("<!-- SKILL-ROUTING:START -->", "<!-- SKILL-ROUTING:END -->"),
    ]:
        if start not in agents_text or end not in agents_text or agents_text.index(start) > agents_text.index(end):
            errors.append(f"AGENTS generated markers invalid: {start} / {end}")

    gitignore = (root / ".gitignore").read_text(encoding="utf-8") if (root / ".gitignore").exists() else ""
    for ignored in [
        "PROJECT_BRIEF.local.md",
        "AGENTS.local.md",
        "CLAUDE.local.md",
        ".claude/settings.local.json",
    ]:
        if ignored not in gitignore:
            errors.append(f".gitignore must ignore {ignored}")

    files, git_blocker = tracked_files(root)
    if git_blocker:
        print("HARNESS VALIDATION: BLOCKED")
        print(f"  - {git_blocker}")
        return 2

    forbidden = policy.get("forbidden_tracked_globs", [])
    allowed = policy.get("allowed_tracked_globs", [])
    max_size = int(policy.get("max_tracked_file_size_mb", 10)) * 1024 * 1024

    for rel in files:
        normalized = rel.replace("\\", "/")
        if match_any(normalized, forbidden) and not match_any(normalized, allowed):
            errors.append(f"forbidden tracked file: {normalized}")
        p = root / rel
        try:
            if p.is_file() and p.stat().st_size > max_size:
                errors.append(f"tracked file exceeds {max_size // (1024*1024)} MiB: {normalized}")
        except OSError:
            pass

    # Private key material + merge markers in tracked text.
    private_markers = [b"-----BEGIN" + suffix for suffix in (b" PRIVATE KEY-----", b" RSA PRIVATE KEY-----", b" OPENSSH PRIVATE KEY-----")]
    format_paths = policy.get("format_paths", [])
    for rel in files:
        p = root / rel
        if not p.is_file() or not text_file(p):
            continue
        try:
            raw = p.read_bytes()
        except OSError:
            continue
        if any(marker in raw for marker in private_markers):
            errors.append(f"private key material detected in tracked file: {rel}")
        if policy.get("check_merge_markers", True):
            text = raw.decode("utf-8", errors="ignore")
            if re.search(r"(?m)^(<<<<<<<|=======|>>>>>>>)", text):
                errors.append(f"merge-conflict marker detected: {rel}")
        if is_under(rel, format_paths):
            if policy.get("check_utf8", True):
                try:
                    text = raw.decode("utf-8")
                except UnicodeDecodeError:
                    errors.append(f"managed text is not UTF-8: {rel}")
                    continue
            else:
                text = raw.decode("utf-8", errors="replace")
            if policy.get("check_final_newline", True) and raw and not raw.endswith(b"\n"):
                errors.append(f"missing final newline: {rel}")
            if policy.get("check_trailing_whitespace", True):
                for n, line in enumerate(text.splitlines(), 1):
                    if line.rstrip(" \t") != line:
                        errors.append(f"trailing whitespace: {rel}:{n}")
                        break

    # Self-documented YAML/TOML configs.
    if policy.get("check_config_parameter_comments", True):
        config_patterns = policy.get("documented_config_globs", [])
        require_example = policy.get("check_config_parameter_examples", True)
        for candidate in sorted(root.rglob("*")):
            if not candidate.is_file() or candidate.suffix.lower() not in {".toml", ".yaml", ".yml"}:
                continue
            rel = str(candidate.relative_to(root)).replace("\\", "/")
            if not match_any(rel, config_patterns):
                continue
            try:
                lines = candidate.read_text(encoding="utf-8").splitlines()
            except UnicodeDecodeError:
                errors.append(f"documented config is not UTF-8: {rel}")
                continue
            for idx, key in config_parameter_lines(candidate):
                comments = preceding_comment_block(lines, idx)
                if not comments:
                    errors.append(f"config parameter lacks comment: {rel}:{idx + 1} ({key})")
                    continue
                if require_example and not any(("Пример:" in item or "Example:" in item) for item in comments):
                    errors.append(f"config parameter comment lacks example: {rel}:{idx + 1} ({key})")

    # Central language policy must remain present in the project manifest.
    manifest_path = root / ".project" / "manifest.yaml"
    if manifest_path.exists():
        try:
            manifest_text = manifest_path.read_text(encoding="utf-8")
            required_language_keys = [
                "default", "agentResponses", "documentation", "commitMessages",
                "codeComments", "testNames", "fixtures", "githubTemplates", "releaseNotes",
            ]
            if not re.search(r"(?m)^language:\s*$", manifest_text):
                errors.append("manifest language policy missing: language")
            for key in required_language_keys:
                if not re.search(rf"(?m)^  {re.escape(key)}:\s*[^#\s]+", manifest_text):
                    errors.append(f"manifest language policy missing value: language.{key}")
        except UnicodeDecodeError:
            errors.append(".project/manifest.yaml is not UTF-8")

    # Git policy semantics.
    git_policy_path = root / ".project" / "git-policy.toml"
    if git_policy_path.exists():
        try:
            gp = load_toml(git_policy_path)
            if gp.get("commit", {}).get("stage_mode") not in {"all-safe", "tracked-only", "staged-only"}:
                errors.append("git-policy: invalid commit.stage_mode")
            if gp.get("branch", {}).get("when_on_protected") not in {"auto-create", "stay", "block"}:
                errors.append("git-policy: invalid branch.when_on_protected")
            if gp.get("push", {}).get("force") != "never":
                warnings.append("git-policy: push.force is not 'never'; review this consciously")
            if gp.get("pull_request", {}).get("after_push") not in {"never", "ask", "create-if-missing"}:
                errors.append("git-policy: invalid pull_request.after_push")
            if gp.get("sync", {}).get("mode") not in {"report", "ff-only"}:
                errors.append("git-policy: invalid sync.mode")
        except Exception:
            pass

    # Commit-mode informational staged state.
    if args.mode == "commit":
        code, staged = run_git(root, "diff", "--cached", "--name-only")
        if code == 0 and not staged.strip():
            warnings.append("no staged files yet; COMMIT agent may stage files according to git-policy")

    if warnings:
        print("WARNINGS:")
        for item in warnings:
            print(f"  - {item}")
    if errors:
        print("HARNESS VALIDATION: FAIL")
        for item in errors:
            print(f"  - {item}")
        return 1

    print(f"HARNESS VALIDATION: PASS ({len(files)} tracked files checked, mode={args.mode})")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
