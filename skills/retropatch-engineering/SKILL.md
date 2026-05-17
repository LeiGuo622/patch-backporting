---
name: retropatch-engineering
description: Project-specific engineering guide for the RetroPatch repository. Use when Codex needs to understand, modify, debug, validate, or document RetroPatch's automated patch-backporting flow or kernel prejudge flow; when touching files under src/, test/, README*.md, pyproject.toml, requirements.txt, or src/example.yml; or when a task depends on this repo's git-based patch application, LLM prompts, config schema, OpenAI/Azure wiring, OpenRouter-based prejudge, or external build.sh/test.sh/poc.sh dataset hooks.
---

# Retropatch Engineering

## Overview

Treat this repository as two linked but separate systems:
- backporting pipeline: `src/backporting.py` + `src/agent/` + `src/tools/`
- prejudge pipeline: `src/prejudge/`

Prefer current code over README text. Some docs and helper scripts are stale.

## Route The Task

1. Classify the request before editing.
   - Change hunk application, patch validation, prompts, or `Project` behavior: read `references/repo-map.md` and `references/runtime-and-validation.md`.
   - Change kernel prejudge logic, CONFIG/arch/fix-commit checks, or LLM necessity judgment: read `references/prejudge-pipeline.md`.
   - Change docs or tests: read `references/known-quirks.md` first so you do not preserve existing drift.
2. Run `python3 skills/retropatch-engineering/scripts/check_setup.py` before claiming the repo is runnable.
   - Add `--config path/to/config.yml` when the task uses a real backport config.
3. Validate narrowly first.
   - Start with import or syntax checks.
   - Run end-to-end flows only when required and only after reviewing mutation risks.

## Follow Working Rules

- Preserve the repo's non-packaged import style unless the task explicitly asks for packaging changes.
- Keep backporting and prejudge edits isolated unless the task clearly spans both.
- Assume end-to-end backporting mutates and cleans the external target repo pointed to by `project_dir`; inspect `Project._checkout()`, `Project._apply_hunk()`, and `main()` before running it.
- Fix documentation drift against current code instead of copying existing README commands.
- Update prompt files and the code that binds them together in the same change when tool semantics or model behavior changes.

## Use Change Playbooks

### Backporting Flow

- Start from `src/backporting.py`, then `src/agent/invoke_llm.py`, then `src/tools/project.py`.
- Inspect `src/tools/utils.py` when behavior depends on patch splitting, line matching, or context repair.
- Treat `load_yml()` as the config contract for required fields and path normalization.

### Prejudge Flow

- Start from `src/prejudge/prejudge.py`.
- Move next to the specific judge module you need: `judge_fix.py`, `judge_arch.py`, `judge_config.py`, `judge_llm.py`, or `judge_agent.py`.
- Inspect `judge_tools.py` and `judge_prompt.py` when the LLM agent's search behavior or output contract matters.

### Config Or Environment Debugging

- Run `python3 skills/retropatch-engineering/scripts/check_setup.py --config path/to/config.yml`.
- Verify directories, commit IDs, and shell hooks before blaming LLM behavior.
- Distinguish the two model stacks:
  - backporting: YAML-driven OpenAI or Azure OpenAI
  - prejudge: `OPENROUTER_API_KEY` + OpenRouter-compatible endpoint in `judge_agent.py`

### Documentation Or Test Cleanup

- Reconcile examples with real entrypoints and constructor signatures.
- Treat `references/known-quirks.md` as the checklist before deleting or rewriting tests.

## References

- `references/repo-map.md`: code map, responsibilities, and call graph.
- `references/runtime-and-validation.md`: dependencies, commands, mutation risks, and validation ladder.
- `references/prejudge-pipeline.md`: prejudge stages, model wiring, and file responsibilities.
- `references/known-quirks.md`: drift and pitfalls to check before editing.
