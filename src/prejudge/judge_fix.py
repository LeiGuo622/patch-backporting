#!/usr/bin/env python3
"""
Fix Commit Analyzer

Analyzes a kernel commit to extract the fix tag (introducing commit)
and checks if that commit exists in the target project's OLK-6.6 branch.
"""

import re
import sys
import subprocess
from pathlib import Path
from typing import Set


class FixCommitAnalyzer:
    """Analyzer for fix commits in kernel patches"""

    def __init__(self, src_project_dir: str, target_project_dir: str):
        self.src_project_dir = Path(src_project_dir).resolve()
        self.target_project_dir = Path(target_project_dir).resolve()

        if not self.src_project_dir.exists():
            raise ValueError(f"Source project directory not found: {src_project_dir}")
        if not self.target_project_dir.exists():
            raise ValueError(f"Target project directory not found: {target_project_dir}")

    def get_commit_message(self, commit_id: str) -> str:
        """
        Get commit message from a commit using git log
        Returns the commit message as string
        """
        try:
            result = subprocess.run(
                ['git', 'log', '-1', '--pretty=%B', commit_id],
                cwd=self.src_project_dir,
                capture_output=True,
                text=True,
                timeout=10
            )

            if result.returncode != 0:
                return ""

            return result.stdout.strip()
        except (subprocess.TimeoutExpired, FileNotFoundError):
            return ""

    def extract_fix_commits(self, commit_message: str) -> Set[str]:
        """
        Extract fix commit IDs from commit message
        Looks for patterns like:
        - Fixes: <commit-id> ("description")
        - Fix: <commit-id>
        - Cc: <commit-id>
        etc.
        """
        fix_commits = set()

        # Common patterns for fix tags
        patterns = [
            r'Fixes:\s+([0-9a-f]{7,40})',
            r'Fix:\s+([0-9a-f]{7,40})',
            r'fixes:\s+([0-9a-f]{7,40})',
            r'fix:\s+([0-9a-f]{7,40})',
            r'Commit:\s+([0-9a-f]{7,40})',
            r'commit:\s+([0-9a-f]{7,40})',
        ]

        for pattern in patterns:
            matches = re.findall(pattern, commit_message)
            fix_commits.update(matches)

        return fix_commits

    def check_commit_in_branch(self, commit_id: str, branch: str = "OLK-6.6") -> bool:
        """
        Check if a commit exists in the target project's specific branch
        Returns True if commit exists, False otherwise
        """
        try:
            # First, try to check if commit exists in the repository
            result = subprocess.run(
                ['git', 'cat-file', '-e', commit_id],
                cwd=self.target_project_dir,
                capture_output=True,
                timeout=10
            )

            if result.returncode != 0:
                # Commit doesn't exist in the repository at all
                return False

            # Check if the commit is reachable from the specified branch
            result = subprocess.run(
                ['git', 'branch', '--contains', commit_id],
                cwd=self.target_project_dir,
                capture_output=True,
                text=True,
                timeout=10
            )

            if result.returncode != 0:
                return False

            # Check if the branch name is in the output
            branches = result.stdout
            return branch in branches

        except (subprocess.TimeoutExpired, FileNotFoundError):
            return False

    def check_commit_exists(self, commit_id: str) -> bool:
        """
        Check if a commit exists anywhere in the target project
        Returns True if commit exists, False otherwise
        """
        try:
            result = subprocess.run(
                ['git', 'cat-file', '-e', commit_id],
                cwd=self.target_project_dir,
                capture_output=True,
                timeout=10
            )

            return result.returncode == 0
        except (subprocess.TimeoutExpired, FileNotFoundError):
            return False

    def analyze(self, commit_id: str) -> dict:
        """
        Analyze a commit to check if its fix commits exist in the target project
        Returns a dict with analysis results
        """
        # Get commit message
        commit_message = self.get_commit_message(commit_id)
        if not commit_message:
            return {
                'success': False,
                'error': 'Could not retrieve commit message'
            }

        # Extract fix commits
        fix_commits = self.extract_fix_commits(commit_message)
        if not fix_commits:
            return {
                'success': True,
                'fix_commits': [],
                'all_exist': True,  # No fix commits means no dependency
                'message': 'No fix commits found in commit message'
            }

        # Check each fix commit
        results = []
        all_exist = True
        for fix_commit in fix_commits:
            exists = self.check_commit_exists(fix_commit)
            exists_in_olk = self.check_commit_in_branch(fix_commit)

            results.append({
                'commit_id': fix_commit,
                'exists_in_repo': exists,
                'exists_in_olk_6_6': exists_in_olk
            })

            if not exists:
                all_exist = False

        return {
            'success': True,
            'fix_commits': results,
            'all_exist': all_exist,
            'message': f'Found {len(fix_commits)} fix commit(s)'
        }

    def should_proceed(self, commit_id: str) -> bool:
        """
        Quick check to determine if we should proceed with config judgment
        Returns True if all fix commits exist in target project, False otherwise
        """
        result = self.analyze(commit_id)
        return result.get('all_exist', True)


def main():
    """Main entry point for standalone testing"""
    if len(sys.argv) < 3:
        print("Usage: judge_fix.py <commit-id> <src-project-dir> <target-project-dir>", file=sys.stderr)
        sys.exit(1)

    commit_id = sys.argv[1]
    src_project_dir = sys.argv[2]
    target_project_dir = sys.argv[3]

    try:
        analyzer = FixCommitAnalyzer(src_project_dir, target_project_dir)
        result = analyzer.analyze(commit_id)

        if not result['success']:
            print(f"Error: {result.get('error', 'Unknown error')}")
            sys.exit(1)

        # Print results
        print(f"Analysis for commit: {commit_id}")
        print(f"Message: {result.get('message', 'N/A')}")

        if result['fix_commits']:
            print("\nFix commits:")
            for fix in result['fix_commits']:
                status = "✓" if fix['exists_in_repo'] else "✗"
                print(f"  {status} {fix['commit_id']} - In repo: {fix['exists_in_repo']}, In OLK-6.6: {fix['exists_in_olk_6_6']}")

        print(f"\nShould proceed with config judgment: {result['all_exist']}")

        # Exit with appropriate code
        sys.exit(0 if result['all_exist'] else 1)

    except Exception as e:
        print(f"Error: {e}", file=sys.stderr)
        sys.exit(1)


if __name__ == "__main__":
    main()