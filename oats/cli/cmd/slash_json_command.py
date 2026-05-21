#!/usr/bin/env python3
"""
Slash JSON command for the oats interactive CLI.

Reads a JSON file from S3 or the local filesystem and prints it
formatted to the console. Supports argparse-style short arguments
for the standalone script and the /json slash command in the REPL.

Usage (standalone):
    python -m oats.cli.cmd.slash_json_command -f path/to/file.json
    python -m oats.cli.cmd.slash_json_command -f s3://bucket/key/file.json
    python -m oats.cli.cmd.slash_json_command --file path/to/file.json

Usage (REPL):
    /json path/to/file.json
    /json s3://bucket/key/file.json
    /json -f path/to/file.json
    /json --file path/to/file.json
"""

import argparse
import json
import os
import sys
from pathlib import Path

from rich.console import Console
from rich.json import JSON as RichJSON

from oats.log import create_log

log = create_log('json.cmd')
console = Console()


def _read_json_file(file_path: str, verbose: bool = False):
    """
    Read a JSON file from S3 or the local filesystem.

    Args:
        file_path: Path to the JSON file. Supports local paths and
                   s3://bucket/key format.
        verbose: If True, print diagnostic messages.

    Returns:
        The parsed JSON data, or None on failure.
    """
    if file_path.startswith("s3://"):
        if verbose:
            console.print(f"  [dim]downloading from S3: {file_path}[/dim]")
        from oats.s3.download_file import download_file
        content, _ = download_file(loc=file_path, verbose=verbose)
        if content is None:
            console.print(f"  [red]failed to download from S3: {file_path}[/red]")
            return None
        return json.loads(content)
    else:
        local_path = Path(file_path)
        if not local_path.exists():
            console.print(f"  [red]file not found: {local_path}[/red]")
            return None
        if verbose:
            console.print(f"  [dim]reading local file: {local_path}[/dim]")
        try:
            with open(local_path, "r", encoding="utf-8") as fh:
                return json.load(fh)
        except json.JSONDecodeError as e:
            console.print(f"  [red]invalid JSON in {local_path}: {e}[/red]")
            return None
        except Exception as e:
            console.print(f"  [red]error reading {local_path}: {e}[/red]")
            return None


def _print_json(data, indent: int = 2):
    """Print JSON data formatted to the console using Rich."""
    if data is None:
        console.print("  [yellow]no data to display[/yellow]")
        return
    rich_json = RichJSON.from_data(data, indent=indent)
    console.print(rich_json)


def handle_json_command(args_str: str, console: Console, verbose: bool = False):
    """
    Handle the /json slash command.

    Parses the arguments and reads/prints the JSON file.

    Args:
        args_str: The argument string after /json (e.g. "-f file.json" or "file.json").
        console: Rich console instance for output.
        verbose: If True, print diagnostic messages.
    """
    # Parse arguments using argparse
    parser = argparse.ArgumentParser(
        description="Read and display a JSON file from S3 or local filesystem.",
        prog="/json",
    )
    parser.add_argument(
        "-f", "--file",
        help="Path to the JSON file (local or s3://bucket/key)",
    )
    parser.add_argument(
        "-v", "--verbose",
        action="store_true",
        help="Enable verbose output",
    )
    parser.add_argument(
        "file_path",
        nargs="?",
        default=None,
        help="Path to the JSON file (positional, local or s3://bucket/key)",
    )

    try:
        parsed = parser.parse_args(args_str.split())
    except SystemExit:
        return

    # Determine the file path: --file takes precedence over positional
    file_path = parsed.file or parsed.file_path
    if not file_path:
        console.print("  [yellow]usage: /json <file_path>[/yellow]")
        console.print("  [dim]  /json path/to/file.json[/dim]")
        console.print("  [dim]  /json s3://bucket/key/file.json[/dim]")
        console.print("  [dim]  /json -f path/to/file.json[/dim]")
        console.print("  [dim]  /json --file path/to/file.json[/dim]")
        return

    verbose = verbose or parsed.verbose
    log.info(f"reading JSON file: {file_path}")

    data = _read_json_file(file_path, verbose=verbose)
    if data is not None:
        _print_json(data)
        console.print()


def main():
    """Entry point for standalone usage."""
    parser = argparse.ArgumentParser(
        description="Read and display a JSON file from S3 or local filesystem.",
        prog="slash_json_command",
    )
    parser.add_argument(
        "-f", "--file",
        required=True,
        help="Path to the JSON file (local or s3://bucket/key)",
    )
    parser.add_argument(
        "-v", "--verbose",
        action="store_true",
        help="Enable verbose output",
    )
    args = parser.parse_args()

    log.info(f"reading JSON file: {args.file}")
    data = _read_json_file(args.file, verbose=args.verbose)
    if data is not None:
        _print_json(data)


if __name__ == "__main__":
    main()
