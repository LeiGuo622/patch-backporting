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
    code_snippet: str, lines: List[str], snippet_num: int
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
    best_start_index = -1

    for i in range(len(lines) - snippet_num + 1):
        combined = "\n".join(lines[i : i + snippet_num])

        distance = Levenshtein.distance(combined, code_snippet)
        if distance < min_distance:
            min_distance = distance
            best_start_index = i + 1

    return best_start_index, min_distance


def process_string(input_string: str) -> Tuple[str, int]:
    """
    Process the input string by removing certain lines and returning the processed string and the count of processed lines.

    Args:
        input_string (str): The input string to be processed.

    Returns:
        tuple[str, int]: A tuple containing the processed string and the count of processed lines.
    """
    lines = input_string.split("\n")
    processed_lines = []

    for line in lines[3:-1]:
        if line.startswith(" "):
            processed_lines.append(line[1:])
        elif line.startswith("-"):
            processed_lines.append(line[1:])
        elif line.startswith("+"):
            continue
        else:
            processed_lines.append(line)

    processed_lines_count = len(processed_lines)

    return processed_lines, processed_lines_count


def find_sub_list(lst: List, needle: List) -> List[int]:
    """
    Find all occurrences of a sublist in a given list using the Knuth-Morris-Pratt (KMP) algorithm.

    Args:
        lst (list): The list to search in.
        neddle (list): The sublist to find.

    Returns:
        list: A list of indices where the sublist is found in the main list.
    """
    match_pos = []

    def get_next(p):
        next = [0] * len(p)
        for i in range(1, len(p)):
            j = next[i - 1]
            while j > 0 and p[i] != p[j]:
                j = next[j - 1]
            if p[i] == p[j]:
                j += 1
            next[i] = j
        return next

    next = get_next(needle)
    i = 0
    j = 0
    while i < len(lst):
        if lst[i] == needle[j]:
            i += 1
            j += 1
            if j == len(needle):
                match_pos.append(i - j)
                j = next[j - 1]
        else:
            if j == 0:
                i += 1
            else:
                j = next[j - 1]
    return match_pos


def revise_patch(patch: str, project_path: str) -> Tuple[str, bool]:
    def revise_hunk(lines: list[str]) -> tuple[str, bool]:
        if len(lines[-1]) == 0 or "\ No newline at end of file" in lines[-1]:
            lines = lines[:-1]
        orignal_line_number = sum(1 for line in lines[1:] if not line.startswith("+"))
        patched_line_number = sum(1 for line in lines[1:] if not line.startswith("-"))
        # @@ -3357,10 +3357,16 @@
        # extract the line number and the number of lines
        chunks = re.findall(r"@@ -(\d+),(\d+) \+(\d+),(\d+) @@(.*)", lines[0])[0]
        if chunks[0] != chunks[2]:
            fixed = True
        orignal_content = []
        patched_content = []

        for line in lines[1:]:
            if line.startswith("-"):
                orignal_content.append(line[1:])
            elif line.startswith("+"):
                patched_content.append(line[1:])
            elif line.startswith(" "):
                orignal_content.append(line[1:])
                patched_content.append(line[1:])

        hunk = "\n".join(lines[1:])

        header = f"@@ -{chunks[0]},{orignal_line_number} +{chunks[2]},{patched_line_number} @@{chunks[4]}\n"

        fixed = True
        return header + hunk, fixed

    def revise_block(lines: list[str]) -> tuple[list[str], bool]:
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

        last_line = -1
        for line_no in range(2, len(lines)):
            if lines[line_no].startswith("@@"):
                if last_line != -1:
                    hunk_lines, hunk_fixed = revise_hunk(lines[last_line:line_no])
                    fixed_lines.append(hunk_lines)
                    block_fixed = block_fixed or hunk_fixed
                last_line = line_no
        if last_line != -1:
            hunk_lines, hunk_fixed = revise_hunk(lines[last_line:])
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
