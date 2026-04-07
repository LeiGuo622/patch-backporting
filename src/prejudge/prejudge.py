#!/usr/bin/env python3
"""
Main Prejudge Controller

Analyzes a kernel commit to determine requirements for backporting.
This includes checking required CONFIG options and other validation criteria.
"""

import sys
import subprocess
from pathlib import Path
from typing import Dict, List, Set


class PrejudgeController:
    """Main controller for pre-judging kernel commits"""

    def __init__(self, kernel_dir: str):
        self.kernel_dir = Path(kernel_dir).resolve()
        if not self.kernel_dir.exists():
            raise ValueError(f"Kernel directory not found: {kernel_dir}")

    def get_patch_from_commit(self, commit_id: str) -> str:
        """
        Get patch content from a commit using git show
        Returns the patch content as string
        """
        try:
            result = subprocess.run(
                ['git', 'show', commit_id],
                cwd=self.kernel_dir,
                capture_output=True,
                text=True,
                timeout=10
            )

            if result.returncode != 0:
                return ""

            return result.stdout
        except (subprocess.TimeoutExpired, FileNotFoundError):
            return ""

    def save_patch_to_temp(self, patch_content: str) -> Path:
        """Save patch content to a temporary file"""
        import tempfile
        # Create a temporary file
        fd, temp_path = tempfile.mkstemp(suffix='.patch', text=True)
        try:
            with open(fd, 'w') as f:
                f.write(patch_content)
        except:
            Path(temp_path).unlink(missing_ok=True)
            raise

        return Path(temp_path)

    def judge_config(self, patch_content: str) -> Set[str]:
        """
        Judge required CONFIG options for the patch
        Returns set of CONFIG_XXX=y strings
        """
        from judge_config import PatchConfigAnalyzer

        try:
            # Save patch to temp file
            temp_patch = self.save_patch_to_temp(patch_content)

            # Analyze
            analyzer = PatchConfigAnalyzer(str(self.kernel_dir))
            configs = analyzer.analyze_patch(str(temp_patch))

            # Clean up temp file
            temp_patch.unlink(missing_ok=True)

            # Format as CONFIG_XXX=y
            return {f"{config}=y" for config in configs}

        except Exception:
            return set()

    def analyze_commit(self, commit_id: str) -> Dict[str, Set[str]]:
        """
        Analyze a commit and return all judgment results
        Returns a dict with keys like 'config', 'others', etc.
        """
        # Get patch from commit
        patch_content = self.get_patch_from_commit(commit_id)
        if not patch_content:
            return {}

        return patch_content
        
    def analyze_config(self, patch_content: str) -> Dict[str, Set[str]]:
        """
        Analyze the patch content for various judgments
        Returns a dict with judgment results
        """
        results = {}

        # Judge CONFIG requirements
        config_results = self.judge_config(patch_content)
        if config_results:
            results['config'] = config_results

        # Future judges can be added here:
        # - Judge required kernel version
        # - Judge dependencies on other commits
        # - Judge affected subsystems
        # etc.

        return results

    def check_config_in_arch_configs(self, configs: Set[str]) -> bool:
        """
        Check if any of the CONFIGs are enabled in any of the architecture configs.
        Returns True if at least one CONFIG is enabled (=y or =m) in any architecture.
        """
        if not configs:
            # No CONFIGs found, return True
            return True

        # Get the config_data directory
        script_dir = Path(__file__).parent
        config_data_dir = script_dir / "config_data"

        if not config_data_dir.exists():
            # If config_data doesn't exist, assume True
            return True

        # Architecture config files
        arch_configs = ['x86', 'arm64', 'riscv', 'powerpc', 'sw_64']

        # For each CONFIG, check if it's enabled in any architecture
        for config_str in configs:
            # Extract CONFIG name from format "CONFIG_XXX=y"
            config_name = config_str.split('=')[0]

            for arch in arch_configs:
                arch_config_file = config_data_dir / arch
                if not arch_config_file.exists():
                    continue

                try:
                    # Read the arch config file
                    with open(arch_config_file, 'r', encoding='utf-8', errors='ignore') as f:
                        for line in f:
                            line = line.strip()
                            # Check if this CONFIG is set to y or m (both will be compiled)
                            if line.startswith(f"{config_name}="):
                                # Extract the value
                                value = line.split('=', 1)[1]
                                if value in ['y', 'm']:
                                    # Found it enabled (built-in or module) in this architecture
                                    return True
                except Exception:
                    continue

        # None of the CONFIGs are enabled in any architecture
        return False

    def analyze_and_report(self, commit_id: str) -> None:
        """
        Analyze a commit and print results
        Output format: true or false
        """
        patch_content = self.analyze_commit(commit_id)

        if not patch_content:
            # No patch content, return True
            print("Error: Could not retrieve patch content. Please check the commit ID and repository.")
            return
        
        results = self.analyze_config(patch_content)

        # Check if any CONFIG is enabled in any architecture
        all_configs = set()
        for items in results.values():
            all_configs.update(items)

        is_enabled = self.check_config_in_arch_configs(all_configs)
        print("true" if is_enabled else "false")


def main():
    if len(sys.argv) < 2:
        print("Usage: prejudge.py <commit-id> [kernel-source-dir]")
        sys.exit(1)

    commit_id = sys.argv[1]

    # Default kernel directory
    if len(sys.argv) >= 3:
        kernel_dir = sys.argv[2]
    else:
        # Try to find kernel directory
        script_dir = Path(__file__).parent.parent.parent
        kernel_dir = script_dir / "data" / "linux"

    try:
        controller = PrejudgeController(kernel_dir)
        controller.analyze_and_report(commit_id)
    except Exception:
        sys.exit(1)


if __name__ == "__main__":
    main()
