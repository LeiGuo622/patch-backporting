#!/usr/bin/env python3
from __future__ import annotations

import argparse
import shutil
import subprocess
import sys
from pathlib import Path

try:
    import yaml
except ImportError:
    yaml = None


REQUIRED_REPO_FILES = [
    "pyproject.toml",
    "requirements.txt",
    "src/backporting.py",
    "src/tools/project.py",
    "src/prejudge/prejudge.py",
]
REQUIRED_CONFIG_FIELDS = [
    "project",
    "project_url",
    "project_dir",
    "patch_dataset_dir",
    "new_patch",
    "new_patch_parent",
    "target_release",
]
OPTIONAL_HOOKS = ["build.sh", "test.sh", "poc.sh"]


def print_status(level: str, label: str, detail: str) -> None:
    print(f"{level:<4} {label}: {detail}")


def run_git(args: list[str], cwd: Path) -> bool:
    result = subprocess.run(
        ["git", *args],
        cwd=cwd,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        text=True,
    )
    return result.returncode == 0


def check_repo_root(repo_root: Path) -> int:
    failures = 0
    print(f"Repo root: {repo_root}")

    if sys.version_info >= (3, 10):
        print_status("OK", "python", f"{sys.version.split()[0]}")
    else:
        print_status("FAIL", "python", f"{sys.version.split()[0]} < 3.10")
        failures += 1

    if shutil.which("git"):
        print_status("OK", "git", "available")
    else:
        print_status("FAIL", "git", "not found in PATH")
        failures += 1

    if shutil.which("ctags"):
        print_status("OK", "ctags", "available")
    else:
        print_status("WARN", "ctags", "missing; backporting symbol lookup will not work")

    for relative_path in REQUIRED_REPO_FILES:
        path = repo_root / relative_path
        if path.exists():
            print_status("OK", relative_path, "present")
        else:
            print_status("FAIL", relative_path, "missing")
            failures += 1

    if run_git(["rev-parse", "--is-inside-work-tree"], repo_root):
        print_status("OK", "repo git", "current directory is a git work tree")
    else:
        print_status("FAIL", "repo git", "current directory is not a git work tree")
        failures += 1

    return failures


def load_config(config_path: Path) -> dict:
    text = config_path.read_text(encoding="utf-8")
    if yaml is not None:
        data = yaml.safe_load(text) or {}
    else:
        data = {}
        for raw_line in text.splitlines():
            stripped = raw_line.strip()
            if not stripped or stripped.startswith("#") or ":" not in raw_line:
                continue
            key, value = raw_line.split(":", 1)
            key = key.strip()
            value = value.strip()
            if value[:1] in {"'", '"'} and value[-1:] == value[:1]:
                value = value[1:-1]
            elif value.lower() == "true":
                value = True
            elif value.lower() == "false":
                value = False
            data[key] = value
    if not isinstance(data, dict):
        raise ValueError("config root must be a mapping")
    return data


def check_commit(repo_dir: Path, commit: str) -> bool:
    return run_git(["rev-parse", "--verify", f"{commit}^{{commit}}"], repo_dir)


def check_config(config_path: Path) -> int:
    failures = 0
    warnings = 0

    print(f"\nConfig: {config_path}")
    if not config_path.exists():
        print_status("FAIL", "config file", "not found")
        return 1

    try:
        data = load_config(config_path)
        print_status("OK", "config parse", "loaded")
    except Exception as exc:
        print_status("FAIL", "config parse", str(exc))
        return 1

    for field in REQUIRED_CONFIG_FIELDS:
        value = data.get(field)
        if value:
            print_status("OK", field, str(value))
        else:
            print_status("FAIL", field, "missing or empty")
            failures += 1

    openai_key = data.get("openai_key", "")
    if openai_key:
        print_status("OK", "openai_key", "present")
    else:
        print_status("WARN", "openai_key", "empty; main backporting flow will not authenticate")
        warnings += 1

    use_azure = bool(data.get("use_azure", False))
    print_status("OK", "use_azure", str(use_azure).lower())
    if use_azure:
        for field in ["azure_endpoint", "azure_deployment", "azure_api_version"]:
            value = data.get(field)
            if value:
                print_status("OK", field, str(value))
            else:
                print_status("WARN", field, "missing while use_azure=true")
                warnings += 1

    for field in ["project_dir", "patch_dataset_dir"]:
        raw_value = data.get(field)
        if not raw_value:
            continue
        resolved = Path(raw_value).expanduser().resolve()
        if resolved.exists():
            print_status("OK", f"{field} resolved", str(resolved))
        else:
            print_status("FAIL", f"{field} resolved", f"{resolved} does not exist")
            failures += 1

        if field == "project_dir" and resolved.exists():
            if run_git(["rev-parse", "--is-inside-work-tree"], resolved):
                print_status("OK", "project_dir git", "target directory is a git work tree")
            else:
                print_status("FAIL", "project_dir git", "target directory is not a git work tree")
                failures += 1

            for hook in OPTIONAL_HOOKS:
                hook_path = resolved / hook
                if hook_path.exists():
                    print_status("OK", hook, f"present in {resolved}")
                else:
                    print_status("WARN", hook, f"absent in {resolved}; this stage will be treated as passed")
                    warnings += 1

            for field_name in ["new_patch", "new_patch_parent", "target_release"]:
                commit = data.get(field_name)
                if commit:
                    if check_commit(resolved, str(commit)):
                        print_status("OK", f"{field_name} resolve", "valid commit-ish")
                    else:
                        print_status("FAIL", f"{field_name} resolve", "invalid in project_dir")
                        failures += 1

    if data.get("OPENROUTER_API_KEY"):
        print_status("WARN", "OPENROUTER_API_KEY", "found in config but prejudge reads this from environment, not YAML")
        warnings += 1

    if failures == 0:
        print_status("OK", "config summary", f"{warnings} warning(s)")
    else:
        print_status("FAIL", "config summary", f"{failures} failure(s), {warnings} warning(s)")

    return failures


def main() -> int:
    parser = argparse.ArgumentParser(description="Check local RetroPatch setup.")
    parser.add_argument("--config", type=Path, help="Optional path to a real backport config YAML.")
    args = parser.parse_args()

    repo_root = Path(__file__).resolve().parents[3]
    failures = check_repo_root(repo_root)

    openrouter_api_key = None
    try:
        import os

        openrouter_api_key = os.getenv("OPENROUTER_API_KEY")
    except Exception:
        openrouter_api_key = None

    if openrouter_api_key:
        print_status("OK", "OPENROUTER_API_KEY", "present in environment")
    else:
        print_status("WARN", "OPENROUTER_API_KEY", "missing; prejudge LLM path will not authenticate")

    if args.config:
        failures += check_config(args.config.expanduser().resolve())

    if failures == 0:
        print("\nResult: setup check passed.")
        return 0

    print("\nResult: setup check failed.")
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
