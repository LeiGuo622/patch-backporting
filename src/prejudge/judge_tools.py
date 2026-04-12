#!/usr/bin/env python3
"""
Tools for Judge Agent

Provides locate_symbol and view_code tools for the judge agent to search
and examine code in the target downstream kernel.
"""

import subprocess
from pathlib import Path

from langchain_core.tools import tool

from tools.logger import logger


def create_locate_symbol_tool(project_path: Path, ref: str):
    """
    Create a locate_symbol tool for finding symbols in the target kernel.

    Args:
        project_path: Path to the target kernel repository
        ref: Git reference to search in

    Returns:
        A LangChain tool function
    """

    @tool
    def locate_symbol(symbol: str) -> str:
        """
        Locate a symbol (function, variable, etc.) in the target kernel code.

        Use this tool to find where a specific symbol is defined in the downstream kernel.
        This helps you determine if the code related to the vulnerability exists.

        Args:
            symbol: The symbol name to search for (e.g., function name, variable name)

        Returns:
            A string listing all locations where the symbol is found, in the format:
            "file_path:line_number" for each occurrence
        """
        try:
            # Use git grep to find the symbol
            result = subprocess.run(
                ["git", "grep", "-n", f"\\b{symbol}\\b", ref],
                cwd=project_path,
                capture_output=True,
                text=True,
                timeout=30,
            )

            if result.returncode != 0:
                # Symbol not found
                return f"The symbol '{symbol}' was NOT FOUND in the target kernel at ref {ref}."

            # Parse the results
            lines = result.stdout.strip()

            return lines[:1000]  # Limit output to first 1000 characters

        except subprocess.TimeoutExpired:
            logger.error(f"Locate symbol timed out for: {symbol}")
            return f"Error: Search timed out for symbol '{symbol}'"
        except Exception as e:
            logger.error(f"Error locating symbol: {e}")
            return f"Error searching for symbol '{symbol}': {str(e)}"

    return locate_symbol


def create_view_code_tool(project_path: Path, ref: str):
    """
    Create a view_code tool for examining source files in the target kernel.

    Args:
        project_path: Path to the target kernel repository
        ref: Git reference to view

    Returns:
        A LangChain tool function
    """

    @tool
    def view_code(file_path: str, start_line: int = 1, end_line: int = 100) -> str:
        """
        View source code from a file in the target kernel.

        Use this tool to examine the actual code around a symbol or location
        to determine if the vulnerable code pattern exists.

        Args:
            file_path: Path to the source file (relative to repository root)
            start_line: Starting line number (default: 1)
            end_line: Ending line number (default: 100)

        Returns:
            The source code content between the specified line numbers
        """
        try:
            # Validate inputs
            if start_line < 1:
                start_line = 1
            if end_line < start_line:
                end_line = start_line
            if end_line - start_line > 500:
                # Limit the window size
                end_line = start_line + 500

            # Use git show to get file content at specific ref
            result = subprocess.run(
                ["git", "show", f"{ref}:{file_path}"],
                cwd=project_path,
                capture_output=True,
                text=True,
                timeout=30,
            )

            if result.returncode != 0:
                return f"Error: File '{file_path}' not found at ref {ref}"

            # Get the lines
            all_lines = result.stdout.split("\n")
            total_lines = len(all_lines)

            # Adjust if beyond file length
            if start_line > total_lines:
                return f"Error: File has only {total_lines} lines, but start_line is {start_line}"

            if end_line > total_lines:
                end_line = total_lines

            # Extract the requested lines
            lines = all_lines[start_line - 1 : end_line]

            # Format output with line numbers
            output = [
                f"Showing {file_path} lines {start_line}-{end_line} "
                f"(at ref {ref}, total {total_lines} lines):\n"
            ]
            output.append("```")
            for i, line in enumerate(lines, start=start_line):
                output.append(f"{i:5d}: {line}")
            output.append("```")

            return "\n".join(output)

        except subprocess.TimeoutExpired:
            logger.error(f"View code timed out for: {file_path}")
            return f"Error: Reading file timed out"
        except Exception as e:
            logger.error(f"Error viewing code: {e}")
            return f"Error viewing file '{file_path}': {str(e)}"

    return view_code