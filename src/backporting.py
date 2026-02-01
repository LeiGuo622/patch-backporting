import argparse
import datetime
import logging
import os
from types import SimpleNamespace

import git
import yaml

from agent.invoke_llm import do_backport, initial_agent
from check.usage import get_usage
from tools.logger import add_file_handler, logger
from tools.project import Project


def is_commit_valid(commit_id: str, project_dir: str):
    try:
        repo = git.Repo(project_dir)
        repo.commit(commit_id)
        return True
    except git.exc.BadName:
        logger.error(f"Commit id {commit_id} in .yml is invalid.")
        return False


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

    data.error_message = config.get("error_message", "")
    if not data.error_message:
        logger.warning(
            "Dataset without error info which means that this vulnerability may not have PoC\n"
        )

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

    if (
        not is_commit_valid(data.new_patch, data.project_dir)
        or not is_commit_valid(data.target_release, data.project_dir)
        or not is_commit_valid(data.new_patch_parent, data.project_dir)
    ):
        exit(1)

    return data


def main():
    # process arguments
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

    # load and check config, create file log
    data = load_yml(config_file)
    log_dir = "../logs"
    os.makedirs(log_dir, exist_ok=True)
    now = datetime.datetime.now().strftime("%m%d%H%M")
    logfile = os.path.join(log_dir, f"{data.project}-{data.tag}-{now}.log")
    add_file_handler(logger, logfile)

    # use LLM to backport
    project = Project(data)
    project.repo.git.clean("-fdx")

    before_usage = get_usage(data.openai_key)
    agent_executor, llm = initial_agent(project, data.openai_key, debug_mode)
    do_backport(agent_executor, project, data, llm, logfile)
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
