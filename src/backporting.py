import argparse
import logging
import os
from types import SimpleNamespace

import yaml

from agent.backports import do_backport, initial_agent
from check.usage import get_usage
from tools.logger import logger
from tools.project import Project


def load_yml(file_path: str):
    """
    Load YAML configuration from a file and return the data as a SimpleNamespace object.

    Args:
        file_path (str): The path to the YAML file.

    Returns:
        data (SimpleNamespace): The configuration data stored in a SimpleNamespace object.
    """
    with open(file_path, "r") as file:
        config = yaml.safe_load(file)

    data = SimpleNamespace()
    data.project = config.get("project")
    data.project_url = config.get("project_url")
    data.project_dir = config.get("project_dir")
    data.patch_dataset_dir = config.get("patch_dataset_dir")
    data.openai_key = config.get("openai_key")
    data.tag = config.get("tag")

    data.new_patch = config.get("new_patch", "")
    if not data.new_patch or not data.new_patch:
        logger.error(
            "Please check your configuration to make sure new_patch is correct!\n"
        )
        exit(1)

    data.new_patch_parent = config.get("new_patch_parent", "")
    if not data.new_patch_parent or not data.new_patch_parent:
        logger.error(
            "Please check your configuration to make sure new_patch_parent is correct!\n"
        )
        exit(1)

    data.target_release = config.get("target_release", "")
    if not data.target_release or not data.target_release:
        logger.error(
            "Please check your configuration to make sure target_release is correct!\n"
        )
        exit(1)

    data.error_message = config.get("error_massage", "")
    if not data.error_message:
        logger.warning(
            "Dataset without error info which means that this vulnerability may not have PoC\n"
        )

    return data


def main():
    parser = argparse.ArgumentParser(
        description="Backports patch with the help of LLM",
        usage="%(prog)s --config CONFIG.yml\ne.g.: python %(prog)s --config CVE-examaple.yml",
    )
    parser.add_argument(
        "-c", "--config", type=str, required=True, help="CVE config yml"
    )
    parser.add_argument("-d", "--debug", action="store_true", help="enable debug mode")

    args = parser.parse_args()
    debug_mode = args.debug
    config_file = args.config

    if debug_mode:
        logger.setLevel(logging.DEBUG)
    else:
        logger.setLevel(logging.INFO)

    data = load_yml(config_file)

    data.project_dir = os.path.expanduser(
        data.project_dir if data.project_dir.endswith("/") else data.project_dir + "/"
    )
    data.patch_dataset_dir = os.path.expanduser(
        data.patch_dataset_dir
        if data.patch_dataset_dir.endswith("/")
        else data.patch_dataset_dir + "/"
    )

    if not os.path.isdir(data.project_dir):
        logger.error(f"Project directory does not exist: {data.project_dir}")
        exit(1)
    if not os.path.isdir(data.patch_dataset_dir):
        logger.error(
            f"Patch dataset directory does not exist: {data.patch_dataset_dir}"
        )
        exit(1)

    project = Project(data.project_url, data.project_dir, data.error_message)
    project.repo.git.clean("-fdx")
    if (
        not project._checkout(data.new_patch)
        or not project._checkout(data.target_release)
        or not project._checkout(data.new_patch_parent)
    ):
        logger.error("Please check given commit id.")
        exit(1)

    before_usage = get_usage(data.openai_key)
    agent_executor, llm = initial_agent(project, data.openai_key, debug_mode)
    do_backport(agent_executor, project, data, llm)
    after_usage = get_usage(data.openai_key)
    logger.debug(
        f"This patch total cost: ${(after_usage['total_cost'] - before_usage['total_cost']):.2f}"
    )
    logger.debug(
        f"This patch total consume tokens: {(after_usage['total_consume_tokens'] - before_usage['total_consume_tokens'])/1000}(k)"
    )


if __name__ == "__main__":
    main()

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
