# Prejudge Pipeline

## High-Level Flow

`PrejudgeController.analyze_and_report()` in `src/prejudge/prejudge.py` currently runs these stages in order:

1. `judge_fix(commit_id)`
2. retrieve patch text from the source repo
3. `judge_config(patch_content)`
4. check whether at least one inferred `CONFIG_*` is enabled in supported arch config snapshots
5. `judge_arch(commit_id)`
6. `judge_agent_llm(commit_id)`
7. print a short textual verdict

Preserve the stage order unless there is a clear reason to change the decision policy.

## Output Contract

The controller prints compact result strings such as:

- `true`
- `false, fix commits missing`
- `false, arch not supported`
- `false, vulnerable code not found`

Assume downstream tooling may depend on these strings. Change them deliberately.

## Judge Modules

### `judge_fix.py`

- read the upstream commit message
- extract fix-tag style commit IDs
- verify whether those commits exist in the target repo
- special-case reachability from `OLK-6.6` for reporting

### `judge_arch.py`

- inspect modified file paths from `git show --name-only`
- reject unsupported `arch/<name>/...` changes
- support `arm`, `arm64`, `x86`, `riscv`, `loongarch`, `powerpc`, and `sw_64`

### `judge_config.py`

- parse added patch lines per file
- infer `CONFIG_*` dependencies from Makefiles and preprocessor conditions
- return config symbols used later by `check_config_in_arch_configs()`

This file is the densest logic in `src/prejudge/`. Edit it surgically.

### `judge_llm.py`

- validate paths
- construct `JudgeAgent`
- run the agent-backed necessity judgment
- return `True` on errors as a conservative fallback

### `judge_agent.py`

- define supported model providers and shared constructor settings
- build the tool-calling agent
- fetch patch text from the source repo
- parse the model's final answer into a boolean

## LLM Tooling

The prejudge agent only uses:

- `locate_symbol(symbol)` from `judge_tools.py`
- `view_code(file_path, start_line, end_line)` from `judge_tools.py`

These tools operate on the target project only and default to `ref="HEAD"` in `judge_llm.py`.

## Configuration Reality

Prejudge does not reuse the YAML config from the main backporting flow.

Instead it currently depends on:
- source repo path
- target repo path
- commit ID
- `OPENROUTER_API_KEY` environment variable

When a task asks to unify or simplify configuration, inspect both flows before proposing changes.

## Safe Edit Strategy

- Change one judge at a time.
- Preserve conservative fallbacks unless the user explicitly wants stricter failures.
- Keep prompt wording, tool behavior, and response parsing aligned.
- Re-run the narrowest relevant script after each change.
