#!/usr/bin/env python3
"""
LLM-based Prejudge for Kernel Patches

This module integrates the LLM judge agent into the prejudge pipeline.
It can be used as an alternative or addition to the rule-based judges.
"""

import sys
from pathlib import Path


def judge_with_llm(
    commit_id: str, src_project_path: str, target_project_path: str
) -> bool:
    """
    Judge if a patch needs backporting using LLM analysis.

    This function uses an LLM agent to analyze the patch and determine
    if the vulnerable code exists in the target kernel.

    Args:
        commit_id: The upstream commit hash
        src_project_path: Path to source kernel repository
        target_project_path: Path to target kernel repository

    Returns:
        True if patch needs backporting, False otherwise

    Raises:
        ValueError: If paths are invalid
        RuntimeError: If LLM analysis fails
    """
    # Import with proper path handling
    import sys
    from pathlib import Path

    # Add the directory containing judge_agent to path
    _prejudge_path = Path(__file__).parent
    if str(_prejudge_path) not in sys.path:
        sys.path.insert(0, str(_prejudge_path))

    from judge_agent import JudgeAgent

    # Validate paths
    src_path = Path(src_project_path).resolve()
    target_path = Path(target_project_path).resolve()

    if not src_path.exists():
        raise ValueError(f"Source project path not found: {src_project_path}")

    if not target_path.exists():
        raise ValueError(f"Target project path not found: {target_project_path}")

    try:
        # Create agent with default settings (DeepSeek as per judge_agent.py)
        agent = JudgeAgent(
            target_project_path=str(target_path),
            model_provider="deepseek",
            ref="HEAD",
            debug_mode=False,
        )

        # Judge the patch
        needs_backport = agent.judge(str(src_path), commit_id)

        return needs_backport

    except Exception as e:
        # On error, be conservative and return True
        from tools.logger import logger

        logger.error(f"LLM judge failed for commit {commit_id}: {e}")
        return True


def main():
    """CLI interface for LLM-based prejudgment"""
    if len(sys.argv) < 4:
        print("Usage: judge_llm.py <commit-id> <src-project-path> <target-project-path>")
        print(
            "\nThis tool uses an LLM to analyze a kernel patch and determine"
            " if it needs backporting to the target kernel."
        )
        print("\nArguments:")
        print("  commit-id: The upstream commit hash to analyze")
        print("  src-project-path: Path to the source kernel repository")
        print("  target-project-path: Path to the target/downstream kernel repository")
        print("\nOutput:")
        print("  'true' if the patch needs backporting")
        print("  'false' if the patch does NOT need backporting")
        print("\nEnvironment:")
        print("  Requires OPENROUTER_API_KEY to be set")
        sys.exit(1)

    commit_id = sys.argv[1]
    src_project_path = sys.argv[2]
    target_project_path = sys.argv[3]

    try:
        result = judge_with_llm(commit_id, src_project_path, target_project_path)
        print("true" if result else "false")

    except ValueError as e:
        print(f"Error: {e}", file=sys.stderr)
        sys.exit(1)
    except Exception as e:
        print(f"Error: {e}", file=sys.stderr)
        sys.exit(1)


if __name__ == "__main__":
    main()