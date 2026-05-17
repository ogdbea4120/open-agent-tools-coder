"""
README Generator Tool for the OATS platform.

Provides :class:`GenerateREADMETool` which scans directories and generates
README.md files that provide detailed overviews of the modules in each
subdirectory, including module names, descriptions, key functions, and
classes.

Helper function:

- :func:`register_generate_readme_tool` — Register the tool with the global registry.
"""

from __future__ import annotations

import os
import ast
from typing import Any
from pathlib import Path
from oats.tool.registry import Tool, ToolContext, ToolResult
from oats.log import cl

log = cl('tool.readme')


class GenerateREADMETool(Tool):
    """Generate README.md files with detailed module overviews in subdirectories.

    Scans each subdirectory and creates a README.md file that provides:

    - A detailed overview of the modules in that subdirectory
    - Module names and descriptions
    - Key functions and classes
    - Usage examples where applicable

    Example:
        ::

            generate_readme
            generate_readme path="./oats/cli"
    """

    @property
    def name(self) -> str:
        return "generate_readme"

    @property
    def description(self) -> str:
        return """Generate README.md files with detailed module overviews in subdirectories.

This tool scans each subdirectory and creates a README.md file that provides:
- A detailed overview of the modules in that subdirectory
- Module names and descriptions
- Key functions and classes
- Usage examples where applicable

Usage:
- Run without arguments to scan the current directory
- Or specify a path to scan a specific directory

Example: generate_readme
Example: generate_readme path=./oats/cli
"""

    @property
    def parameters(self) -> dict[str, Any]:
        return {
            "type": "object",
            "properties": {
                "path": {
                    "type": "string",
                    "description": "Path to directory to scan (default: current directory)",
                },
            },
            "required": [],
        }

    def _extract_module_docstring(self, file_path: Path) -> str:
        """Extract the module-level docstring from a Python file.

        Parses the file's AST and retrieves the top-level docstring.

        Args:
            file_path: Path to the Python file.

        Returns:
            The module docstring as a string, or an empty string if not found.
        """
        try:
            with open(file_path, "r", encoding="utf-8") as f:
                content = f.read()

            # Parse the AST to get the module docstring
            tree = ast.parse(content)
            docstring = ast.get_docstring(tree)

            if docstring:
                # Clean up the docstring
                docstring = docstring.strip()
                # Convert to markdown format
                docstring = docstring.replace("\n", "\n\n")
                return docstring
            return ""
        except Exception:
            return ""

    def _get_module_info(self, file_path: Path) -> dict[str, str]:
        """Get basic information about a Python module.

        Extracts the module name and docstring. If no docstring is found,
        infers a description from the filename.

        Args:
            file_path: Path to the Python file.

        Returns:
            A dict with keys ``name``, ``docstring``, and ``path``.
        """
        try:
            # Get module name without extension
            module_name = file_path.stem

            # Try to extract docstring
            docstring = self._extract_module_docstring(file_path)

            # If no docstring, try to infer from filename
            if not docstring:
                if module_name == "__init__":
                    docstring = f"Initialization module for {file_path.parent.name}"
                else:
                    docstring = f"Module: {module_name}"

            return {
                "name": module_name,
                "docstring": docstring,
                "path": str(file_path.relative_to(Path.cwd())),
            }
        except Exception:
            return {
                "name": file_path.stem,
                "docstring": "",
                "path": str(file_path.relative_to(Path.cwd())),
            }

    def _analyze_directory(self, directory_path: Path) -> dict[str, Any]:
        """Analyze a directory to gather information about its Python modules.

        Recursively finds all ``.py`` files, extracts module docstrings, and
        returns a summary dict.

        Args:
            directory_path: The directory to analyze.

        Returns:
            A dict with keys ``directory``, ``modules`` (list of module info dicts),
            and ``total_modules``.
        """
        modules = []
        python_files = list(directory_path.rglob("*.py"))

        # Filter out __pycache__ and other hidden directories
        python_files = [
            f for f in python_files if not f.parts[0].startswith(".") and ".pyc" not in str(f)
        ]

        for file_path in python_files:
            # Skip __init__.py files in the main directory
            if file_path.name == "__init__.py" and file_path.parent == directory_path:
                continue

            module_info = self._get_module_info(file_path)
            modules.append(module_info)

        return {"directory": str(directory_path), "modules": modules, "total_modules": len(modules)}

    def _generate_readme_content(self, directory_info: dict[str, Any]) -> str:
        """Generate README.md content for a directory based on module analysis.

        Produces a markdown document with:
        - An overview section with a module count
        - A table of modules and their descriptions
        - Detailed module descriptions
        - Usage examples

        Args:
            directory_info: A dict from :meth:`_analyze_directory` with keys
                ``directory``, ``modules``, and ``total_modules``.

        Returns:
            The README content as a markdown string.
        """
        directory = directory_info["directory"]
        modules = directory_info["modules"]

        # Title
        content = f"# README for {os.path.basename(directory)}\n\n"

        # Description
        content += "## Overview\n\n"
        content += f"This directory contains {len(modules)} Python modules:\n\n"

        # Module listing
        if modules:
            content += "| Module | Description |\n"
            content += "|--------|-------------|\n"
            for module in modules:
                # Clean up the description to fit in table
                desc = (
                    module["docstring"].split("\n")[0]
                    if module["docstring"]
                    else "No description available."
                )
                # Limit description length
                if len(desc) > 100:
                    desc = desc[:97] + "..."
                content += f"| `{module['name']}` | {desc} |\n"
            content += "\n"

        # Detailed module descriptions
        if modules:
            content += "## Detailed Module Descriptions\n\n"
            for module in modules:
                content += f"### `{module['name']}`\n\n"
                if module["docstring"]:
                    content += f"{module['docstring']}\n\n"
                else:
                    content += f"Details about the `{module['name']}` module.\n\n"

        # Additional information
        content += "## Usage\n\n"
        content += "To use the modules in this directory, import them directly:\n\n"
        content += "```python\n"
        for module in modules[:3]:  # Show first 3 modules
            content += f"from {os.path.basename(directory)}.{module['name']} import *\n"
        if len(modules) > 3:
            content += "...\n"
        content += "```\n\n"

        return content

    async def execute(self, args: dict[str, Any], ctx: ToolContext) -> ToolResult:
        """Scan a directory and generate README.md files for each subdirectory.

        Validates the target path, analyzes Python modules in each subdirectory
        (extracting docstrings via AST), and writes a README.md file per
        subdirectory with module overviews, descriptions, and usage examples.

        Args:
            args: May contain ``path`` (str, directory to scan, default: current dir).
            ctx: The tool execution context.

        Returns:
            A :class:`ToolResult` with a summary of README files generated.
        """
        # Determine path to scan
        path_str = args.get("path", ".")
        scan_path = Path(path_str).resolve()

        # Validate the path exists
        if not scan_path.exists():
            return ToolResult(
                title="README Generation",
                output=f"# README Generation Error\n\n**Error:** Path '{scan_path}' does not exist.",
                error=f"Path '{scan_path}' does not exist",
            )

        # If it's a file, we can't generate READMEs for it
        if scan_path.is_file():
            return ToolResult(
                title="README Generation",
                output=f"# README Generation Error\n\n**Error:** '{scan_path}' is a file, not a directory.",
                error=f"'{scan_path}' is a file, not a directory",
            )

        # Find all subdirectories
        subdirs = [d for d in scan_path.iterdir() if d.is_dir() and not d.name.startswith(".")]

        # Also include the main directory itself if it has Python files
        main_dir_has_py = any(scan_path.glob("*.py"))
        if main_dir_has_py:
            subdirs.insert(0, scan_path)

        # Generate READMEs
        success_count = 0
        failed_dirs = []

        for subdir in subdirs:
            try:
                # Analyze the directory
                dir_info = self._analyze_directory(subdir)

                # Generate README content
                readme_content = self._generate_readme_content(dir_info)

                # Write README.md
                readme_path = subdir / "README.md"
                readme_path.write_text(readme_content, encoding="utf-8")

                success_count += 1

            except Exception as e:
                failed_dirs.append(str(subdir))
                print(f"Failed to generate README for {subdir}: {str(e)}")

        # Build result message
        result_msg = "# README Generation Complete\n\n"
        result_msg += f"Successfully generated README.md files for {success_count} directories.\n\n"

        if failed_dirs:
            result_msg += "Failed to generate README.md for the following directories:\n"
            for failed_dir in failed_dirs:
                result_msg += f"- {failed_dir}\n"
            result_msg += "\n"

        result_msg += "## Generated Files\n\n"
        result_msg += "The following README.md files were created:\n\n"
        for subdir in subdirs:
            result_msg += f"- {subdir}/README.md\n"

        return ToolResult(
            title="README Generation",
            output=result_msg,
        )


def register_generate_readme_tool() -> None:
    """Register the README generation tool with the global tool registry.

    Creates a :class:`GenerateREADMETool` instance and registers it via
    :func:`oats.tool.registry.register_tool`.
    """
    from oats.tool.registry import register_tool

    register_tool(GenerateREADMETool())


# Standalone execution support
if __name__ == "__main__":
    import asyncio

    # Create a mock context for testing

    # Register the tool
    register_generate_readme_tool()

    # Create tool instance
    tool = GenerateREADMETool()

    # Create a mock context
    ctx = ToolContext(session_id="test_session", project_dir=Path("."), working_dir=Path("."))

    # Execute with current directory
    async def main():
        """Standalone entry point for testing the README generation tool."""
        try:
            result = await tool.execute({"path": "."}, ctx)
            print(result.output)
        except Exception as e:
            print(f"Error running tool: {e}")

    asyncio.run(main())
