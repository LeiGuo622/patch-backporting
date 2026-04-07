#!/usr/bin/env python3
"""
Patch Kconfig Dependency Analyzer

Analyzes a kernel patch to determine which CONFIG options need to be enabled
for the patched code to be compiled into vmlinux.
"""

import re
import sys
from pathlib import Path
from typing import Dict, Set, List, Tuple
from collections import defaultdict

try:
    import kconfiglib
except ImportError:
    print("Error: kconfiglib is required. Install with: pip install kconfiglib", file=sys.stderr)
    sys.exit(1)


class PatchParser:
    """Parse kernel patch files to extract modified lines"""

    def __init__(self, patch_content: str):
        self.patch_content = patch_content
        self.files_changed: Dict[str, Set[int]] = {}

    def parse(self) -> Dict[str, Set[int]]:
        """Extract added lines per file from the patch"""
        current_file = None
        new_line_num = 0

        for line in self.patch_content.splitlines():
            # Track which file we're modifying
            if line.startswith("+++ b/"):
                current_file = line[6:]
                self.files_changed[current_file] = set()
                new_line_num = 0

            # Parse hunk headers to get line numbers
            elif line.startswith("@@"):
                # Format: @@ -old_start,old_count +new_start,new_count @@
                match = re.search(r'\+(\d+)', line)
                if match:
                    new_line_num = int(match.group(1))

            # Track added lines (lines starting with + but not +++ which is file header)
            elif line.startswith("+") and not line.startswith("+++"):
                if current_file:
                    self.files_changed[current_file].add(new_line_num)
                    new_line_num += 1

            # Track context lines (not removed)
            elif not line.startswith("-"):
                new_line_num += 1

        return self.files_changed


class PreprocessorConditionTracker:
    """Track preprocessor conditional nesting in C code"""

    def __init__(self):
        self.condition_stack: List[str] = []
        self.line_to_conditions: Dict[int, List[str]] = defaultdict(list)

    def process_line(self, line: str, source_line: int = None):
        """Process a preprocessed line, tracking conditionals"""
        line = line.strip()

        # Handle conditional directives
        if line.startswith("#if"):
            self.condition_stack.append(line)
        elif line.startswith("#elif"):
            if self.condition_stack:
                self.condition_stack.pop()
            self.condition_stack.append(line.replace("elif", "if"))
        elif line.startswith("#else"):
            if self.condition_stack:
                last = self.condition_stack.pop()
                # Negate the last condition for else branch
                cond = last[3:].strip()  # Remove "#if "
                self.condition_stack.append(f"!({cond})")
        elif line.startswith("#endif"):
            if self.condition_stack:
                self.condition_stack.pop()

        # Track source line mapping
        elif source_line is not None:
            if line.startswith("#line"):
                match = re.search(r'#line (\d+)', line)
                if match:
                    source_line = int(match.group(1))
            else:
                # Associate current conditions with this source line
                if self.condition_stack:
                    self.line_to_conditions[source_line] = self.condition_stack.copy()
                source_line += 1

    def get_conditions_for_line(self, line_num: int) -> List[str]:
        """Get all preprocessor conditions for a given source line"""
        return self.line_to_conditions.get(line_num, [])


class SourceAnalyzer:
    """Analyze kernel source code to extract CONFIG dependencies"""

    def __init__(self, kernel_dir: str):
        # Convert to absolute path
        self.kernel_dir = Path(kernel_dir).resolve()

    def extract_config_from_makefile(self, source_file: str) -> Set[str]:
        """Extract CONFIG dependencies by parsing the Makefile"""
        configs = set()

        # Get the directory containing the source file
        source_path = self.kernel_dir / source_file
        source_dir = source_path.parent

        # Get the object file name for our source file
        obj_name = source_path.stem + '.o'

        # Get the directory name (for parent directory Makefile lookup)
        dir_name = source_dir.name

        # Try this directory first, then parent directories
        current_dir = source_dir
        depth = 0
        while current_dir != self.kernel_dir and current_dir.parents and depth < 5:  # Limit depth to avoid infinite loops
            makefile = current_dir / 'Makefile'
            if makefile.exists():
                try:
                    with open(makefile, 'r', encoding='utf-8', errors='ignore') as f:
                        content = f.read()

                    # Parse Makefile to find this object file's CONFIG conditions
                    # Always search for the obj_name, whether in same dir or parent dir
                    found = self._parse_makefile_for_config(content, obj_name, current_dir == source_dir)

                    if found:
                        configs.update(found)
                        break
                except Exception as e:
                    pass

            # Move up to parent directory
            current_dir = current_dir.parent
            depth += 1

        return configs

    def _parse_makefile_for_config(self, makefile_content: str, obj_name: str, is_same_dir: bool) -> Set[str]:
        """Parse Makefile content to find CONFIG options for a specific object file"""
        configs = set()
        composite_object = None  # Track if we find our object in a composite object (e.g., btrfs-y)

        lines = makefile_content.splitlines()
        i = 0

        # Track the current conditional context
        current_config = None

        # The target we're searching for
        search_target = obj_name

        while i < len(lines):
            line = lines[i].strip()

            # Look for conditional compilation patterns:
            # ifneq ($(CONFIG_FOO),)
            # ifdef CONFIG_BAR
            if line.startswith('ifneq') or line.startswith('ifdef'):
                match = re.search(r'\$\((CONFIG_[A-Z0-9_]+)\)', line)
                if match:
                    current_config = match.group(1)

            # End of conditional block
            elif line.startswith('endif'):
                current_config = None

            # Look for patterns like:
            # obj-$(CONFIG_FOO) += file.o
            # obj-$(CONFIG_FOO) += directory/
            elif search_target in line:
                # Check if this line contains our target
                if '+=' in line or '=' in line:
                    # First, try to find CONFIG directly in this line
                    match = re.search(r'\$\((CONFIG_[A-Z0-9_]+)\)', line)
                    if match:
                        configs.add(match.group(1))
                    # If not, use the current conditional context
                    elif current_config:
                        configs.add(current_config)
                    break  # Found our target, no need to continue

            # Also handle multi-line definitions with backslash continuation
            elif line.endswith('\\') and i + 1 < len(lines):
                # First, check if current line contains our target
                if search_target in line:
                    # This line has our target, extract CONFIG from it
                    match = re.search(r'\$\((CONFIG_[A-Z0-9_]+)\)', line)
                    if match:
                        configs.add(match.group(1))
                        break
                    elif current_config:
                        configs.add(current_config)
                        break

                # Check for composite object patterns like:
                # btrfs-y += inode.o
                # btrfs-$(CONFIG_FOO) += file.o
                elif ('-y +=' in line or '-y +=' in line.replace(' ', '') or
                      '-objs +=' in line or '-objs +=' in line.replace(' ', '')):
                    # Extract the composite object name (e.g., "btrfs" from "btrfs-y +=")
                    composite_match = re.match(r'([a-zA-Z0-9_]+)-(?:y|objs)\s*\+=', line)
                    if composite_match:
                        composite_name = composite_match.group(1)
                        # Check if our target is in this composite object line or subsequent lines
                        if search_target in line:
                            # Found our object in this composite, check if there's a CONFIG
                            config_match = re.search(r'\$\((CONFIG_[A-Z0-9_]+)\)', line)
                            if config_match:
                                configs.add(config_match.group(1))
                                break
                            elif current_config:
                                configs.add(current_config)
                                break
                            else:
                                # No CONFIG on this line, need to find what controls this composite object
                                composite_object = composite_name
                        # Check multi-line continuation
                        j = i + 1
                        while j < len(lines):
                            if search_target in lines[j]:
                                # Found our object in the multi-line definition
                                # Now we need to find what controls this composite object
                                composite_object = composite_name
                                break
                            if not lines[j].strip().endswith('\\'):
                                break
                            j += 1
                        if composite_object:
                            break

                # Otherwise, check if this line starts a multi-line definition
                # that might lead to our target in subsequent lines
                match = re.search(r'\$\((CONFIG_[A-Z0-9_]+)\)', line)
                if match:
                    # This line has a CONFIG, check if any subsequent line has our target
                    config_from_this_line = match.group(1)
                    j = i + 1
                    while j < len(lines):
                        if search_target in lines[j]:
                            configs.add(config_from_this_line)
                            break
                        # Stop if we hit a line that doesn't end with \
                        if not lines[j].strip().endswith('\\'):
                            break
                        j += 1
                    if configs:
                        break

            i += 1

        # If we found a composite object but no direct CONFIG, search for what controls it
        if composite_object and not configs:
            # Search for obj-$(CONFIG_XXX) += composite_object.o
            composite_target = composite_object + '.o'
            i = 0
            while i < len(lines):
                line = lines[i].strip()
                if composite_target in line:
                    # Found the composite object being controlled by a CONFIG
                    match = re.search(r'\$\((CONFIG_[A-Z0-9_]+)\)', line)
                    if match:
                        configs.add(match.group(1))
                        break
                    elif current_config:
                        configs.add(current_config)
                        break

                # Also check multi-line definitions
                elif line.endswith('\\') and i + 1 < len(lines):
                    match = re.search(r'\$\((CONFIG_[A-Z0-9_]+)\)', line)
                    if match:
                        config_from_this_line = match.group(1)
                        j = i + 1
                        while j < len(lines):
                            if composite_target in lines[j]:
                                configs.add(config_from_this_line)
                                break
                            if not lines[j].strip().endswith('\\'):
                                break
                            j += 1
                        if configs:
                            break
                i += 1

        return configs

    def extract_config_conditions(self, source_file: str, line_numbers: Set[int]) -> Set[str]:
        """Extract CONFIG conditions from specific lines in a source file"""
        full_path = self.kernel_dir / source_file

        if not full_path.exists():
            print(f"Warning: {source_file} not found in kernel tree", file=sys.stderr)
            return set()

        # Read the source file and look for #if CONFIG_ patterns
        # We need to find which conditionals surround each line
        conditions = set()

        try:
            with open(full_path, 'r', encoding='utf-8', errors='ignore') as f:
                lines = f.readlines()

            # Track preprocessor stack as we scan
            stack = []
            line_conditions: Dict[int, List[str]] = defaultdict(list)

            for i, line in enumerate(lines, start=1):
                stripped = line.strip()

                # Track preprocessor directives
                if stripped.startswith("#if") or stripped.startswith("#elif"):
                    stack.append(stripped)
                    line_conditions[i] = stack.copy()
                elif stripped.startswith("#else"):
                    if stack:
                        last = stack.pop()
                        # Negate for else branch
                        cond = last[3:].strip()
                        stack.append(f"!({cond})")
                    line_conditions[i] = stack.copy()
                elif stripped.startswith("#endif"):
                    if stack:
                        stack.pop()
                    line_conditions[i] = stack.copy()
                else:
                    # Regular line - inherit current stack
                    if stack:
                        line_conditions[i] = stack.copy()

            # Now collect conditions for our target lines
            for line_num in line_numbers:
                if line_num in line_conditions:
                    for cond in line_conditions[line_num]:
                        # Extract CONFIG_ symbols from the condition
                        configs = self._extract_configs_from_condition(cond)
                        conditions.update(configs)

        except Exception as e:
            print(f"Error reading {source_file}: {e}", file=sys.stderr)

        return conditions

    def _extract_configs_from_condition(self, condition: str) -> Set[str]:
        """Extract CONFIG symbol names from a preprocessor condition"""
        configs = set()

        # Match patterns like:
        # defined(CONFIG_FOO)
        # CONFIG_FOO
        # CONFIG_FOO=y
        # defined(CONFIG_FOO) && defined(CONFIG_BAR)

        # First handle defined() macros
        defined_pattern = r'defined\s*\(\s*(CONFIG_[A-Z0-9_]+)\s*\)'
        configs.update(re.findall(defined_pattern, condition))

        # Then handle bare CONFIG_ symbols (not inside defined())
        # Remove defined() parts first
        temp = re.sub(defined_pattern, '', condition)
        bare_pattern = r'\b(CONFIG_[A-Z0-9_]+)\b'
        configs.update(re.findall(bare_pattern, temp))

        return configs


class KconfigAnalyzer:
    """Analyze Kconfig dependencies using kconfiglib"""

    def __init__(self, kernel_dir: str):
        # Convert to absolute path
        self.kernel_dir = Path(kernel_dir).resolve()
        self.kconf = None
        self._kconfig_loaded = False

        # Set environment variable for kconfiglib
        import os
        os.environ['srctree'] = str(self.kernel_dir)
        # Set a fake compiler to avoid compiler detection issues
        os.environ['CC'] = 'gcc'
        os.environ['HOSTCC'] = 'gcc'
        os.environ['LD'] = 'ld'

    def _load_kconfig(self):
        """Lazy load Kconfig, only when needed"""
        if self._kconfig_loaded:
            return

        try:
            # Disable warnings to avoid compiler issues
            self.kconf = kconfiglib.Kconfig(
                str(self.kernel_dir / "Kconfig"),
                warn=False
            )
            self._kconfig_loaded = True
        except Exception as e:
            # If kconfiglib fails, we'll do manual parsing
            print(f"Warning: Could not load Kconfig with kconfiglib: {e}", file=sys.stderr)
            print("Falling back to manual Kconfig parsing...", file=sys.stderr)
            self._kconfig_loaded = True

    def analyze_config_dependencies(self, config_symbols: Set[str]) -> Dict[str, Set[str]]:
        """
        Analyze dependencies for given CONFIG symbols.
        Returns a dict mapping each symbol to its required dependencies.
        """
        self._load_kconfig()

        results = {}

        if self.kconf is None:
            # Fallback: manual parsing
            return self._manual_parse_dependencies(config_symbols)

        for symbol_name in config_symbols:
            symbol = self.kconf.syms.get(symbol_name)

            if not symbol:
                # Symbol not found in Kconfig
                results[symbol_name] = set()
                continue

            deps = set()

            # Direct dependencies (from 'depends on')
            if symbol.direct_dep:
                direct_configs = self._extract_configs_from_expr(symbol.direct_dep)
                deps.update(direct_configs)

            # For 'select' statements - these are auto-enabled but might have conditions
            if symbol.selects:
                for selected_sym, cond in symbol.selects:
                    # If the select has a condition, those configs must be enabled
                    if cond:
                        cond_configs = self._extract_configs_from_expr(cond)
                        deps.update(cond_configs)

            results[symbol_name] = deps

        return results

    def _manual_parse_dependencies(self, config_symbols: Set[str]) -> Dict[str, Set[str]]:
        """
        Fallback: Manually parse Kconfig files to find dependencies.
        This is a simplified version that looks for 'depends on' statements.
        """
        results = {}

        # Build a mapping of symbol names to likely Kconfig locations
        # For example, CONFIG_MLX5_CLS_ACT -> drivers/net/ethernet/mellanox/mlx5/core/Kconfig
        symbol_locations = {}
        for symbol_name in config_symbols:
            # Remove CONFIG_ prefix
            name = symbol_name[7:] if symbol_name.startswith('CONFIG_') else symbol_name

            # Try to find Kconfig in a smart way based on symbol name patterns
            locations = []

            # For driver symbols, look in drivers/
            if any(x in name.lower() for x in ['mlx', 'ethernet', 'net', 'wifi']):
                locations.extend(self.kernel_dir.rglob('drivers/**/Kconfig'))

            # For filesystem symbols, look in fs/
            if 'fs' in name.lower() or any(x in name.lower() for x in ['btrfs', 'ext4', 'xfs']):
                locations.extend(self.kernel_dir.rglob('fs/**/Kconfig'))

            # If no specific hint, try the main Kconfig files
            if not locations:
                locations = [
                    self.kernel_dir / 'drivers' / 'Kconfig',
                    self.kernel_dir / 'fs' / 'Kconfig',
                    self.kernel_dir / 'net' / 'Kconfig',
                    self.kernel_dir / 'Kconfig'
                ]

            symbol_locations[symbol_name] = locations

        for symbol_name in config_symbols:
            deps = set()
            # Search for the symbol in relevant Kconfig files only
            for kconfig_file in symbol_locations.get(symbol_name, []):
                found_deps = self._parse_symbol_dependencies(kconfig_file, symbol_name)
                if found_deps:
                    deps.update(found_deps)
                    break  # Found it, no need to search more
            results[symbol_name] = deps

        return results

    def _find_kconfig_files(self) -> List[Path]:
        """Find all Kconfig files in the kernel tree"""
        return list(self.kernel_dir.rglob("Kconfig"))

    def _parse_symbol_dependencies(self, kconfig_file: Path, symbol_name: str) -> Set[str]:
        """Parse a single Kconfig file for dependencies of a symbol"""
        deps = set()

        try:
            with open(kconfig_file, 'r', encoding='utf-8', errors='ignore') as f:
                content = f.read()

            # Find the config definition
            # Pattern: config SYMBOL_NAME or config SYMBOL_NAME
            pattern = rf'\bconfig\s+{symbol_name[7:]}\b'  # Remove CONFIG_ prefix
            match = re.search(pattern, content, re.MULTILINE)

            if match:
                # Get the text from this config to the next config/endmenu
                start = match.start()
                # Find the next 'config', 'menu', 'choice', 'endmenu', etc. at the same level
                # Use a more robust pattern
                next_config = re.search(r'\n\s*(config|menuconfig|menu|choice|comment|endmenu|if|endif)\s',
                                        content[start + 1:], re.MULTILINE)

                if next_config:
                    section = content[start:start + next_config.start() + 1]
                else:
                    section = content[start:]

                # Extract dependencies from 'depends on'
                depends_pattern = r'depends\s+on\s+(.+?)(?:\n|$)'
                for match in re.finditer(depends_pattern, section, re.IGNORECASE):
                    dep_expr = match.group(1).strip()
                    # Extract CONFIG symbols from the dependency expression
                    # First, find symbols with CONFIG_ prefix
                    dep_symbols = re.findall(r'\b(CONFIG_[A-Z0-9_]+)\b', dep_expr)
                    deps.update(dep_symbols)

                    # Then, find symbols without CONFIG_ prefix (Kconfig allows both forms)
                    # Remove the ones we already found with CONFIG_ prefix
                    temp_expr = re.sub(r'\bCONFIG_[A-Z0-9_]+\b', '', dep_expr)
                    # Find bare symbols (all caps, typical Kconfig symbol names)
                    bare_symbols = re.findall(r'\b([A-Z][A-Z0-9_]+)\b', temp_expr)
                    for bare in bare_symbols:
                        # Skip common keywords and operators
                        if bare not in ['Y', 'N', 'M', 'AND', 'OR', 'NOT', 'IF', 'THEN']:
                            deps.add(f"CONFIG_{bare}")

                # Also add the symbols that are selected (they are dependencies too)
                select_pattern = r'select\s+([A-Z0-9_]+)\s*(?:if\s+(.+?))?(?:\n|$)'
                for match in re.finditer(select_pattern, section, re.IGNORECASE):
                    selected = match.group(1)
                    # Convert to CONFIG_ format
                    if not selected.startswith('CONFIG_'):
                        selected = f"CONFIG_{selected}"
                    deps.add(selected)

                    # Also add conditions if present
                    cond = match.group(2)
                    if cond:
                        cond_symbols = re.findall(r'\b(CONFIG_[A-Z0-9_]+)\b', cond)
                        deps.update(cond_symbols)

        except Exception as e:
            pass  # Ignore errors in manual parsing

        return deps

    def _extract_configs_from_expr(self, expr) -> Set[str]:
        """Extract CONFIG symbols from a kconfiglib expression"""
        configs = set()

        if expr is None:
            return configs

        # Convert to string and extract CONFIG_ references
        # kconfiglib expressions can be complex, so we use string representation
        expr_str = str(expr)

        # Match CONFIG_FOO patterns
        pattern = r'\b(CONFIG_[A-Z0-9_]+)\b'
        configs = set(re.findall(pattern, expr_str))

        return configs

    def get_all_required_configs(self, patch_configs: Set[str]) -> Set[str]:
        """
        Recursively get all CONFIG options needed for the patch.
        Returns the complete set of CONFIG options that must be enabled.
        """
        required = set(patch_configs)
        to_process = set(patch_configs)
        visited = set()

        while to_process:
            current = to_process.pop()

            if current in visited:
                continue
            visited.add(current)

            # Get dependencies for this config
            deps = self.analyze_config_dependencies({current})

            for symbol, dep_set in deps.items():
                for dep in dep_set:
                    if dep not in required:
                        required.add(dep)
                        to_process.add(dep)

        return required


class PatchConfigAnalyzer:
    """Main analyzer combining patch parsing and Kconfig analysis"""

    def __init__(self, kernel_dir: str):
        self.kernel_dir = kernel_dir
        self.source_analyzer = SourceAnalyzer(kernel_dir)
        self.kconfig_analyzer = KconfigAnalyzer(kernel_dir)

    def analyze_patch(self, patch_file: str) -> Set[str]:
        """
        Analyze a patch file and return all required CONFIG options.
        Returns empty set if any error occurs or no configs found.
        """
        try:
            # Read patch
            patch_content = Path(patch_file).read_text()
        except Exception:
            return set()

        try:
            # Parse patch to get modified lines
            parser = PatchParser(patch_content)
            files_changed = parser.parse()

            if not files_changed:
                return set()

            # Extract CONFIG conditions from modified lines
            all_config_conditions = set()

            for source_file, line_numbers in files_changed.items():
                # Only analyze C source files
                if not (source_file.endswith('.c') or source_file.endswith('.h')):
                    continue

                # Try to get CONFIG from Makefile (most accurate)
                makefile_configs = self.source_analyzer.extract_config_from_makefile(source_file)
                all_config_conditions.update(makefile_configs)

                # If Makefile didn't give us the answer, try source code analysis
                if not makefile_configs:
                    configs = self.source_analyzer.extract_config_conditions(
                        source_file, line_numbers
                    )
                    all_config_conditions.update(configs)

            return all_config_conditions
        except Exception:
            return set()

    def _infer_config_from_path(self, source_file: str) -> Set[str]:
        """
        Infer CONFIG options from the file path using a generic approach.
        For example:
        - fs/btrfs/foo.c -> CONFIG_BTRFS_FS
        - drivers/net/ethernet/mellanox/mlx5/... -> CONFIG_MLX5_CORE
        """
        configs = set()

        # Extract directory path
        path_parts = Path(source_file).parts

        # Convert path to list for easier processing
        path_list = list(path_parts)

        # Generic approach: find Kconfig files and match them to path components
        for i, part in enumerate(path_list):
            if part in ['Kconfig', 'Makefile', '.git', 'include']:
                continue

            # Try different CONFIG name patterns based on directory name
            possible_configs = []

            # Pattern 1: For drivers/ or fs/ subdirectories: CONFIG_<NAME>[_FS|_CORE]
            if 'drivers' in path_list or 'fs' in path_list:
                # Try CONFIG_<DIR>_CORE for drivers
                if 'drivers' in path_list:
                    possible_configs.append(f"CONFIG_{part.upper()}_CORE")
                    possible_configs.append(f"CONFIG_{part.upper()}")

                # Try CONFIG_<DIR>_FS for filesystems
                if 'fs' in path_list:
                    possible_configs.append(f"CONFIG_{part.upper()}_FS")
                    possible_configs.append(f"CONFIG_{part.upper()}")

                # Try just CONFIG_<DIR> for other cases
                possible_configs.append(f"CONFIG_{part.upper()}")

            # Pattern 2: For net/ directory: CONFIG_NET_<DRIVER>
            if 'net' in path_list:
                possible_configs.append(f"CONFIG_{part.upper()}")

            # Pattern 3: For sound/, block/, crypto/, etc.
            if path_list[0] in ['drivers', 'fs', 'net', 'sound', 'block', 'crypto', 'security']:
                possible_configs.append(f"CONFIG_{part.upper()}")

            # Try to verify which configs actually exist
            for config in possible_configs:
                if self._config_exists(config):
                    configs.add(config)
                    # Once we find a match, use it
                    break

        # Special case: if still no configs found, try to infer from parent directory
        if not configs and len(path_list) >= 2:
            # Look for Makefile in parent directory to see what config controls this directory
            for i in range(len(path_list) - 1, 0, -1):
                parent_dir = self.kernel_dir / Path(*path_list[:i])
                if parent_dir.exists() and (parent_dir / 'Kconfig').exists():
                    # Found a Kconfig, try to parse it
                    inferred = self._parse_kconfig_for_directory(parent_dir, path_list[i] if i < len(path_list) else '')
                    configs.update(inferred)
                    if configs:
                        break

        return configs

    def _config_exists(self, config_name: str) -> bool:
        """Check if a CONFIG symbol exists - simplified version that assumes it exists"""
        # Since we're getting configs from Makefile, we can assume they exist
        # No need to verify via Kconfig parsing
        return True

    def _parse_kconfig_for_directory(self, kconfig_dir: Path, subdir: str) -> Set[str]:
        """Parse a Kconfig file to find configs related to a subdirectory"""
        configs = set()

        kconfig_file = kconfig_dir / 'Kconfig'
        if not kconfig_file.exists():
            return configs

        try:
            with open(kconfig_file, 'r', encoding='utf-8', errors='ignore') as f:
                content = f.read()

            # Look for 'source' statements that include the subdirectory
            source_pattern = rf'source\s+["\']?{re.escape(subdir)}/Kconfig'
            if re.search(source_pattern, content):
                # This Kconfig sources our subdir, look for config definitions
                # that might control it
                config_defs = re.finditer(r'\bconfig\s+([A-Z0-9_]+)', content)
                for match in config_defs:
                    config_name = f"CONFIG_{match.group(1)}"
                    if self._config_exists(config_name):
                        configs.add(config_name)
                        break  # Use the first match

            # Also look for configs that match the directory name
            if subdir:
                # Remove common suffixes/prefixes
                base_name = subdir.rstrip('1234567890-_.')
                possible_configs = [
                    f"CONFIG_{base_name.upper()}_CORE",
                    f"CONFIG_{base_name.upper()}",
                    f"CONFIG_{base_name.upper()}_FS",
                    f"CONFIG_{subdir.upper()}_CORE",
                    f"CONFIG_{subdir.upper()}",
                ]

                for config in possible_configs:
                    if self._config_exists(config):
                        configs.add(config)
                        break

        except Exception:
            pass

        return configs

    def analyze_and_report(self, patch_file: str) -> None:
        """Analyze patch and print CONFIG options"""
        configs = self.analyze_patch(patch_file)

        if not configs:
            return

        # Only print the CONFIG options
        for config in sorted(configs):
            print(f"{config}=y")


def main():
    if len(sys.argv) < 2:
        print("Usage: judge_config.py <patch-file> [kernel-source-dir]", file=sys.stderr)
        sys.exit(1)

    patch_file = sys.argv[1]

    # Default kernel directory
    if len(sys.argv) >= 3:
        kernel_dir = sys.argv[2]
    else:
        # Try to find kernel directory
        script_dir = Path(__file__).parent.parent.parent
        kernel_dir = script_dir / "data" / "linux"

    kernel_dir = Path(kernel_dir).resolve()
    if not kernel_dir.exists():
        sys.exit(1)

    try:
        analyzer = PatchConfigAnalyzer(str(kernel_dir))
        analyzer.analyze_and_report(patch_file)
    except Exception:
        sys.exit(1)


if __name__ == "__main__":
    main()
