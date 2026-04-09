#!/usr/bin/env python3
"""
Architecture Support Analyzer

Analyzes a kernel patch to determine if it modifies architecture-specific code
that is supported by the downstream kernel.
"""

import re
import sys
import subprocess
from pathlib import Path
from typing import Set, List


class ArchAnalyzer:
    """Analyzer for architecture-specific code changes"""

    # Supported architectures in the downstream kernel
    SUPPORTED_ARCHS = {
        'arm',       # ARM 32-bit
        'arm64',     # ARM 64-bit
        'x86',       # x86 (includes both i386 and x86_64)
        'riscv',     # RISC-V
        'loongarch', # LoongArch
        'powerpc',   # PowerPC
        'sw_64',     # SW-64 (might be downstream-specific)
    }

    def __init__(self, kernel_dir: str):
        self.kernel_dir = Path(kernel_dir).resolve()
        if not self.kernel_dir.exists():
            raise ValueError(f"Kernel directory not found: {kernel_dir}")

    def get_patch_files(self, commit_id: str) -> List[str]:
        """
        Get list of files modified by a commit
        Returns list of file paths
        """
        try:
            result = subprocess.run(
                ['git', 'show', '--name-only', '--pretty=format:', commit_id],
                cwd=self.kernel_dir,
                capture_output=True,
                text=True,
                timeout=10
            )

            if result.returncode != 0:
                return []

            # Filter out empty lines
            files = [f.strip() for f in result.stdout.splitlines() if f.strip()]
            return files

        except (subprocess.TimeoutExpired, FileNotFoundError):
            return []

    def get_arch_from_path(self, file_path: str) -> str:
        """
        Extract architecture name from file path
        Returns the architecture name if the file is under arch/, None otherwise
        """
        # Check if file is under arch/ directory
        if file_path.startswith('arch/'):
            # Extract architecture name
            # Format: arch/<arch_name>/...
            match = re.match(r'arch/([^/]+)', file_path)
            if match:
                return match.group(1)

        return None

    def has_arch_specific_changes(self, commit_id: str) -> bool:
        """
        Check if the commit modifies any architecture-specific code
        Returns True if there are arch/ directory changes
        """
        files = self.get_patch_files(commit_id)

        for file_path in files:
            arch = self.get_arch_from_path(file_path)
            if arch:
                return True

        return False

    def is_supported_arch(self, arch: str) -> bool:
        """
        Check if an architecture is supported
        Returns True if arch is in SUPPORTED_ARCHS
        """
        # Normalize architecture name
        arch_lower = arch.lower()

        # Check if it's a supported architecture
        return arch_lower in self.SUPPORTED_ARCHS

    def analyze(self, commit_id: str) -> dict:
        """
        Analyze a commit to check if it modifies only supported architectures
        Returns a dict with analysis results
        """
        files = self.get_patch_files(commit_id)

        if not files:
            return {
                'success': False,
                'error': 'Could not retrieve file list from commit'
            }

        # Find all architecture-specific changes
        arch_changes = []
        for file_path in files:
            arch = self.get_arch_from_path(file_path)
            if arch:
                arch_changes.append({
                    'file': file_path,
                    'arch': arch,
                    'supported': self.is_supported_arch(arch)
                })

        # Determine if all arch changes are supported
        all_supported = True
        unsupported_archs = set()

        for change in arch_changes:
            if not change['supported']:
                all_supported = False
                unsupported_archs.add(change['arch'])

        # If there are no arch-specific changes, it's automatically supported
        if not arch_changes:
            return {
                'success': True,
                'has_arch_changes': False,
                'all_supported': True,
                'arch_changes': [],
                'message': 'No architecture-specific changes found'
            }

        return {
            'success': True,
            'has_arch_changes': True,
            'all_supported': all_supported,
            'arch_changes': arch_changes,
            'unsupported_archs': list(unsupported_archs),
            'message': f'Found {len(arch_changes)} arch-specific change(s) to {len(set(c["arch"] for c in arch_changes))} architecture(s)'
        }

    def should_backport(self, commit_id: str) -> bool:
        """
        Quick check to determine if the commit should be backported
        Returns True if:
        - No arch-specific changes, OR
        - All arch changes are to supported architectures
        Returns False if any arch change is to an unsupported architecture
        """
        result = self.analyze(commit_id)
        return result.get('all_supported', True)


def main():
    """Main entry point for standalone testing"""
    if len(sys.argv) < 2:
        print("Usage: judge_arch.py <commit-id> [kernel-source-dir]")
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
        analyzer = ArchAnalyzer(str(kernel_dir))
        result = analyzer.analyze(commit_id)

        if not result['success']:
            print(f"Error: {result.get('error', 'Unknown error')}")
            sys.exit(1)

        # Print results
        print(f"Architecture analysis for commit: {commit_id}")
        print(f"Message: {result.get('message', 'N/A')}")

        if result['arch_changes']:
            print("\nArchitecture-specific changes:")
            for change in result['arch_changes']:
                status = "✓" if change['supported'] else "✗"
                print(f"  {status} {change['file']} (arch: {change['arch']})")

            if result.get('unsupported_archs'):
                print(f"\nUnsupported architectures: {', '.join(result['unsupported_archs'])}")

        print(f"\nShould backport: {result['all_supported']}")

        # Exit with appropriate code
        sys.exit(0 if result['all_supported'] else 1)

    except Exception as e:
        print(f"Error: {e}", file=sys.stderr)
        sys.exit(1)


if __name__ == "__main__":
    main()