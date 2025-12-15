import os
import re
import subprocess
import tempfile
from typing import List, Tuple

from git import Repo
from langchain_core.tools import tool

import tools.utils as utils
from tools.logger import logger


class Project:
    def __init__(self, project_url: str, dir: str, err_msg: str = "no err_msg"):
        self.project_url = project_url
        self.dir = dir
        self.repo = Repo(dir)
        self.err_msg = err_msg
        self.succeeded_patches = []
        self.round_succeeded = False
        self.all_hunks_applied_succeeded = False
        self.compile_succeeded = False
        self.testcase_succeeded = False
        self.poc_succeeded = False

    def _checkout(self, ref: str) -> None:
        self.repo.git.reset("--hard")
        self.repo.git.checkout(ref)

    def _get_patch(self, ref: str) -> str:
        try:
            return self.repo.git.show(f"{ref}^..{ref}")
        except:
            return "Error commit id, please check if the commit id is correct."

    def _prepare(self) -> None:
        """
        Prepares the project by generating a symbol map using ctags.

        Raises:
            subprocess.CalledProcessError: If the ctags command fails.
        """
        ctags = subprocess.run(
            ["ctags", "--excmd=number", "-R", "."],
            stdout=subprocess.PIPE,
            cwd=self.dir,
            stdin=subprocess.PIPE,
            stderr=subprocess.DEVNULL,
        )
        ctags.check_returncode()
        self.symbol_map = {}
        with open(os.path.join(self.dir, "tags"), "rb") as f:
            for line in f.readlines():
                if text := line.decode("utf-8", errors="ignore"):
                    if text.startswith("!_TAG_"):
                        continue
                    try:
                        symbol, file, lineno = text.strip().split(';"')[0].split("\t")
                        lineno = int(lineno)
                        if symbol not in self.symbol_map:
                            self.symbol_map[symbol] = []
                        self.symbol_map[symbol].append((file, lineno))
                    except:
                        continue

    def _viewcode(self, ref: str, path: str, startline: int, endline: int) -> str:
        """
        View a file from a specific ref of the target repository. Lines between startline and endline are shown.

        Args:
            ref (str): The specific ref of the target repository.
            path (str): The path of the file to view.
            startline (int): The starting line number to display.
            endline (int): The ending line number to display.

        Returns:
            str: The content of the file between the specified startline and endline.
                 If the file doesn't exist in the commit, a message indicating that is returned.
        """
        try:
            file = self.repo.tree(ref) / path
        except:
            return "This file doesn't exist in this commit."
        content = file.data_stream.read().decode("utf-8")
        lines = content.split("\n")
        ret = []
        endline = min(endline, len(lines))
        for i in range(startline - 1, endline):
            ret.append(lines[i])
        return "\n".join(ret)

    def _locate_symbol(self, ref: str, symbol: str) -> List[Tuple[str, int]] | None:
        """
        Locate a symbol in a specific ref of the target repository.

        Args:
            ref (str): The reference of the target repository.
            symbol (str): The symbol to locate.

        Returns:
            List[Tuple[str, int]] | None: File path and code lines.
        """
        # XXX: Analyzing ctags file everytime locate symbol is time-consuming.
        self._checkout(ref)
        self._prepare()
        if symbol in self.symbol_map:
            return self.symbol_map[symbol]
        else:
            return None

    def _apply_error_handling(self, ref: str, revised_patch: str) -> Tuple[str, str]:
        """
        Generate feedback to llm when an error patch is applied.

        Args:
            ref (str): The reference of the target repository.
            revised_patch (str): The patch to be applied.

        Returns:
            Tuple[str, str]: Bug patch similar code block information and difference between patch context and original code context.

        """
        path = re.findall(r"--- a/(.*)", revised_patch)[0]
        revised_patch_line = revised_patch.split("\n")
        revised_patch_line = [s[1:] for s in revised_patch_line]
        file = self.repo.tree(ref) / path
        content = file.data_stream.read().decode("utf-8")
        lines = content.split("\n")

        contexts, num_context = utils.process_string(revised_patch)
        lineno = utils.find_most_similar_block("\n".join(contexts), lines, num_context)

        startline = max(lineno - 1, 0)
        endline = min(lineno + 5 + num_context, len(lines))
        block = "Here are lines {} through {} of file {} for commit {}.\n".format(
            startline, endline, path, ref
        )
        block += "```code snippet\n"
        for i in range(startline, endline):
            block = block + lines[i] + "\n"
        block += "```\n"

        differ = "```context diff\n"
        for i, context in enumerate(contexts):
            if context != lines[lineno - 1 + i]:
                try:
                    patch_lineno = revised_patch_line.index(context) + 1
                    differ += f"On the line {patch_lineno} of your patch. There is a slight difference between patch and the source code.\n"
                    differ += f"          Your patch:{context}\n"
                    differ += f"Original source code:{lines[lineno - 1 + i]}\n"
                except:
                    patch_lineno = revised_patch_line.index(context[1:]) + 1
                    differ += f"On the line {patch_lineno} of your patch. There is an error caused by your line doesn't start with ` `(space).\n"
                    differ += f"Your patch:{context}\n"
        if differ == "```context diff\n":
            differ = "Here it shows that there is no difference between your context and the original code, the reason for the failure is that you didn't keep at least three lines of source code at the beginning and end of the patch, please follow this to fix it.\n"
        else:
            differ += "```\nREMEMBER For these lines you need to keep it start with `-` and ` ` (space) first, and then you need to copy the original source code behind it and use tab indentation. Please eliminate these diffs step by step. Be sure to eliminate these diffs the next time you generate a patch!\n"
        return block, differ

    def _apply_file_move_handling(self, ref: str, old_patch: str) -> str:
        """
        If a patch cannot apply for "No such file", try to find the symbol and apply the patch to the correct file.

        Args:
            ref (str): The reference string.
            old_patch (str): The patch that raises "No such file" when apply.

        Returns:
            str: If the symbol is found, a message indicating the current file path.

        Raises:
            SystemExit: If the symbol or file cannot be found or the patch cannot be applied directly.

        """
        ret = ""
        missing_file_path = re.findall(r"--- a/(.*)", old_patch)[0]
        # @@ -135,7 +135,6 @@ struct ksmbd_transport_ops {
        # @@ -416,13 +416,7 @@ static void stop_sessions(void)
        symbol_name = re.findall(r"\b\w+(?=\s*[{\(])", old_patch)[0]
        symbol_locations = self._locate_symbol(ref, symbol_name)

        if not symbol_locations:
            logger.debug(f"No {missing_file_path} and no {symbol_name}() in the repo.")
            # TODO: return what to LLM
            # can not find symbol, the symbol is renamed or removed
            exit(1)
        else:
            logger.debug(f"Find {symbol_name} in {symbol_locations}.")
            find_file = False
            for item in symbol_locations:
                file_path = item[0]
                new_patch = old_patch.replace(missing_file_path, file_path)
                if "successfully" in self._apply_hunk(ref, new_patch):
                    find_file = True
                    logger.debug(f"{missing_file_path} has been moved to {file_path}.")
                    ret += f"{missing_file_path} has been moved to {file_path}. Please use --- a/{file_path} in your patch.\n"
                    break
            if not find_file:
                logger.debug(f"Patch can not be applied to {symbol_locations}.")
                # TODO: return what to LLM
                # find symbol, but patch can not apply directly
                exit(1)
        return ret

    def _apply_hunk(self, ref: str, patch: str) -> str:
        """
        Apply a hunk to a specific ref of the target repository.

        Args:
            ref (str): The reference of the target repository.
            patch (str): The patch to be applied.

        Returns:
            str: A string indicating the result of the patch application.

        Raises:
            Exception: If the patch fails to apply.

        """
        ret = ""
        self._checkout(ref)
        self.repo.git.reset("--hard")
        revised_patch, fixed = utils.revise_patch(patch, self.dir)
        with tempfile.NamedTemporaryFile(mode="w", delete=False) as f:
            f.write(revised_patch)
        logger.debug("revised_patch")
        logger.debug(revised_patch)
        logger.debug(f"Applying patch {f.name}")
        try:
            self.repo.git.apply([f.name], v=True)
            ret += "Patch applied successfully\n"
            self.succeeded_patches.append(revised_patch)
            self.round_succeeded = True
        except Exception as e:
            logger.debug(f"{e.stderr}")
            if "No such file" in e.stderr:
                ret += self._apply_file_move_handling(ref, revised_patch)

            elif "patch does not apply" in e.stderr:
                ret += "This patch does not apply because of context mismatch, you CAN NOT send it to me again. Repeated patches will harm the lives of others.\n"
                ret += "Next I'll give you the context of the previous error patch in the old version, and you should modify the previous error patch according to this section.\n"
                block, differ = self._apply_error_handling(ref, revised_patch)
                ret += block
                ret += f"In addition to that, I've got more detailed error messages for you below where the context of your generated patch differs specifically from the source code context.\n"
                ret += differ
                ret += f"Based on the above feedback or use tools `locate_symbol` and `viewcode` to re-check patch-related code snippet. Please modify your patch so that the context in your patch is exactly the same as the source code, including the difference between SPACE and INDENTATION.\n"
                ret += "At tbe beginning and end of the hunk, MUST has at least 3 lines context. For lines that start with '-' and ' ', both need to be matched as context. You MUST never confuse '->' with ''s'.\n"

            elif "corrupt patch" in e.stderr:
                # TODO: return what to LLM
                # format error
                pass

        self.repo.git.reset("--hard")
        return ret

    def _compile_patch(self, ref: str, complete_patch: str) -> str:
        """
        If all hunks could be applied successfully, compiles the patched source code after applying the joined patch.

        Args:
            ref (str): The reference to checkout before applying the patch.
            complete_patch (str): The complete patch to be applied.

        Returns:
            str: A message indicating the result of the compilation process.

        Raises:
            subprocess.TimeoutExpired: If the compilation process times out.

        """
        # apply joined patch
        self._checkout(ref)
        ret = ""
        pps = utils.split_patch(complete_patch, False)
        for idx, pp in enumerate(pps):
            revised_patch, fixed = utils.revise_patch(pp, self.dir)
            with tempfile.NamedTemporaryFile(mode="w", delete=False) as f:
                f.write(revised_patch)
            try:
                self.repo.git.apply([f.name], v=True)
                logger.debug(
                    f"The joined patch hunk {idx} could be applied successfully, file {f.name}"
                )
            except Exception as e:
                logger.debug(
                    f"Failed to apply Complete patch hunk {idx}, file {f.name}"
                )
                # TODO: give feedback to LLM about which line can not be applied
                ret = f"For the patch you just generated, there was an APPLY failure during testing. Specifically there was a context mismatch in hunk {idx} across the patch, below is part of the feedback I found for you.\n"
                block, differ = self._apply_error_handling(ref, revised_patch)
                ret += block
                ret += f"Here is the source code near the hunk context for your reference, a good patch context should look exactly like the source code.\n"
                ret += f"In addition to that, I've got more detailed error messages for you below where the context of your generated patch differs specifically from the source code context.(The line numbers below are all line numbers in the hunk, not the entire patch.)\n"
                ret += differ
                ret += f"Based on the above feedback, MUST you please modify only hunk {idx} in the patch and leave the other hunks untouched so that the context present in hunk {idx} is exactly the same as the source code to guarantee that git apply can be executed normally.\n"
                self.repo.git.reset("--hard")
                return ret

        # compile the patch
        logger.debug("Start compile the patched source code")
        if not os.path.exists(os.path.join(self.dir, "build.sh")):
            logger.debug("No build.sh file found.")
            exit(1)

        build_process = subprocess.Popen(
            ["/bin/bash", "build.sh"],
            stdin=subprocess.DEVNULL,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            cwd=self.dir,
            text=True,
        )
        try:
            _, compile_result = build_process.communicate(timeout=60 * 60)
        except subprocess.TimeoutExpired:
            build_process.kill()
            ret += f"The compilation process of the patched source code is timeout. "
            self.repo.git.reset("--hard")
            return ret

        if build_process.returncode != 0:
            logger.info(f"Compilation                       FAILED")
            logger.debug(f"{compile_result}")
            ret += "The source code could not be COMPILED successfully after applying the patch. "
            ret += "Next I'll give you the error message during compiling, and you should modify the error patch. "
            ret += f"Here is the error message:\n{compile_result}\n"
            ret += "Please revise the patch with above error message. "
            ret += "Or use tools `locate_symbol` and `viewcode` to re-check patch-related code snippet. "
            ret += "Please DO NOT send the same patch to me, repeated patches will harm the lives of others.\n"
        else:
            logger.info(f"Compilation                       PASS")
            ret += "The patched source code could be COMPILED successfully! I really thank you for your great efforts.\n"
            self.compile_succeeded = True
        self.repo.git.reset("--hard")
        return ret

    def _run_testcase(self) -> str:
        """
        Runs the testcase after compiling a patch.

        Returns:
            str: A message indicating the result of the testcase process.
        """
        ret = ""
        logger.debug("Run testcase after compile")

        if not os.path.exists(os.path.join(self.dir, "test.sh")):
            logger.debug("No test.sh file found, considered as test passed.")
            self.testcase_succeeded = True
            ret += "The patched source code could pass TESTCASE! I really thank you for your great efforts.\n"
            return ret
        testcase_process = subprocess.Popen(
            ["/bin/bash", "test.sh"],
            stdin=subprocess.DEVNULL,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            cwd=self.dir,
            text=True,
        )

        try:
            _, testcase_result = testcase_process.communicate(timeout=60 * 30)
        except subprocess.TimeoutExpired:
            testcase_process.kill()
            ret += "The TESTCASE process of the patched source code is timeout. "
            return ret

        if testcase_process.returncode != 0:
            logger.info(f"Testsuite                         FAILED")
            logger.debug(f"{testcase_result}")
            ret = "The patched program could not pass the testcase. "
            ret += "Next I'll give you the error message during running the testcase, and you should modify the previous error patch according to this section. "
            ret += f"Here is the error message:\n{testcase_result}\n"
            ret += "Please revise the patch with above error message. "
            ret += "Or use tools `locate_symbol` and `viewcode` to re-check patch-related code snippet. "
            ret += "Please DO NOT send the same patch to me, repeated patches will harm the lives of others.\n"
            self.compile_succeeded = False
        else:
            logger.info(f"Testsuite                         PASS")
            ret += "The patched source code could pass TESTCASE! I really thank you for your great efforts.\n"
            self.testcase_succeeded = True
        return ret

    def _run_poc(self, complete_patch) -> str:
        """
        Runs the Proof of Concept (PoC) after running the testcase.

        Returns:
            str: A message indicating the result of the PoC process.
        """
        ret = ""
        logger.debug("Run PoC after compile and run testcase")

        if not os.path.exists(os.path.join(self.dir, "poc.sh")):
            logger.debug("No poc.sh file found, considered as PoC passed.")
            self.poc_succeeded = True
            ret += "Existing PoC could NOT TRIGGER the bug, which means your patch successfully fix the bug! I really thank you for your great efforts.\n"
            return ret
        poc_process = subprocess.Popen(
            ["/bin/bash", "poc.sh"],
            stdin=subprocess.DEVNULL,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            cwd=self.dir,
            text=True,
        )

        try:
            _, poc_result = poc_process.communicate(timeout=60 * 10)
        except subprocess.TimeoutExpired:
            poc_process.kill()
            ret += "The TESTCASE process of the patched source code is timeout. "
            return ret

        if self.err_msg in poc_result:
            logger.info(f"PoC test                          FAILED")
            logger.debug(f"returncode = {poc_process.returncode}")
            logger.debug(f"stderr: {poc_result}")
            ret += "Existing PoC could still trigger the bug, which means your patch fail to fix the bug. "
            ret += "Next I'll give you the error message during running the PoC, and you should modify the previous error patch according to this section. "
            ret += f"Here is the error message:\n{poc_result}\n"
            ret += "Please revise the patch with above error message. "
            ret += "Or use tools `locate_symbol` and `viewcode` to re-check patch-related code snippet. "
            ret += "Please DO NOT send the same patch to me, repeated patches will harm the lives of others.\n"
            self.compile_succeeded = False
            self.testcase_succeeded = False
        else:
            logger.info(f"PoC test                          PASS")
            ret += "Existing PoC could NOT TRIGGER the bug, which means your patch successfully fix the bug! I really thank you for your great efforts.\n"
            self.succeeded_patches.clear()
            self.succeeded_patches.append(complete_patch)
            self.poc_succeeded = True
        return ret

    def _validate(self, ref: str, patch: str) -> str:
        """
        Validates a patch by using the `_compile_patch`, `_run_testcase`, and `_run_poc` methods.

        Args:
            ref (str): The reference string.
            patch (str): The patch string.

        Returns:
            str: The validation result.

        """
        if self.all_hunks_applied_succeeded:
            ret = ""
            if not self.compile_succeeded:
                ret += self._compile_patch(ref, patch)
            if self.compile_succeeded and not self.testcase_succeeded:
                ret += self._run_testcase()
            if (
                self.compile_succeeded
                and self.testcase_succeeded
                and not self.poc_succeeded
            ):
                ret += self._run_poc(patch)
            return ret
        else:
            return self._apply_hunk(ref, patch)

    def get_tools(self):
        return (
            creat_viewcode_tool(self),
            creat_locate_symbol_tool(self),
            create_validate_tool(self),
        )


def creat_locate_symbol_tool(project: Project):
    @tool
    def locate_symbol(ref: str, symbol: str) -> str:
        """
        Locate a symbol in a specific ref of the target repository.
        """
        res = project._locate_symbol(ref, symbol)
        if res is not None:
            return "\n".join([f"{file}:{line}" for file, line in res])
        else:
            return "Symbol not found"

    return locate_symbol


def creat_viewcode_tool(project: Project):
    @tool
    def viewcode(ref: str, path: str, startline: int, endline: int) -> str:
        """
        View a file from a specific ref of the target repository. Lines between startline and endline are shown.
        """
        return project._viewcode(ref, path, startline, endline)

    return viewcode


def create_validate_tool(project: Project):
    @tool
    def validate(ref: str, patch: str) -> str:
        """
        validate a patch on a specific ref of the target repository.
        """
        return project._validate(ref, patch)

    return validate
