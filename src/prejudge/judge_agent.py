#!/usr/bin/env python3
"""
Judge Agent for Patch Backport Necessity

This module uses an LLM-based agent to analyze kernel patches and determine
whether they need to be backported to downstream kernels based on whether
the vulnerable code exists in the target.
"""

import os
import subprocess
from functools import partial
from pathlib import Path
from typing import Literal

from langchain.agents import AgentExecutor, create_tool_calling_agent
from langchain.prompts import ChatPromptTemplate, MessagesPlaceholder
from langchain_openai import ChatOpenAI

# Handle imports for both direct execution and module import
import sys
from pathlib import Path

# Add current directory to path for imports
_prejudge_path = Path(__file__).parent
_src_path = Path(__file__).parent.parent
if str(_prejudge_path) not in sys.path:
    sys.path.insert(0, str(_prejudge_path))
if str(_src_path) not in sys.path:
    sys.path.insert(0, str(_src_path))

from judge_tools import create_locate_symbol_tool, create_view_code_tool
from judge_prompt import JUDGE_SYSTEM_PROMPT, JUDGE_USER_PROMPT
from tools.logger import logger


# LLM Configuration
_openrouter_common = partial(
    ChatOpenAI,
    temperature=0.0,
    verbose=True,
    base_url="https://newapi.sophie.pub/v1",
)

SUPPORTED_MODELS = {
    "openai": {
        "name": "OpenAI",
        "default_model": "openai/gpt-4o",
        "key_env_name": "OPENROUTER_API_KEY",
        "constructor": _openrouter_common,
    },
    "deepseek": {
        "name": "DeepSeek",
        "default_model": "deepseek/deepseek-chat",
        "key_env_name": "OPENROUTER_API_KEY",
        "constructor": _openrouter_common,
    },
    "gemini": {
        "name": "Gemini",
        "default_model": "google/gemini-2.5-pro",
        "key_env_name": "OPENROUTER_API_KEY",
        "constructor": _openrouter_common,
    },
    "claude": {
        "name": "Claude",
        "default_model": "anthropic/claude-3-5-sonnet-20240620",
        "key_env_name": "OPENROUTER_API_KEY",
        "constructor": _openrouter_common,
    },
}


class JudgeAgent:
    """Agent to judge if a patch needs to be backported"""

    def __init__(
        self,
        target_project_path: str,
        model_provider: Literal["openai", "deepseek", "gemini", "claude"] = "openai",
        ref: str = "HEAD",
        debug_mode: bool = False,
    ):
        """
        Initialize the judge agent.

        Args:
            target_project_path: Path to the target downstream kernel
            model_provider: LLM provider to use (claude, openai, deepseek, gemini)
            ref: Git reference to check in the target project (default: HEAD)
            debug_mode: Enable verbose logging
        """
        self.target_project_path = Path(target_project_path).resolve()
        if not self.target_project_path.exists():
            raise ValueError(f"Target project path not found: {target_project_path}")

        self.ref = ref
        self.debug_mode = debug_mode

        # Initialize LLM
        if model_provider not in SUPPORTED_MODELS:
            raise ValueError(f"Unsupported model provider: {model_provider}")

        model_config = SUPPORTED_MODELS[model_provider]
        api_key = os.getenv(model_config["key_env_name"])

        if not api_key:
            raise ValueError(
                f"API key not found. Please set {model_config['key_env_name']} environment variable."
            )

        self.llm = model_config["constructor"](
            model=model_config["default_model"],
            api_key=api_key,
        )

        # Create tools
        self.locate_symbol = create_locate_symbol_tool(self.target_project_path, self.ref)
        self.view_code = create_view_code_tool(self.target_project_path, self.ref)

        self.tools = [self.locate_symbol, self.view_code]

        # Create agent
        prompt = ChatPromptTemplate.from_messages(
            [
                ("system", JUDGE_SYSTEM_PROMPT),
                ("user", JUDGE_USER_PROMPT),
                MessagesPlaceholder(variable_name="agent_scratchpad"),
            ]
        )

        agent = create_tool_calling_agent(self.llm, self.tools, prompt)
        self.agent_executor = AgentExecutor(
            agent=agent,
            tools=self.tools,
            verbose=debug_mode,
            max_iterations=15,
            handle_parsing_errors=True,
        )

    def get_patch_from_commit(self, src_project_path: str, commit_id: str) -> str:
        """
        Get patch content from a commit in the source project.

        Args:
            src_project_path: Path to the source kernel repository
            commit_id: The commit hash to retrieve

        Returns:
            Patch content as string
        """
        try:
            result = subprocess.run(
                ["git", "show", commit_id],
                cwd=src_project_path,
                capture_output=True,
                text=True,
                timeout=30,
            )

            if result.returncode != 0:
                logger.error(f"Failed to get patch from commit {commit_id}")
                return ""

            return result.stdout
        except subprocess.TimeoutExpired:
            logger.error(f"Git show timed out for commit {commit_id}")
            return ""
        except Exception as e:
            logger.error(f"Error getting patch from commit: {e}")
            return ""

    def judge(self, src_project_path: str, commit_id: str) -> bool:
        """
        Judge if a patch needs to be backported.

        Args:
            src_project_path: Path to the source kernel repository
            commit_id: The commit hash to judge

        Returns:
            True if the patch needs to be backported, False otherwise
        """
        # Get patch content
        patch_content = self.get_patch_from_commit(src_project_path, commit_id)

        if not patch_content:
            logger.warning(f"Could not retrieve patch for commit {commit_id}")
            # If we can't get the patch, err on the side of caution and say yes
            return True

        # Invoke the agent
        try:
            result = self.agent_executor.invoke(
                {
                    "patch_content": patch_content,
                }
            )

            # Parse the agent's response
            response = result.get("output", "")

            return self._parse_decision(response)

        except Exception as e:
            logger.error(f"Error during agent execution: {e}")
            # If agent fails, err on the side of caution and say yes
            return True

    def _parse_decision(self, response: str) -> bool:
        """
        Parse the agent's decision from its response.

        Args:
            response: The agent's text response

        Returns:
            True if needs backporting, False otherwise

        The parsing logic looks for explicit decision markers:
        - YES/TRUE/NEEDS_BACKPORT -> True
        - NO/FALSE/DOES_NOT_NEED -> False

        If no clear decision is found, defaults to True (conservative approach).
        """
        response_lower = response.lower()

        # Check for clear "no" indicators first
        no_indicators = [
            "does not need",
            "doesn't need",
            "does not exist",
            "doesn't exist",
            "clearly not present",
            "obviously absent",
            "definitely not",
            "conclusion: false",
            "conclusion: no",
            "decision: no",
            "decision: false",
            "answer: false",
            "answer: no",
        ]

        for indicator in no_indicators:
            if indicator in response_lower:
                logger.debug(f"Found 'no' indicator: '{indicator}'")
                return False

        # Check for "yes" indicators (used if no "no" found)
        yes_indicators = [
            "needs to be backported",
            "should be backported",
            "requires backporting",
            "clearly present",
            "obviously exists",
            "definitely exists",
            "conclusion: true",
            "conclusion: yes",
            "decision: yes",
            "decision: true",
            "answer: true",
            "answer: yes",
        ]

        for indicator in yes_indicators:
            if indicator in response_lower:
                logger.debug(f"Found 'yes' indicator: '{indicator}'")
                return True

        # If no clear decision found, check overall tone
        # If the response says the code exists and needs fixing, return True
        if any(
            word in response_lower
            for word in ["vulnerability exists", "bug exists", "code is present", "found in"]
        ):
            return True

        # Default: conservative approach - if uncertain, say yes
        logger.debug("No clear decision found, defaulting to True (conservative)")
        return True


def main():
    """CLI interface for the judge agent"""
    import sys

    if len(sys.argv) < 4:
        print(
            "Usage: judge_agent.py <commit-id> <src-project-path> <target-project-path> [model-provider]"
        )
        print(
            "  commit-id: The upstream commit hash to judge (e.g., 5a4041f2c47247575a6c2e53ce14f7b0ac946c33)"
        )
        print("  src-project-path: Path to the source kernel repository")
        print("  target-project-path: Path to the target/downstream kernel repository")
        print(
            "  model-provider: Optional, one of: claude (default), openai, deepseek, gemini"
        )
        sys.exit(1)

    commit_id = sys.argv[1]
    src_project_path = sys.argv[2]
    target_project_path = sys.argv[3]
    model_provider = sys.argv[4] if len(sys.argv) >= 5 else "openai"

    try:
        # Create judge agent
        agent = JudgeAgent(
            target_project_path=target_project_path,
            model_provider=model_provider,
            debug_mode=True,
        )

        # Judge the patch
        needs_backport = agent.judge(src_project_path, commit_id)

        # Output result as true/false
        print("true" if needs_backport else "false")

    except Exception as e:
        logger.error(f"Error: {e}")
        sys.exit(1)


if __name__ == "__main__":
    main()