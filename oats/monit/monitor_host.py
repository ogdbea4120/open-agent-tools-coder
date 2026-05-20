#!/usr/bin/env python3
"""Host monitoring script — CPU, GPU, disk free space, and coder process count.

Polls system metrics at a configurable interval and appends rows to a CSV
archive file.  Defaults to a single run (dry-run validation).
"""

import argparse
import csv
import os
import re
import subprocess
import time
from datetime import datetime, timezone

from oats.log import cl

log = cl("monit_host")

# ---------------------------------------------------------------------------
# Defaults
# ---------------------------------------------------------------------------
DEFAULT_METRICS_FILE = "/tmp/coder-metrics.csv"
DEFAULT_INTERVAL = 30  # seconds
DEFAULT_RUNS = 1  # dry-run validation by default

CSV_FIELDS = [
    "timestamp",
    "cpu_percent",
    "gpu_count",
    "gpu_util_percent",
    "gpu_mem_used_mb",
    "gpu_mem_total_mb",
    "disk_free_gb",
    "coder_process_count",
]


# ---------------------------------------------------------------------------
# Metric collectors
# ---------------------------------------------------------------------------

def get_cpu_percent() -> float:
    """Return overall CPU usage percent via /proc/stat (two-sample approach)."""
    try:
        with open("/proc/stat") as f:
            line1 = f.readline()
        fields1 = list(map(int, line1.split()[1:]))

        time.sleep(0.5)

        with open("/proc/stat") as f:
            line2 = f.readline()
        fields2 = list(map(int, line2.split()[1:]))

        idle1 = fields1[3]
        idle2 = fields2[3]
        total1 = sum(fields1)
        total2 = sum(fields2)

        idle_delta = idle2 - idle1
        total_delta = total2 - total1

        if total_delta == 0:
            return 0.0
        return round((1.0 - idle_delta / total_delta) * 100, 2)
    except Exception as e:
        log.warn(f"failed to read CPU: {e}")
        return -1.0


def get_gpu_metrics() -> dict:
    """Return GPU metrics via nvidia-smi (if available)."""
    result = {
        "gpu_count": 0,
        "gpu_util_percent": 0.0,
        "gpu_mem_used_mb": 0,
        "gpu_mem_total_mb": 0,
    }
    try:
        out = subprocess.check_output(
            [
                "nvidia-smi",
                "--query-gpu=utilization.gpu,memory.used,memory.total",
                "--format=csv,noheader,nounits",
            ],
            stderr=subprocess.DEVNULL,
        ).decode().strip()
    except (FileNotFoundError, subprocess.CalledProcessError):
        return result

    if not out:
        return result

    lines = [l.strip() for l in out.split("\n") if l.strip()]
    result["gpu_count"] = len(lines)

    utils, used, totals = [], [], []
    for line in lines:
        parts = [p.strip() for p in line.split(",")]
        if len(parts) == 3:
            try:
                utils.append(float(parts[0]))
                used.append(int(parts[1]))
                totals.append(int(parts[2]))
            except ValueError:
                continue

    result["gpu_util_percent"] = round(sum(utils) / len(utils), 2) if utils else 0.0
    result["gpu_mem_used_mb"] = sum(used)
    result["gpu_mem_total_mb"] = sum(totals)
    return result


def get_disk_free_gb(path: str = "/") -> float:
    """Return free disk space in GB for the given mount point."""
    try:
        stat = os.statvfs(path)
        free_bytes = stat.f_bavail * stat.f_frsize
        return round(free_bytes / (1024 ** 3), 2)
    except Exception as e:
        log.warn(f"failed to read disk free: {e}")
        return -1.0


def get_coder_process_count() -> int:
    """Count processes whose command line contains the word 'coder'."""
    try:
        out = subprocess.check_output(
            ["ps", "aux"],
            stderr=subprocess.DEVNULL,
        ).decode()
    except (FileNotFoundError, subprocess.CalledProcessError) as e:
        log.warn(f"failed to list processes: {e}")
        return -1

    count = 0
    pattern = re.compile(r"coder", re.IGNORECASE)
    for line in out.strip().split("\n"):
        if pattern.search(line):
            count += 1
    return count


# ---------------------------------------------------------------------------
# CSV helpers
# ---------------------------------------------------------------------------

def _ensure_csv(filepath: str) -> None:
    """Create the CSV file with a header row if it doesn't exist yet."""
    if not os.path.exists(filepath):
        with open(filepath, "w", newline="") as f:
            writer = csv.DictWriter(f, fieldnames=CSV_FIELDS)
            writer.writeheader()


def append_row(filepath: str, row: dict) -> None:
    """Append a single metrics row to the CSV."""
    with open(filepath, "a", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=CSV_FIELDS)
        writer.writerow(row)


# ---------------------------------------------------------------------------
# Main loop
# ---------------------------------------------------------------------------

def collect_metrics() -> dict:
    """Collect all metrics into a single dict."""
    ts = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    gpu = get_gpu_metrics()
    return {
        "timestamp": ts,
        "cpu_percent": get_cpu_percent(),
        "gpu_count": gpu["gpu_count"],
        "gpu_util_percent": gpu["gpu_util_percent"],
        "gpu_mem_used_mb": gpu["gpu_mem_used_mb"],
        "gpu_mem_total_mb": gpu["gpu_mem_total_mb"],
        "disk_free_gb": get_disk_free_gb(),
        "coder_process_count": get_coder_process_count(),
    }


def run(args: argparse.Namespace) -> None:
    _ensure_csv(args.metrics_file)

    if args.runs == -1:
        log.info(f"continuous mode — interval={args.interval}s, output={args.metrics_file}")
    else:
        log.info(f"running {args.runs} time(s), output={args.metrics_file}")

    iteration = 0
    while True:
        row = collect_metrics()
        append_row(args.metrics_file, row)
        iteration += 1

        log.info(
            f"#{iteration}  cpu={row['cpu_percent']}%  "
            f"gpu_count={row['gpu_count']}  gpu_util={row['gpu_util_percent']}%  "
            f"gpu_mem={row['gpu_mem_used_mb']}/{row['gpu_mem_total_mb']}MB  "
            f"disk_free={row['disk_free_gb']}GB  "
            f"coder_procs={row['coder_process_count']}"
        )

        if args.runs != -1 and iteration >= args.runs:
            break

        if args.runs == -1:
            time.sleep(args.interval)


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def parse_args(argv=None) -> argparse.Namespace:
    p = argparse.ArgumentParser(
        description="Monitor host metrics (CPU, GPU, disk, coder processes) and append to CSV.",
    )
    p.add_argument(
        "-o", "--metrics-file",
        default=DEFAULT_METRICS_FILE,
        help=f"CSV output path (default: {DEFAULT_METRICS_FILE})",
    )
    p.add_argument(
        "-i", "--interval",
        type=int,
        default=DEFAULT_INTERVAL,
        help=f"Polling interval in seconds for continuous mode (default: {DEFAULT_INTERVAL})",
    )
    p.add_argument(
        "-n", "--runs",
        type=int,
        default=DEFAULT_RUNS,
        help=(
            "Number of collection cycles.  Use -1 for continuous.  "
            f"Default is {DEFAULT_RUNS} (dry-run validation)."
        ),
    )
    return p.parse_args(argv)


def main() -> None:
    args = parse_args()
    run(args)


if __name__ == "__main__":
    main()
