[![English](https://img.shields.io/badge/Lang-English-blue.svg)](README.md)

# RetroPatch

RetroPatch 是一个由 LLM 辅助的补丁回移工具集。它接收新版本中的修复提交，分析该补丁为什么不能直接应用到旧版本目标提交，并结合 Git、符号定位、源码查看、编译、测试和 PoC 验证反馈，迭代生成适配目标版本的补丁。

仓库还包含面向内核场景的预判流程，用于在执行成本更高的补丁生成前，判断候选上游修复是否值得回移到目标源码树。

## 项目能力

RetroPatch 自动化的是常见的回移循环：

1. 读取已知修复提交，并拆分为多个 patch hunk。
2. 尝试将每个 hunk 直接应用到目标旧版本。
3. 如果 hunk 冲突，LLM agent 会调用仓库工具定位旧版本中的对应代码，并重写 hunk。
4. 将所有成功 hunk 合并为完整补丁。
5. 通过补丁应用、编译、回归测试和 PoC 检查验证完整补丁。
6. 保存日志和最终成功补丁信息，供人工复核。

该工具适用于安全修复和维护分支回移，尤其是目标分支与上游之间存在代码移动、符号重命名、上下文变化或部分逻辑缺失的场景。

## 目录结构

```text
src/backporting.py          主回移命令入口
src/example.yml             示例配置
src/agent/                  LLM prompt 与 agent 编排
src/tools/                  Git、patch、符号、验证和日志工具
src/prejudge/               内核回移预判流程
test/                       hunk、patch、prejudge 辅助测试脚本
skills/retropatch-engineering/
                            本仓库专用的本地 Codex skill
Dockerfile                  容器化运行环境
```

## 环境要求

- Python 3.10 或更高版本
- Git
- Universal Ctags（命令为 `ctags`），用于符号索引
- 目标项目的一份可丢弃 clone
- 目标项目自身需要的可选构建依赖
- 主回移流程使用的 OpenAI API key 或 Azure OpenAI 配置
- 如果运行预判 LLM 工具，需要设置 `OPENROUTER_API_KEY`

安装 Python 依赖：

```shell
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
```

如果使用 PDM：

```shell
pdm install
```

## 重要安全说明

RetroPatch 运行时会修改配置中的 `project_dir`。主流程会在目标仓库内执行 Git 清理操作，包括 hard reset 和删除未跟踪文件。

请为 `project_dir` 使用专门的、可丢弃的 clone。不要把包含未提交修改或重要未跟踪文件的工作区交给该工具。

最终验证前，`patch_dataset_dir` 中的验证脚本会被复制到 `project_dir`。如果目标仓库内已有同名文件，可能会被替换。

## 快速开始

1. 准备干净的目标项目 clone。

```shell
git clone <project-url> dataset/<project-name>
```

2. 准备案例目录，放置可选验证脚本。

```text
patch_dataset_dir/
  build.sh    可选；构建打补丁后的目标项目
  test.sh     可选；运行回归测试
  poc.sh      可选；运行 bug 触发脚本 / PoC
```

如果某个脚本不存在，RetroPatch 会将对应验证阶段视为通过。

3. 复制并编辑示例配置。

```shell
cp src/example.yml case.yml
```

4. 运行回移 agent。

```shell
python src/backporting.py --config case.yml
```

使用 debug 模式输出更详细的 agent 和工具日志：

```shell
python src/backporting.py --config case.yml --debug
```

运行日志会创建在当前工作目录相对路径 `../logs` 下，并在运行结束时复制到 `patch_dataset_dir`。

## 配置说明

示例：

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

字段说明：

- `project`：项目名称，用于日志。
- `project_url`：上游仓库 URL，作为 agent 上下文。
- `new_patch`：需要回移的新版本修复提交。
- `new_patch_parent`：`new_patch` 的父提交，即新版本中修复前的漏洞版本。
- `target_release`：需要应用修复的旧版本目标提交或 revision。
- `sanitizer`：PoC 使用的 sanitizer 类型，作为案例元数据。
- `error_message`：PoC 输出中代表 bug 仍可触发的关键文本。
- `tag`：案例标识，通常是 CVE 或 bug ID。
- `openai_key`：主回移 agent 使用的 API key。
- `project_dir`：本地目标项目 Git 仓库路径。
- `patch_dataset_dir`：案例目录，包含验证脚本并接收日志副本。
- `use_azure`、`azure_endpoint`、`azure_deployment`、`azure_api_version`：可选 Azure OpenAI 配置。

所有必需提交都必须存在于 `project_dir` 中；配置加载阶段会将它们解析为完整 commit hash。

## 回移流程

```text
新版本漏洞提交 --new_patch--> 新版本已修复提交
        |
        | 回移修复
        v
旧版本目标提交 ----生成补丁----> 旧版本已修复状态
```

处理每个 hunk 时，agent 可以调用以下工具：

- `viewcode`：查看指定 revision、路径和行号范围的源码。
- `locate_symbol`：通过 Ctags 定位函数或符号。
- `git_history`：查看与当前 hunk 相关代码行的历史。
- `git_show`：查看相关历史提交内容。
- `validate`：应用 hunk 或完整补丁，并返回具体反馈。

所有 hunk 应用成功后，RetroPatch 按以下顺序验证完整补丁：

1. 将完整补丁应用到 `target_release`。
2. 如果存在 `build.sh`，运行构建。
3. 如果存在 `test.sh`，运行回归测试。
4. 如果存在 `poc.sh`，运行 PoC，并检查 `error_message` 是否不再出现。

## 预判流程

预判流程适合批量处理内核修复。它会在完整回移前检查依赖/修复提交、架构和配置相关性，以及目标源码树中是否存在漏洞代码。

单个提交：

```shell
export OPENROUTER_API_KEY=<your-key>
python src/prejudge/prejudge.py <commit-id> <kernel-source-dir> <target-project-dir>
```

批量 CSV：

```shell
python test/test_prejudge.py <input.csv> <output.csv> <kernel-source-dir> <target-project-dir>
```

输入 CSV 需要包含 `CVE-ID`、`Mainline_Commit` 和 `Status` 三列。输出 CSV 会新增 `Prejudge_Result` 列。

也可以直接运行 LLM 判定 agent：

```shell
python src/prejudge/judge_agent.py <commit-id> <src-project-path> <target-project-path> [model-provider]
```

支持的 provider 名称包括 `openai`、`deepseek`、`gemini` 和 `claude`。

## Docker

构建镜像：

```shell
docker build -t retropatch .
```

挂载项目和数据目录运行：

```shell
docker run --rm \
  -v "$(pwd)":/app \
  -v /path/to/dataset:/path/to/dataset \
  retropatch \
  python backporting.py --config /app/case.yml
```

进入交互 shell：

```shell
docker run --rm -it \
  -v "$(pwd)":/app \
  -v /path/to/dataset:/path/to/dataset \
  retropatch /bin/bash
```

## 开发与验证

检查本地设置：

```shell
python3 skills/retropatch-engineering/scripts/check_setup.py
python3 skills/retropatch-engineering/scripts/check_setup.py --config case.yml
```

运行辅助验证脚本：

```shell
python test/test_patch.py --config case.yml
python test/test_prejudge.py test.csv test_results.csv data/linux data/kernel
```

`test/test_patch.py` 和 `test/test_hunk.py` 是开发辅助脚本，内部包含示例 patch。针对具体案例使用前，通常需要先编辑脚本中的示例内容。

## 常见问题

- `Commit id ... is invalid`：配置中的提交不存在于 `project_dir`。
- `Project directory does not exist`：`project_dir` 必须指向本地 Git checkout。
- Ctags 报错或符号定位结果异常：安装 Universal Ctags，并确认 `ctags` 在 `PATH` 中。
- 补丁应用后验证很快通过：检查 `patch_dataset_dir` 是否缺少 `build.sh`、`test.sh` 或 `poc.sh`；缺失脚本会被视为通过。
- 预判流程 API 报错：为 `src/prejudge/*` 工具设置 `OPENROUTER_API_KEY`。

## Codex Skill

仓库内置了本地 Codex skill：`skills/retropatch-engineering/`。

处理 RetroPatch 特定任务时可以使用 `$retropatch-engineering`，例如修改 `src/backporting.py`、`src/agent/`、`src/tools/` 中的回移流程，修改 `src/prejudge/` 中的预判流程，或更新依赖本仓库工作流的文档。
