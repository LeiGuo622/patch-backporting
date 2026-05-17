# Runtime And Validation

## Prerequisites

- Use Python `>=3.10`.
- Install repo dependencies from `requirements.txt` or via the configured package manager.
- Have `git` available.
- Prefer having `ctags` available for the backporting `locate_symbol` flow.
- Expect end-to-end backporting to depend on external repositories and dataset directories referenced by the config file.

## Practical Commands

- Validate local structure:
  - `python3 skills/retropatch-engineering/scripts/check_setup.py`
- Validate a real backport config:
  - `python3 skills/retropatch-engineering/scripts/check_setup.py --config path/to/config.yml`
- Run the main backporting flow from repo root:
  - `python3 src/backporting.py --config path/to/config.yml`
- Run the prejudge CLI:
  - `python3 src/prejudge/prejudge.py <commit-id> <kernel-source-dir> <target-project-dir>`
- Run the batch prejudge helper:
  - `python3 test/test_prejudge.py <input.csv> <output.csv> <kernel-dir> <target-project-dir>`
- Run a syntax pass after targeted edits:
  - `python3 -m py_compile src/backporting.py src/tools/project.py`
  - widen the file list only as needed

## Validation Ladder

Use the narrowest useful validation first:

1. import or syntax validation
2. direct helper script validation
3. targeted module run
4. full backporting or prejudge workflow

Use end-to-end runs only when the task actually depends on the external repo, build hooks, or LLM interaction.

## Mutation Risks

Review these behaviors before running end-to-end backporting:

- `src/backporting.py` calls `project.repo.git.clean("-fdx")`.
- `Project._checkout()` uses `git reset --hard` and `git checkout`.
- `Project._apply_hunk()` and `_compile_patch()` repeatedly apply and reset patches inside `project_dir`.
- `do_backport()` copies files from `patch_dataset_dir` into `project_dir` before full validation.
- `src/backporting.py` copies the generated log file back into `patch_dataset_dir`.

Do not run these flows against a repo with uncommitted work unless the user explicitly accepts that risk.

## External Hook Discovery

Inside the target repo referenced by `project_dir`:

- `build.sh`: if present, compile during validation
- `test.sh`: if present, run after compile
- `poc.sh`: if present, run after testcase and look for `error_message`

If a hook is absent, the corresponding stage is treated as passed.

## Model Configuration Split

Keep the two LLM configurations separate:

- Backporting flow:
  - configured from YAML in `load_yml()`
  - regular OpenAI path uses `ChatOpenAI`
  - Azure path uses `AzureChatOpenAI`
- Prejudge flow:
  - configured from environment in `judge_agent.py`
  - currently expects `OPENROUTER_API_KEY`
  - `judge_llm.py` currently instantiates `JudgeAgent(..., model_provider="deepseek", ref="HEAD")`

When debugging auth or model selection, determine which stack is active before editing code.

## CI Reality

Current GitHub Actions only runs `pylint` on `src/` via `.github/workflows/pylint.yml`.

Do not assume there is full automated coverage for:
- `test/`
- end-to-end backporting
- prejudge flows
- external dataset integration
