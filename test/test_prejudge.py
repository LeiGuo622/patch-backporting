#!/usr/bin/env python3
"""
Batch test script for prejudge functionality.

Reads CVE commits from a CSV file, runs prejudge on each commit,
and outputs results to a new CSV file with original content plus prejudge results.
"""

import sys
import csv
from pathlib import Path

# Add src directory to path to import prejudge module
sys.path.insert(0, str(Path(__file__).parent.parent / "src" / "prejudge"))

from prejudge import PrejudgeController


def process_cve_csv(input_csv_path: str, output_csv_path: str,
                    kernel_dir: str, target_project_dir: str):
    """
    Process CVE commits from input CSV and write results to output CSV.

    Args:
        input_csv_path: Path to input CSV file with columns: CVE-ID, Mainline_Commit, Status
        output_csv_path: Path to output CSV file (will include original columns + Prejudge_Result)
        kernel_dir: Path to kernel source directory (data/linux)
        target_project_dir: Path to target project directory (data/kernel)
    """
    # Validate input file exists
    input_path = Path(input_csv_path)
    if not input_path.exists():
        print(f"Error: Input CSV file not found: {input_csv_path}")
        sys.exit(1)

    # Validate directories exist
    kernel_path = Path(kernel_dir)
    if not kernel_path.exists():
        print(f"Error: Kernel directory not found: {kernel_dir}")
        sys.exit(1)

    target_path = Path(target_project_dir)
    if not target_path.exists():
        print(f"Error: Target project directory not found: {target_project_dir}")
        sys.exit(1)

    # Initialize prejudge controller
    try:
        controller = PrejudgeController(kernel_dir, target_project_dir)
    except Exception as e:
        print(f"Error initializing PrejudgeController: {e}")
        sys.exit(1)

    # Read input CSV
    results = []
    with open(input_path, 'r', encoding='utf-8') as f:
        reader = csv.DictReader(f)
        fieldnames = reader.fieldnames + ['Prejudge_Result']

        for row in reader:
            cve_id = row['CVE-ID']
            commit_id = row['Mainline_Commit']
            status = row['Status']

            print(f"Processing {cve_id} (commit: {commit_id})...")

            # Run prejudge analysis
            try:
                # Capture the output from analyze_and_report
                from io import StringIO
                import sys

                # Capture stdout
                old_stdout = sys.stdout
                sys.stdout = captured_output = StringIO()

                controller.analyze_and_report(commit_id)

                # Restore stdout
                sys.stdout = old_stdout
                prejudge_result = captured_output.getvalue().strip()

            except Exception as e:
                prejudge_result = f"Error: {str(e)}"
                print(f"  Error: {e}")

            print(f"  Result: {prejudge_result}")

            # Add result to row
            row['Prejudge_Result'] = prejudge_result
            results.append(row)

    # Write output CSV
    output_path = Path(output_csv_path)
    with open(output_path, 'w', encoding='utf-8', newline='') as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(results)

    print(f"\nResults written to: {output_csv_path}")


def main():
    if len(sys.argv) != 5:
        print("Usage: test_prejudge.py <input-csv-path> <output-csv-path> <kernel-dir> <target-project-dir>")
        print("\nExample:")
        print("  python test_prejudge.py test.csv test_results.csv data/linux data/kernel")
        sys.exit(1)

    input_csv = sys.argv[1]
    output_csv = sys.argv[2]
    kernel_dir = sys.argv[3]
    target_project_dir = sys.argv[4]

    process_cve_csv(input_csv, output_csv, kernel_dir, target_project_dir)


if __name__ == "__main__":
    main()