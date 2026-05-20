"""
CLI for the trajectory self-improvement report.

Usage::

    python -m oats.trajectory.report                 # 7-day markdown report
    python -m oats.trajectory.report --since 30      # 30-day window
    python -m oats.trajectory.report --json          # raw dict

The heavy lifting lives in :mod:`oats.trajectory.metrics`; this module is
just argument parsing and output formatting.
"""
from __future__ import annotations

import argparse
import json
import sys

from oats.trajectory.metrics import format_report_markdown, report


def main(argv: list[str] | None = None) -> int:
    """CLI entry point for the trajectory self-improvement report.

    Parses ``--since`` (window in days, default 7) and ``--json`` (emit JSON
    instead of Markdown). Delegates to :func:`oats.trajectory.metrics.report`
    and :func:`oats.trajectory.metrics.format_report_markdown`.

    Args:
        argv: Command-line arguments (defaults to ``sys.argv[1:]``).

    Returns:
        Exit code (always 0 on success).
    """
    ap = argparse.ArgumentParser(description="Coder2 self-improvement report")
    ap.add_argument("--since", type=float, default=7.0, help="Window in days (default 7)")
    ap.add_argument("--json", action="store_true", help="Emit JSON instead of Markdown")
    args = ap.parse_args(argv)

    data = report(since_days=args.since)
    if args.json:
        print(json.dumps(data, indent=2, sort_keys=True))
    else:
        print(format_report_markdown(data))
    return 0


if __name__ == "__main__":
    sys.exit(main())
