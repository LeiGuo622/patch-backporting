[![简体中文](https://img.shields.io/badge/语言-简体中文-red.svg)](README.zh-CN.md)

# patch-backporting

## Demo

[![asciicast](https://asciinema.org/a/8J9k0iBJ6IkdDmvr.svg)](https://asciinema.org/a/8J9k0iBJ6IkdDmvr)

## Usage

```shell
python src/backporting.py --config src/example.yml # Remember to fill out the config first.
```

## Codex Skill

This repository includes a local Codex skill at `skills/retropatch-engineering/`.

Use `$retropatch-engineering` when working on RetroPatch-specific tasks such as:

- backporting pipeline changes in `src/backporting.py`, `src/agent/`, or `src/tools/`
- prejudge pipeline changes in `src/prejudge/`
- config, prompt, validation, test, or README updates that depend on this repository's workflow

Example prompt:

```text
Use $retropatch-engineering to update the prejudge pipeline and keep the docs in sync.
```

Before claiming the local setup is runnable, run:

```shell
python3 skills/retropatch-engineering/scripts/check_setup.py
python3 skills/retropatch-engineering/scripts/check_setup.py --config path/to/config.yml
```

## Docker Usage

Build the docker image:

```shell
docker build -t patch-backporting .
```

Run the container:

```shell
# Ensure you mount the necessary directories (code, config, datasets)
# Example: assuming config.yml is in current dir and datasets are in /data
docker run --rm -v $(pwd):/app -v /path/to/dataset:/path/to/dataset patch-backporting python backporting.py --config example.yml
```

Alternatively, you can use the interactive mode to execute scripts inside the container:

```shell
docker run --rm -it -v $(pwd):/app -v /path/to/dataset:/path/to/dataset patch-backporting /bin/bash
# Inside the container
cd /app/src
python backporting.py --config example.yml
```

## Config structure

```yml
project: libtiff
project_url: https://github.com/libsdl-org/libtiff 
new_patch: 881a070194783561fd209b7c789a4e75566f7f37 # patch commit id in new version, Version A(Fixed)    
new_patch_parent: 6bb0f1171adfcccde2cd7931e74317cccb7db845 # patch parent commit, Version A 
target_release: 13f294c3d7837d630b3e9b08089752bc07b730e6 # commid id which need to be fixed, Version B 
sanitizer: LeakSanitizer # sanitizer type for poc, could be empty
error_message: "ERROR: LeakSanitizer" # poc trigger message for poc, could be empty
tag: CVE-2023-3576
openai_key: # Your openai key
project_dir: dataset/libsdl-org/libtiff # path to your project
patch_dataset_dir: ~/backports/patch_dataset/libtiff/CVE-2023-3576/ # path to your patchset, include build.sh, test.sh ....

# Optional: Azure OpenAI Configuration
# use_azure: true
# azure_endpoint: "https://your-resource.openai.azure.com/"
# azure_deployment: "gpt-4"
# azure_api_version: "2024-12-01-preview"

#                    Version A           Version A(Fixed)     
#   ┌───┐            ┌───┐             ┌───┐                  
#   │   ├───────────►│   ├────────────►│   │                  
#   └─┬─┘            └───┘             └───┘                  
#     │                                                       
#     │                                                       
#     │                                                       
#     │              Version B                                
#     │              ┌───┐                                    
#     └─────────────►│   ├────────────► ??                    
#                    └───┘                       
```
