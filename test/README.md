# Test Directory

This directory contains test scripts and data for batch testing the prejudge functionality.

## test_prejudge.py

Batch test script that reads CVE commits from a CSV file, runs prejudge analysis on each commit, and outputs results to a new CSV file.

### Usage

```bash
python test_prejudge.py <input-csv-path> <output-csv-path> <kernel-dir> <target-project-dir>
```

### Arguments

- `input-csv-path`: Path to input CSV file with columns: CVE-ID, Mainline_Commit, Status
- `output-csv-path`: Path to output CSV file (will include original columns + Prejudge_Result)
- `kernel-dir`: Path to kernel source directory (e.g., data/linux)
- `target-project-dir`: Path to target project directory (e.g., data/kernel)

### Example

```bash
python test_prejudge.py test.csv test_results.csv data/linux data/kernel
```

### Input CSV Format

The input CSV should have the following columns:
- `CVE-ID`: CVE identifier (e.g., CVE-2025-68325)
- `Mainline_Commit`: Git commit hash from mainline kernel
- `Status`: Current status (e.g., undefined)

### Output CSV Format

The output CSV includes all input columns plus:
- `Prejudge_Result`: Result from prejudge analysis (true/false with reason)

### Example Output

```
CVE-ID,Mainline_Commit,Status,Prejudge_Result
CVE-2025-68325,9fefc78f7f02d71810776fdeb119a05a946a27cc,undefined,"false, fix commits missing"
CVE-2025-68761,c105e76bb17cf4b55fe89c6ad4f6a0e3972b5b08,undefined,"false, fix commits missing"
CVE-2025-68751,14e4e4175b64dd9216b522f6ece8af6997d063b2,undefined,"false, config not enabled"
```

## test.csv

Sample input CSV file with three example CVE commits for testing purposes.