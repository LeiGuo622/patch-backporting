[![简体中文](https://img.shields.io/badge/语言-简体中文-red.svg)](README.zh-CN.md)

# RetroPatch

RetroPatch is an LLM-assisted patch backporting toolkit. It takes a fix commit
from a newer upstream revision, analyzes why the patch does not apply cleanly to
an older target revision, and iteratively generates a target-version patch with
tool feedback from Git, symbol lookup, source-code inspection, compilation,
testcases, and PoC validation.

The repository also includes a prejudge pipeline for kernel-oriented workflows.
That pipeline decides whether a candidate upstream fix is worth backporting to a
target tree before running the heavier patch-generation workflow.

## What This Project Does

RetroPatch automates the common backporting loop:

1. Read a known fix commit and split it into patch hunks.
2. Try to apply each hunk directly to the target revision.
3. If a hunk conflicts, use an LLM agent with repository tools to locate the
   corresponding old code and rewrite the hunk.
4. Join all successful hunks into a complete patch.
5. Validate the patch by applying it, building the target project, running
   regression tests, and checking whether the PoC still triggers the bug.
6. Save logs and the final successful patch information for review.

The tool is designed for security and maintenance backports where the target
branch may differ from upstream through moved code, renamed symbols, changed
context, or partially absent logic.

## Repository Layout

```text
src/backporting.py          Main backporting CLI
src/example.yml             Example case configuration
src/agent/                  LLM prompts and agent orchestration
src/tools/                  Git, patch, symbol, validation, and logging helpers
src/prejudge/               Kernel pre-backport judgment pipeline
test/                       Helper scripts for hunk, patch, and prejudge testing
skills/retropatch-engineering/
                            Local Codex skill for repository-specific work
Dockerfile                  Containerized runtime
```

## Requirements

- Python 3.10 or newer
- Git
- Universal Ctags (`ctags`) for symbol indexing
- A disposable clone of the target project
- Optional build dependencies required by the target project
- An OpenAI API key or Azure OpenAI configuration for the main workflow
- `OPENROUTER_API_KEY` if you run the prejudge LLM tools

Install Python dependencies:

```shell
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
```

If you use PDM:

```shell
pdm install
```

## Important Safety Notes

RetroPatch modifies the configured `project_dir` while running. The main
workflow calls Git cleanup operations, including hard reset and removal of
untracked files, inside the target repository.

Use a dedicated throwaway clone for `project_dir`. Do not point the tool at a
working tree that contains uncommitted work or important untracked files.

Validation scripts from `patch_dataset_dir` are copied into `project_dir` before
final validation. If files with the same names already exist in `project_dir`,
they may be replaced.

## Quick Start

1. Prepare a clean target-project clone.

```shell
git clone <project-url> dataset/<project-name>
```

2. Prepare a case directory containing optional validation scripts.

```text
patch_dataset_dir/
  build.sh    optional; builds the patched target
  test.sh     optional; runs regression tests
  poc.sh      optional; runs the bug trigger / PoC
```

If a script is absent, RetroPatch treats that validation stage as passed.

3. Copy and edit the example configuration.

```shell
cp src/example.yml case.yml
```

4. Run the backporting agent.

```shell
python src/backporting.py --config case.yml
```

Use debug mode for verbose agent and tool logs:

```shell
python src/backporting.py --config case.yml --debug
```

Runtime logs are created under `../logs` relative to the current working
directory and copied into `patch_dataset_dir` at the end of a run.

## Configuration

Example:

```yaml
project: libtiff
project_url: https://github.com/libsdl-org/libtiff
new_patch: 881a070194783561fd209b7c789a4e75566f7f37
new_patch_parent: 6bb0f1171adfcccde2cd7931e74317cccb7db845
target_release: 13f294c3d7837d630b3e9b08089752bc07b730e6
sanitizer: LeakSanitizer
error_message: "ERROR: LeakSanitizer"
tag: CVE-2023-3576
openai_key: sk-...
project_dir: dataset/libsdl-org/libtiff
patch_dataset_dir: ~/backports/patch_dataset/libtiff/CVE-2023-3576/

use_azure: false
# azure_endpoint: "https://your-resource.openai.azure.com/"
# azure_deployment: "gpt-5"
# azure_api_version: "2024-12-01-preview"
```

Field reference:

- `project`: Human-readable project name used in logs.
- `project_url`: Upstream repository URL, used as context for the agent.
- `new_patch`: Upstream fixed commit to backport.
- `new_patch_parent`: Parent commit of `new_patch`, representing the newer
  vulnerable revision before the fix.
- `target_release`: Older target commit or revision that needs the fix.
- `sanitizer`: Optional case metadata for the sanitizer used by the PoC.
- `error_message`: Text expected in PoC output when the bug is still triggered.
- `tag`: Case identifier, commonly a CVE or bug ID.
- `openai_key`: API key for the main backporting agent.
- `project_dir`: Local target-project Git repository.
- `patch_dataset_dir`: Case directory containing validation scripts and copied
  logs.
- `use_azure`, `azure_endpoint`, `azure_deployment`, `azure_api_version`:
  Optional Azure OpenAI settings.

The required commits must all exist in `project_dir`; the loader resolves them
to full commit hashes before the run starts.

## Backporting Workflow

```text
newer vulnerable revision --new_patch--> newer fixed revision
          |
          | backport fix
          v
older target revision ----generated patch----> fixed older target
```

For each hunk, the agent can use these tools:

- `viewcode`: inspect source code at a specific path and revision.
- `locate_symbol`: locate a function or symbol using Ctags.
- `git_history`: inspect history for lines related to the current hunk.
- `git_show`: inspect a relevant historical commit.
- `validate`: apply a hunk or complete patch and return concrete feedback.

After all hunks apply, RetroPatch validates the complete patch in this order:

1. Apply the complete patch to `target_release`.
2. Run `build.sh` if present.
3. Run `test.sh` if present.
4. Run `poc.sh` if present and check that `error_message` no longer appears.

## Prejudge Pipeline

The prejudge pipeline is useful when processing many kernel fixes. It filters
cases before full backporting by checking dependency/fix commits, architecture
and config relevance, and whether vulnerable code appears in the target tree.

Single commit:

```shell
export OPENROUTER_API_KEY=<your-key>
python src/prejudge/prejudge.py <commit-id> <kernel-source-dir> <target-project-dir>
```

Batch CSV:

```shell
python test/test_prejudge.py <input.csv> <output.csv> <kernel-source-dir> <target-project-dir>
```

The input CSV should contain `CVE-ID`, `Mainline_Commit`, and `Status` columns.
The output CSV adds a `Prejudge_Result` column.

The LLM-based judge can also be run directly:

```shell
python src/prejudge/judge_agent.py <commit-id> <src-project-path> <target-project-path> [model-provider]
```

Supported provider names are `openai`, `deepseek`, `gemini`, and `claude`.

## Docker

Build the image:

```shell
docker build -t retropatch .
```

Run with mounted project and dataset directories:

```shell
docker run --rm \
  -v "$(pwd)":/app \
  -v /path/to/dataset:/path/to/dataset \
  retropatch \
  python backporting.py --config /app/case.yml
```

Interactive shell:

```shell
docker run --rm -it \
  -v "$(pwd)":/app \
  -v /path/to/dataset:/path/to/dataset \
  retropatch /bin/bash
```

## Development And Validation

Check local setup:

```shell
python3 skills/retropatch-engineering/scripts/check_setup.py
python3 skills/retropatch-engineering/scripts/check_setup.py --config case.yml
```

Run helper validation scripts:

```shell
python test/test_patch.py --config case.yml
python test/test_prejudge.py test.csv test_results.csv data/linux data/kernel
```

`test/test_patch.py` and `test/test_hunk.py` are development helpers. They
contain embedded patch examples and may need editing for a specific case before
use.

## Troubleshooting

- `Commit id ... is invalid`: the configured commit does not exist in
  `project_dir`.
- `Project directory does not exist`: `project_dir` must point to a local Git
  checkout.
- Ctags errors or missing symbol results: install Universal Ctags and confirm
  `ctags` is on `PATH`.
- Patch applies but validation passes too quickly: check whether `build.sh`,
  `test.sh`, or `poc.sh` are missing from `patch_dataset_dir`; missing scripts
  are treated as passed.
- Prejudge API errors: set `OPENROUTER_API_KEY` for `src/prejudge/*` tools.

## Codex Skill

This repository includes a local Codex skill at
`skills/retropatch-engineering/`.

Use `$retropatch-engineering` when working on RetroPatch-specific tasks such as
pipeline changes in `src/backporting.py`, `src/agent/`, `src/tools/`, prejudge
changes in `src/prejudge/`, or documentation updates that depend on this
workflow.
