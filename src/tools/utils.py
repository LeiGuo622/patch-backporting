import os
import re
import traceback
from typing import Generator, List, Tuple

import Levenshtein

from tools.logger import logger

blacklist = [
    ".rst",
    ".yaml",
    ".yml",
    ".md",
    ".tcl",
    "CHANGES",
    "ANNOUNCE",
    "NEWS",
    ".pem",
    ".js",
    ".sha1",
    ".sha256",
    ".uuid",
    ".test",
    "manifest",
    ".xml",
    "_test.go",
    ".json",
    ".golden",
    ".txt",
    ".mdx",
]


def find_most_similar_files(target_filename: str, search_directory: str) -> List[str]:
    """
    Find the five file paths that are most similar to non-existent files.

    Args:
        target_filename (str): The target file's name which we want to find out.
        search_directory (str): Directory name which we need to find in.

    Returns:
        List[str]: List of the five most similar file.
    """
    top_n = 5
    similarity_list = []

    # Walk through all subdirectories and files in the search directory
    for root, dirs, files in os.walk(search_directory):
        for filename in files:
            # Calculate the Levenshtein distance between the target filename and the current filename
            distance = Levenshtein.distance(target_filename, filename)
            relative_path = os.path.relpath(
                os.path.join(root, filename), search_directory
            )
            similarity_list.append((distance, relative_path))

    # Sort the list by distance in ascending order and get the top N results
    similarity_list.sort(key=lambda x: x[0])
    top_similar_files = [
        relative_path for distance, relative_path in similarity_list[:top_n]
    ]

    return top_similar_files


def find_most_similar_block(
    code_lines: List[str], lines: List[str], snippet_num: int
) -> Tuple[int, int]:
    """
    Finds the most similar block of code in a list of lines to a given code snippet.

    Args:
        code_snippet (str): The code snippet to compare against.
        lines (List[str]): The list of lines containing code blocks.
        snippet_num (int): The number of lines in the code snippet.

    Returns:
        int: The index of the start line of the most similar block.
        int: Minimum Edit Distance.
    """
    min_distance = float("inf")
    best_start_index = 1

    for i in range(len(lines) - snippet_num + 1):
        distance = sum(
            Levenshtein.distance(code_lines[j], lines[i + j])
            for j in range(snippet_num)
        )
        if distance < min_distance:
            min_distance = distance
            best_start_index = i + 1

    return best_start_index, min_distance


def extract_context(lines: str) -> Tuple[str, int]:
    """
    Process the input string by removing certain lines and returning the processed string and the count of processed lines.

    Args:
        input_string (str): The input string to be processed.

    Returns:
        tuple[str, int]: A tuple containing the processed string and the count of processed lines.
    """
    processed_lines = []
    for line in lines:
        if line.startswith(" "):
            processed_lines.append(line[1:])
        elif line.startswith("-"):
            processed_lines.append(line[1:])

    processed_lines_count = len(processed_lines)

    return processed_lines, processed_lines_count


def revise_patch(
    patch: str, project_path: str, revise_context: bool = False
) -> Tuple[str, bool]:
    """fix mistakes in generated patch.
    1. wrong line numbers.
    2. wrong format: not startswith ` `, `-` or `+`
    3. wrong context lines: a) wrong indention. b) wrong lines.

    Args:
        patch (str): patch to be revised.
        project_path (str): CVE project source code in local.
        revise_context (bool, optional): True means force to revise all context lines. Defaults to False.

    Returns:
        Tuple[str, bool]: revised patch and fix flag.
    """

    def revise_hunk(lines: list[str], target_file_lines: list[str]) -> tuple[str, bool]:
        """fix lines from "@@" to the end"""
        fixed = False
        # fix wrong line number
        if len(lines[-1]) == 0 or "\ No newline at end of file" in lines[-1]:
            lines = lines[:-1]
        orignal_line_number = sum(1 for line in lines[1:] if not line.startswith("+"))
        patched_line_number = sum(1 for line in lines[1:] if not line.startswith("-"))
        # @@ -3357,10 +3357,16 @@
        # extract the line number and the number of lines
        chunks = re.findall(r"@@ -(\d+),(\d+) \+(\d+),(\d+) @@(.*)", lines[0])[0]
        if chunks[0] != chunks[2]:
            fixed = True
        header = f"@@ -{chunks[0]},{orignal_line_number} +{chunks[2]},{patched_line_number} @@{chunks[4]}\n"

        # fix corrupt patch
        tmp_lines = []
        for line in lines[1:]:
            if line.startswith("+") or line.startswith("-") or line.startswith(" "):
                tmp_lines.append(line)
            else:
                tmp_lines.append(" " + line)

        # fix mismatched lines
        # force_flag: force to revise all mismatched lines, otherwise fix indentation only
        # TODO: if the distance is close, it should be revised
        # XXX: if the distance is far, it should not be revised
        contexts, num_context = extract_context(tmp_lines)
        lineno, _ = find_most_similar_block(contexts, target_file_lines, num_context)
        ctx_window = target_file_lines[
            max(0, lineno - 3) : min(
                lineno + num_context + 1, len(target_file_lines) - 1
            )
        ]

        revised_lines = []
        for line in tmp_lines:
            if line.startswith(" ") or line.startswith("-"):
                sign = line[0]
                lineno, _ = find_most_similar_block(
                    [line[1:]],
                    ctx_window,
                    1,
                )
                new_line = ctx_window[lineno - 1]
                if revise_context:
                    revised_lines.append(sign + new_line.strip("\n"))
                elif line[1:].strip() == new_line.strip():
                    revised_lines.append(sign + new_line.strip("\n"))
                else:
                    revised_lines.append(line)
            else:
                revised_lines.append(line.replace("'s", "->"))

        return header + "\n".join(revised_lines), fixed

    def revise_block(lines: list[str]) -> tuple[list[str], bool]:
        """fix "--- a/" and "+++ b/", and call revise_hunk."""
        try:
            file_path_a = re.findall(r"--- a/(.*)", lines[0])[0]
            fixed_file_path_a = os.path.normpath(file_path_a)
        except:
            file_path_a = fixed_file_path_a = lines[0]

        try:
            file_path_b = re.findall(r"\+\+\+ b/(.*)", lines[1])[0]
            fixed_file_path_b = os.path.normpath(file_path_b)
        except:
            file_path_b = fixed_file_path_b = lines[1]

        block_fixed = (
            file_path_a != fixed_file_path_a or file_path_b != fixed_file_path_b
        )
        assert (
            (file_path_a == file_path_b and fixed_file_path_a == fixed_file_path_b)
            or fixed_file_path_a == "--- /dev/null"
            or fixed_file_path_b == "--- /dev/null"
        )

        fixed_lines = [
            f"--- a/{fixed_file_path_a}".replace("a/--- ", ""),
            f"+++ b/{fixed_file_path_b}".replace("b/--- ", ""),
        ]
        try:
            with open(os.path.join(project_path, file_path_a), "r") as f:
                file_content = [line.rstrip("\n") for line in f]
        except:
            # do not revise patch if file changed, handle changed file in `_apply_hunk`
            return lines, False

        last_line = -1
        for line_no in range(2, len(lines)):
            if lines[line_no].startswith("@@"):
                if last_line != -1:
                    hunk_lines, hunk_fixed = revise_hunk(
                        lines[last_line:line_no], file_content
                    )
                    fixed_lines.append(hunk_lines)
                    block_fixed = block_fixed or hunk_fixed
                last_line = line_no
        if last_line != -1:
            hunk_lines, hunk_fixed = revise_hunk(lines[last_line:], file_content)
            fixed_lines.append(hunk_lines)
            block_fixed = block_fixed or hunk_fixed

        return fixed_lines, block_fixed

    try:
        lines = patch.splitlines()
        fixed_lines = []

        last_line = -1
        fixed = False
        for line_no in range(len(lines)):
            if lines[line_no].startswith("--- a/") or lines[line_no].startswith(
                "--- /dev/null"
            ):
                if last_line != -1:
                    block_lines, block_fixed = revise_block(lines[last_line:line_no])
                    fixed_lines += block_lines
                    fixed = fixed or block_fixed
                last_line = line_no
        if last_line != -1:
            block_lines, block_fixed = revise_block(lines[last_line:])
            fixed_lines += block_lines
            fixed = fixed or block_fixed

        return "\n".join(fixed_lines) + "\n", fixed
    except Exception as e:
        logger.debug("Failed to revise patch")
        logger.debug(e)
        logger.warning("".join(traceback.TracebackException.from_exception(e).format()))
        return patch, False


def split_patch(patch: str, flag_commit: bool) -> Generator[str, None, None]:
    """
    Split a patch into individual blocks.

    Args:
        patch (str): The patch to be split.
        flag_commit (bool): Whether the patch exists commit message.

    Yields:
        str: Each individual block of the patch.

    Returns:
        None
    """

    def split_block(lines: list[str]):
        file_path_line_a = lines[0]
        file_path_line_b = lines[1]
        last_line = -1
        for line_no in range(2, len(lines)):
            if lines[line_no].startswith("@@"):
                if last_line != -1:
                    content = (
                        file_path_line_a
                        + "\n"
                        + file_path_line_b
                        + "\n"
                        + "\n".join(lines[last_line:line_no])
                    )
                    yield content
                last_line = line_no
        if last_line != -1:
            content = (
                file_path_line_a
                + "\n"
                + file_path_line_b
                + "\n"
                + "\n".join(lines[last_line:])
            )
            yield content

    try:
        lines = patch.splitlines()
        message = ""
        last_line = -1
        for line_no in range(len(lines)):
            if lines[line_no].startswith("--- a/"):
                if last_line >= 0:
                    if flag_commit:
                        for x in split_block(lines[last_line : line_no - 2]):
                            yield message + x
                    else:
                        for x in split_block(lines[last_line:line_no]):
                            yield message + x
                if last_line == -1 and flag_commit:
                    message = "\n".join(lines[: max(line_no - 2, 0)])
                if any(
                    lines[line_no].endswith(blacklist_item)
                    for blacklist_item in blacklist
                ):
                    last_line = -2
                else:
                    last_line = line_no
            if lines[line_no].startswith("--- /dev/null"):
                if last_line >= 0:
                    if flag_commit:
                        for x in split_block(lines[last_line : line_no - 3]):
                            yield message + x
                    else:
                        for x in split_block(lines[last_line:line_no]):
                            yield message + x
                if last_line == -1 and flag_commit:
                    message = "\n".join(lines[: max(line_no - 3, 0)])
                if any(
                    lines[line_no + 1].endswith(blacklist_item)
                    for blacklist_item in blacklist
                ):
                    last_line = -2
                else:
                    last_line = line_no
        if last_line >= 0:
            for x in split_block(lines[last_line:]):
                yield message + x

    except Exception as e:
        logger.debug("Failed to split patch")
        logger.debug(e)
        logger.warning("".join(traceback.TracebackException.from_exception(e).format()))
        return None
