# Known Quirks

## Prefer Code Over Docs

- `README.md` and `README.zh-CN.md` still mention `do_on_fix.py`, but the current main entrypoint in this repo is `src/backporting.py`.
- Treat `src/backporting.py`, `src/prejudge/prejudge.py`, and the tests as the source of truth when updating docs.

## Treat Some Test Helpers As Drifted

- `test/test_hunk.py` still constructs `Project` with an old signature and is not aligned with the current `Project(data)` constructor.
- Read helper scripts before assuming they are authoritative examples.

## Respect Destructive Runtime Behavior

- End-to-end backporting resets and cleans the external target repo.
- Validation may copy dataset files into the target repo and overwrite same-named files.
- Avoid running these paths casually during repo-only refactors or docs work.

## Separate The Two Model Stacks

- Backporting uses YAML-selected OpenAI or Azure settings.
- Prejudge uses environment-based OpenRouter-compatible settings.
- Do not “simplify” auth or model code without checking which pipeline you are touching.

## Remember Import Style

- This repo is not packaged as an installable module.
- Several scripts rely on current working directory or manual `sys.path` adjustment.
- Avoid unnecessary import rewrites unless the task explicitly targets packaging or CLI cleanup.

## Treat Short Verdict Strings Carefully

- Prejudge returns terse text like `false, fix commits missing`.
- These strings are easy to break accidentally during cleanup.

## Expect External Data

- A meaningful backport run needs:
  - a real target repo in `project_dir`
  - a dataset directory in `patch_dataset_dir`
  - optional `build.sh`, `test.sh`, and `poc.sh` hooks
- The repo alone is not enough to validate full behavior.

## Remember Lazy Tool Dependencies

- Backporting symbol lookup depends on `ctags`.
- Missing `ctags` does not block every task, but it blocks the full `locate_symbol` workflow.
