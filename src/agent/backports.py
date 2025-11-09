import os
import re

from langchain.agents import AgentExecutor, create_tool_calling_agent
from langchain.prompts import ChatPromptTemplate, MessagesPlaceholder
from langchain_core.callbacks import FileCallbackHandler
from langchain_openai import ChatOpenAI

from agent.prompt import SYSTEM_PROMPT, USER_PROMPT_HUNK, USER_PROMPT_PATCH
from tools.logger import logger
from tools.project import Project
from tools.utils import split_patch


def initial_agent(project: Project, api_key: str, debug_mode: bool):
    base_url = "https://api.openai.com/v1"

    llm = ChatOpenAI(
        temperature=0,
        model="gpt-4-turbo",
        api_key=api_key,
        openai_api_base=base_url,
        verbose=True,
    )

    prompt = ChatPromptTemplate.from_messages(
        [
            ("system", SYSTEM_PROMPT),
            ("user", USER_PROMPT_HUNK),
            MessagesPlaceholder(variable_name="agent_scratchpad"),
        ]
    )
    viewcode, locate_symbol, validate = project.get_tools()
    tools = [viewcode, locate_symbol, validate]
    agent = create_tool_calling_agent(llm, tools, prompt)
    agent_executor = AgentExecutor(
        agent=agent, tools=tools, verbose=debug_mode, max_iterations=30
    )
    return agent_executor


def do_backport(agent_executor, project, data):
    log_dir = "../logs"
    os.makedirs(log_dir, exist_ok=True)
    logfile = os.path.join(log_dir, "{}-llm.log".format(data.tag))
    log_handler = FileCallbackHandler(logfile)

    patch = project._get_patch(data.new_patch)
    pps = split_patch(patch)
    for idx, pp in enumerate(pps):
        project.round_succeeded = False
        ret = project._apply_hunk(data.target_release, pp)
        if project.round_succeeded:
            logger.debug(f"Hunk {idx} can be applied without any conflicts")
            continue
        else:
            similar_block = re.findall(r"section.\n(.*?)\nPlease", ret, re.DOTALL)[0]
            logger.debug(f"Hunk {idx} can not be applied, using LLM to generate a fix")
            agent_executor.invoke(
                {
                    "project_url": data.project_url,
                    "new_patch_parent": data.new_patch_parent,
                    "new_patch": pp,
                    "target_release": data.target_release,
                    "similar_block": similar_block,
                },
                {"callbacks": [log_handler]},
            )
            if not project.round_succeeded:
                logger.debug(
                    f"Failed to backport the hunk {idx} \n----------------------------------\n{pp}\n----------------------------------\n"
                )
                logger.error(f"Abort")
                exit(1)

    project.all_hunks_applied_succeeded = True
    logger.info(
        "Successfully apply all hunks, try to join all hunks into one patch and test"
    )
    complete_patch = "\n".join(project.succeeded_patches)

    for file in os.listdir(data.patch_dataset_dir):
        if os.path.exists(f"{data.project_dir}{file}"):
            os.remove(f"{data.project_dir}{file}")
        os.symlink(f"{data.patch_dataset_dir}{file}", f"{data.project_dir}{file}")

    validate_ret = project._validate(data.target_release, complete_patch)
    if project.poc_succeeded:
        logger.info(
            f"Successfully backport patch to target release {data.target_release}"
        )
        for patch in project.succeeded_patches:
            logger.info(patch)
    return
    prompt = ChatPromptTemplate.from_messages(
        [
            ("system", SYSTEM_PROMPT),
            ("user", USER_PROMPT_PATCH),
            MessagesPlaceholder(variable_name="agent_scratchpad"),
        ]
    )
    agent = create_tool_calling_agent(llm, tools, prompt)
    agent_executor = AgentExecutor(
        agent=agent, tools=tools, verbose=True, max_iterations=5
    )
    agent_executor.invoke(
        {
            "project_url": project_url,
            "new_patch_parent": new_patch_parent,
            "new_patch": complete_patch,
            "target_release": target_release,
            "error_message": validate_ret,
        },
        {"callbacks": [log_handler]},
    )
    if not project.compile_succeeded:
        logger.debug(f"Failed to complie the patch")
        logger.error(f"Abort")
        exit(1)
    else:
        logger.info(
            f"Successfully backport the patch to target release {target_release}"
        )
