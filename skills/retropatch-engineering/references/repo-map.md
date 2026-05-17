# RetroPatch Repo Map

## Top Level

- `src/backporting.py`: main backporting entrypoint, config loading, logging, project setup, end-to-end orchestration.
- `src/agent/`: backporting LLM prompts and agent construction.
- `src/tools/`: project abstraction, patch application, validation, logger, and patch utilities.
- `src/prejudge/`: kernel prejudge pipeline and judge submodules.
- `test/`: helper scripts for manual or batch validation; not all files here are current.
- `README.md` and `README.zh-CN.md`: user-facing docs, but not always aligned with current entrypoints.

## Backporting Call Graph

1. `src/backporting.py`
   - parse `--config` and `--debug`
   - call `load_yml()`
   - create `Project(data)`
   - call `initial_agent(project, data, debug_mode)`
   - call `do_backport(...)`
2. `src/agent/invoke_llm.py`
   - build the LangChain tool-calling agent
   - expose `viewcode`, `locate_symbol`, `validate`, `git_history`, `git_show`
   - iterate hunk by hunk, then run full validation if all hunks apply
3. `src/tools/project.py`
   - own git checkout/reset/apply/compile/test/poc behavior
   - adapt file moves and context mismatches
   - expose LangChain tools
4. `src/tools/utils.py`
   - split patch text into hunks
   - compute fuzzy line matches
   - revise malformed or context-drifted patch hunks

## Main Runtime Object

`Project` in `src/tools/project.py` stores:
- target repository location and git handle
- commit refs for the new patch parent and target release
- progress flags for hunk application, compile, testcase, and PoC
- transient hunk context used by `git_history()` and `git_show()`

Treat `Project` as the behavioral center of the backporting system. Most runtime mutations happen there.

## Config Contract

`load_yml()` in `src/backporting.py` currently consumes:
- `project`
- `project_url`
- `project_dir`
- `patch_dataset_dir`
- `openai_key`
- `tag`
- `use_azure`
- `azure_endpoint`
- `azure_deployment`
- `azure_api_version`
- `new_patch`
- `new_patch_parent`
- `target_release`
- `error_message`

Required fields are enforced in code for the three commit refs and for existing directories.

## Tool Semantics In Backporting

- `viewcode(ref, path, startline, endline)`: inspect old code directly from git state.
- `locate_symbol(ref, symbol)`: locate a symbol via ctags-generated data.
- `validate(ref, patch)`: apply a hunk or run the compile → testcase → poc ladder for the joined patch.
- `git_history()`: inspect line history for the current hunk.
- `git_show()`: inspect the last commit surfaced by `git_history()`.

If a task changes tool contracts, review both `src/tools/project.py` and `src/agent/prompt.py`.

## Prejudge Structure

`src/prejudge/prejudge.py` owns the top-level orchestration.

Key submodules:
- `judge_fix.py`: extract fix-tag dependencies and check whether they exist in the target repo.
- `judge_arch.py`: reject unsupported `arch/`-specific changes.
- `judge_config.py`: infer `CONFIG_*` requirements from patch lines and Makefile/Kconfig structure.
- `judge_llm.py`: bridge into the LLM-backed necessity check.
- `judge_agent.py`: build the LLM agent and provider selection logic.
- `judge_tools.py`: git-based `locate_symbol` and `view_code` helpers for prejudge.
