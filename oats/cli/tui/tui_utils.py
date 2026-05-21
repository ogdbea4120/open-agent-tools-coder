"""Terminal UI utility functions for the interactive coder REPL.

Provides helpers for rendering tools, configuration, git diffs/logs,
session history, web page browsing, think-block filtering, and a
live animated status tracker. Also includes the slash-command help
table and various formatting utilities.
"""

import os
import sys
import traceback
import time
import signal
import uuid
import re
import asyncio
from pathlib import Path
from rich.live import Live
from rich.text import Text
from rich.console import Console
from oats.cli.tui.tui_consts import (
    SYM_TOOL,
    SYM_ERR,
    SYM_WARN,
    SYM_SEP,
    SYM_OK,
    SYM_COMPACT,
    SYM_ITER,
    TOOL_ICONS,
    _IMAGE_EXTS,
    _format_tokens,
    _detect_image_protocol,
)

def _print_tools(console: Console):
    """Print available tools in a compact grouped format."""
    from oats.tool.registry import list_tools as _lt
    tools = sorted(_lt(), key=lambda x: x.name)

    console.print()
    for t in tools:
        icon = TOOL_ICONS.get(t.name, " ")
        aliases = ""
        if hasattr(t, 'aliases') and t.aliases:
            aliases = f" [dim]({', '.join(t.aliases)})[/dim]"
        desc = t.description.split('\n')[0][:55]
        loaded = "[green]●[/green]" if getattr(t, 'always_load', False) else "[dim]○[/dim]"
        console.print(f"  {loaded} {icon} [bold cyan]{t.name:16}[/bold cyan]{aliases} [dim]{desc}[/dim]")
    console.print(f"\n  [dim]{len(tools)} tools loaded[/dim]")
    console.print()

def _print_config(console: Console, verbose: bool = False):
    """Print active configuration."""
    from oats.core.config import get_config
    cfg = get_config()

    console.print()
    console.print(f"  [bold cyan]config[/bold cyan]")
    console.print(f"  [dim]data dir[/dim]     {cfg.data_dir}")
    console.print(f"  [dim]project dir[/dim]  {cfg.project_dir}")
    console.print(f"  [dim]model[/dim]        {cfg.model.model_id}")
    console.print(f"  [dim]provider[/dim]     {cfg.model.provider_id}")

    if cfg.provider:
        console.print()
        console.print(f"  [bold cyan]providers[/bold cyan]")
        for name, prov in cfg.provider.items():
            url = prov.base_url or ""
            key = "******"
            if verbose:
                key = "***" + prov.api_key[-4:] if prov.api_key and len(prov.api_key) > 4 else prov.api_key or ""
            enabled = "[green]●[/green]" if prov.enabled else "[red]○[/red]"
            console.print(f"  {enabled} [cyan]{name:16}[/cyan] [dim]{url}[/dim]  [dim]{key}[/dim]")

    if cfg.hooks.hooks:
        console.print()
        console.print(f"  [bold cyan]hooks[/bold cyan]")
        for h in cfg.hooks.hooks:
            matcher = f" [dim]({h.matcher})[/dim]" if h.matcher else ""
            console.print(f"  [dim]·[/dim] {h.event}{matcher} → [dim]{h.command}[/dim]")

    if cfg.permission:
        console.print()
        console.print(f"  [bold cyan]permissions[/bold cyan]")
        console.print(f"  [dim]bash[/dim]  {cfg.permission.bash}")
        for path, rule in cfg.permission.read.items():
            console.print(f"  [dim]read[/dim]  {path} → {rule}")
        for path, rule in cfg.permission.write.items():
            console.print(f"  [dim]write[/dim] {path} → {rule}")

    coder_config_file = os.getenv('CODER_CONFIG_FILE', None)
    if coder_config_file is None:
        console.print(f"  [red]Warning - environment variable CODER_CONFIG_FILE is not set[/red] Please run [cyan]export CODER_CONFIG_FILE=PATH/coder.json[/cyan] then restart with [cyan]oat[/cyan]")
    else:
        if os.path.exists(coder_config_file):
            from oats.cli.validate_coder_env import validate_coder_env
            valid_env_vllm_small = False
            try:
                valid_env_vllm_small = validate_coder_env(provider_id='vllm-small')
                if not valid_env_vllm_small:
                    console.print(f'[red]Detected vLLM - chat - misconfigured[/red] named: [cyan]vllm-small[/cyan].\n  👉 Please check the config: [cyan]{coder_config_file}[/cyan]')

            except Exception:
                console.print(f'[red]Detected Invalid vLLM - chat[/red] with vLLM: [cyan]vllm-small[/cyan].\n  👉 Please check the config: [cyan]{coder_config_file}[/cyan]')
            valid_env_tool_t1 = False
            try:
                valid_env_tool_t1 = validate_coder_env(provider_id='t1')
                if not valid_env_tool_t1:
                    console.print(f'[red]Detected vLLM - tool calling- misconfigured[/red] named: [cyan]t1[/cyan].\n  👉 Please check the config: [cyan]{coder_config_file}[/cyan]')
            except Exception:
                console.print(f'[red]Detected Invalid vLLM - tool calling[/red] with vLLM: [cyan]t1[/cyan].\n\n  👉 Please check the config: [cyan]{coder_config_file}[/cyan]')
            console.print(f"\n  Checking env var CODER_CONFIG_FILE\n\n  [yellow]{coder_config_file}[/yellow]\n")
            num_missing = 0
            if valid_env_vllm_small:
                console.print("  [green]vllm-small[/green] - [cyan]chat:latest[/cyan] - [green]active ✔[/green]")
            else:
                num_missing += 1
                console.print("  [red]vllm-small[/red] - [cyan]chat:latest[/cyan] - [red]offline[/red]")
            if valid_env_tool_t1:
                console.print("  [green]tool-calling[/green] - [cyan]openai/google/functiongemma-270m-it[/cyan] - [green]active ✔[/green]")
            else:
                console.print("  [red]tool-calling[/red] - [cyan]openai/google/functiongemma-270m-it[/cyan] - [red]offline[/red]")
                num_missing += 1
            if num_missing > 0:
                console.print(f"\n  👉 [yellow]Detected {num_missing} vLLM instances in the CODER_CONFIG_FILE is[/yellow] [red]missing[/red] or [purple]incorrect[/purple] - [cyan]{coder_config_file}[/cyan]")
        else:
            console.print("  [red]Warning - environment variable CODER_CONFIG_FILE is missing[/red]  👉 Please run [cyan]export CODER_CONFIG_FILE=PATH/coder.json[/cyan] then restart with [cyan]oat[/cyan]")

    console.print()


def _run_git(console: Console, cwd: str, *args: str, max_lines: int = 30) -> str | None:
    """Run a git command and return output, or None on failure."""
    try:
        import subprocess
        result = subprocess.run(
            ["git"] + list(args),
            capture_output=True, text=True, cwd=cwd, timeout=10,
        )
        if result.returncode != 0:
            return result.stderr.strip() if result.stderr.strip() else None
        output = result.stdout.strip()
        lines = output.split('\n')
        if len(lines) > max_lines:
            output = '\n'.join(lines[:max_lines]) + f'\n  … ({len(lines) - max_lines} more lines)'
        return output
    except Exception as e:
        console.print(f"### Sorry!! Failed _run_git with error:\n```\n{traceback.format_exc()}\n```\n")
        return f"error: {e}"


def _print_diff(console: Console, cwd: str):
    """Show git diff (staged + unstaged)."""
    console.print()
    diff = _run_git(console, cwd, "diff", max_lines=50)
    staged = _run_git(console, cwd, "diff", "--staged", max_lines=50)

    if staged:
        console.print(f"  [bold cyan]staged[/bold cyan]")
        console.print(staged)
    if diff:
        if staged:
            console.print()
        console.print(f"  [bold cyan]unstaged[/bold cyan]")
        console.print(diff)
    if not diff and not staged:
        console.print(f"  [dim]clean — no changes[/dim]")
    console.print()


def _print_log(console: Console, cwd: str):
    """Show recent git log."""
    console.print()
    log_output = _run_git(console, cwd, "log", "--oneline", "--graph", "-15")
    if log_output:
        console.print(log_output)
    else:
        console.print(f"  [dim]no git history[/dim]")
    console.print()


async def _print_history(console: Console):
    """List recent sessions."""
    from oats.session.session import list_sessions
    sessions = await list_sessions()
    if not sessions:
        console.print(f"  [dim]no sessions found[/dim]")
        return

    sessions_sorted = sorted(sessions, key=lambda s: s.time.updated, reverse=True)[:15]

    console.print()
    for s in sessions_sorted:
        age = _format_age(s.time.updated)
        tokens = _format_tokens(s.total_tokens)
        console.print(
            f"  [dim]{s.id[:8]}[/dim]  {s.title[:45]:<45}  "
            f"[dim]{s.message_count:>3} msgs  {tokens:>5} tok  {age}[/dim]"
        )
    console.print()


def _format_age(dt) -> str:
    """Format a datetime as a human-readable age string."""
    from oats.date import utc
    now = utc()
    delta = now - dt
    secs = int(delta.total_seconds())
    if secs < 60:
        return "just now"
    elif secs < 3600:
        return f"{secs // 60}m ago"
    elif secs < 86400:
        return f"{secs // 3600}h ago"
    else:
        return f"{secs // 86400}d ago"

def _turn_separator(console: Console):
    """Print a subtle separator between turns."""
    console.print(f"  [dim]{SYM_SEP * 50}[/dim]")

def _format_tool_args(tool_name: str, args: dict) -> str:
    """Format tool arguments for concise display."""
    if tool_name == "read":
        return args.get("file_path", str(args))[:80]
    elif tool_name == "write":
        fp = args.get("file_path", "?")
        content_len = len(args.get("content", ""))
        return f"{fp} ({content_len} chars)"
    elif tool_name in ("edit", "multiedit"):
        fp = args.get("file_path", "?")
        return fp
    elif tool_name == "bash":
        cmd = args.get("command", str(args))[:80]
        return cmd
    elif tool_name == "glob":
        return args.get("pattern", str(args))[:80]
    elif tool_name == "grep":
        pat = args.get("pattern", "?")
        path = args.get("path", ".")
        return f"{pat} in {path}"[:80]
    elif tool_name == "tool_search":
        return args.get("query", str(args))[:80]
    elif tool_name == "lsp":
        action = args.get("action", "?")
        return action[:80]
    elif tool_name in ("agent", "agent_status"):
        desc = args.get("description", args.get("prompt", str(args)))[:60]
        return desc
    elif tool_name in ("plan_enter", "plan_exit"):
        return args.get("reason", "")[:60]
    elif tool_name in ("memory_write", "memory_read", "memory_delete"):
        key = args.get("key", args.get("name", ""))[:40]
        return key
    elif tool_name in ("webfetch", "websearch"):
        return args.get("url", args.get("query", str(args)))[:80]
    else:
        # Generic: show first string value
        for v in args.values():
            if isinstance(v, str) and v:
                return v[:60]
        return str(args)[:60]

# ── /browse — render web pages in terminal ───────────────────────────

def _browse_url(console: Console, url: str):
    """Fetch a URL and render it as formatted text in the terminal."""
    if not url.startswith(("http://", "https://")):
        url = "https://" + url

    # Try lynx first (best HTML rendering)
    import shutil
    import subprocess
    from rich.panel import Panel
    lynx = shutil.which("lynx")
    if lynx:
        try:
            result = subprocess.run(
                [lynx, "-dump", "-width", str(min(console.width or 80, 120)),
                 "-nolist", "-nonumbers", url],
                capture_output=True, text=True, timeout=15,
            )
            if result.returncode == 0 and result.stdout.strip():
                console.print()
                # Render through Rich for consistent styling
                content = result.stdout.strip()
                # Limit output to avoid flooding
                lines = content.split("\n")
                if len(lines) > 200:
                    content = "\n".join(lines[:200])
                    content += f"\n\n... ({len(lines) - 200} more lines, use lynx for full page)"
                console.print(Panel(content, title=f"[bold]{url}[/bold]", border_style="dim"))
                return
        except subprocess.TimeoutExpired:
            console.print(f"  [yellow]{SYM_WARN} lynx timed out, trying httpx...[/yellow]")
        except Exception:
            pass

    # Fallback: fetch with httpx and render as markdown
    try:
        import httpx
        with httpx.Client(timeout=15, follow_redirects=True) as client:
            resp = client.get(url, headers={"User-Agent": "Mozilla/5.0 (compatible; coder/2.0)"})
            resp.raise_for_status()
            content_type = resp.headers.get("content-type", "")

            if "json" in content_type:
                console.print()
                console.print(Panel(resp.text[:5000], title=f"[bold]{url}[/bold]", border_style="dim"))
                return

            # Strip HTML to get readable text
            text = resp.text
            # Remove scripts and styles
            text = re.sub(r'<(script|style)[^>]*>.*?</\1>', '', text, flags=re.DOTALL | re.IGNORECASE)
            # Remove tags
            text = re.sub(r'<[^>]+>', ' ', text)
            # Collapse whitespace
            text = re.sub(r'\s+', ' ', text).strip()
            # Decode entities
            import html
            text = html.unescape(text)

            if text:
                lines = text[:8000].split(". ")
                formatted = ".\n".join(lines)
                console.print()
                console.print(Panel(formatted[:5000], title=f"[bold]{url}[/bold]", border_style="dim"))
            else:
                console.print(f"  [yellow]{SYM_WARN} no readable content at {url}[/yellow]")
    except Exception as e:
        console.print(f"  [red]{SYM_ERR} {e}[/red]")

# ── Streaming think-block filter ──────────────────────────────────────

class ThinkFilter:
    """
    Filters <think>...</think> blocks from streaming deltas.

    Shows a minimal indicator while the model reasons, then emits
    only the actionable content after </think>.
    """

    _OPEN = "<think>"
    _CLOSE = "</think>"

    def __init__(self):
        """Initialize the think filter with an empty buffer."""
        self._buf = ""
        self._think_shown = False

    def feed(self, delta: str) -> str:
        """Feed a text delta and return the filtered output.

        Accumulates the delta in the internal buffer and drains any
        complete think blocks, returning only non-think content.
        """
        self._buf += delta
        return self._drain()

    def _drain(self) -> str:
        """Drain the buffer, stripping complete think blocks and emitting safe content."""
        output = ""
        while True:
            open_idx = self._buf.find(self._OPEN)
            close_idx = self._buf.find(self._CLOSE)

            if open_idx != -1 and (close_idx == -1 or open_idx < close_idx):
                output += self._buf[:open_idx]
                if close_idx != -1 and close_idx > open_idx:
                    after = close_idx + len(self._CLOSE)
                    self._buf = self._buf[after:].lstrip("\n\r")
                    if not self._think_shown:
                        self._think_shown = True
                    output += "\r\033[K"
                    self._think_shown = False
                    continue
                else:
                    self._buf = self._buf[open_idx:]
                    if not self._think_shown:
                        self._think_shown = True
                    break
            elif close_idx != -1 and open_idx == -1:
                after = close_idx + len(self._CLOSE)
                self._buf = self._buf[after:].lstrip("\n\r")
                if self._think_shown:
                    output += "\r\033[K"
                    self._think_shown = False
                continue
            else:
                if not self._think_shown:
                    safe, held = self._split_safe(self._buf)
                    output += safe
                    self._buf = held
                break
        return output

    @staticmethod
    def _split_safe(buf: str) -> tuple[str, str]:
        """Split buffer into safe (no partial tags) and held (partial tag) parts."""
        for tag in ("<think>", "</think>"):
            for length in range(min(len(tag) - 1, len(buf)), 0, -1):
                if buf.endswith(tag[:length]):
                    return buf[:-length], buf[-length:]
        return buf, ""

    def flush(self) -> str:
        """Flush remaining buffer content, stripping any incomplete think blocks."""
        out = ""
        if self._think_shown:
            out += "\r\033[K"
        open_idx = self._buf.find(self._OPEN)
        if open_idx != -1:
            out += self._buf[:open_idx]
        else:
            out += self._buf
        self._buf = ""
        self._think_shown = False
        return out


def _strip_think_blocks(text: str) -> str:
    """Remove <think>...</think> blocks from text for clean Markdown rendering."""
    text = re.sub(r'<think>.*?</think>\s*', '', text, flags=re.DOTALL)
    text = re.sub(r'<think>.*$', '', text, flags=re.DOTALL)
    return text.lstrip('\n')

# ── Live status indicator ────────────────────────────────────────────

_SPINNER_FRAMES = ["⠋", "⠙", "⠹", "⠸", "⠼", "⠴", "⠦", "⠧", "⠇", "⠏"]

class _StatusTracker:
    """Animated status line shown while the LLM is generating."""

    def __init__(self, console: Console):
        """Initialize the status tracker with the given Rich console.

        Args:
            console: The Rich console to render the live status line on.
        """
        self._start = time.monotonic()
        self._input_tokens = 0
        self._output_tokens = 0
        self._phase = "thinking"
        self._frame = 0
        self._live: Live | None = None
        self._task: asyncio.Task | None = None
        self._console: Console = console

    def _render(self) -> Text:
        """Render the current status line as a Rich Text object."""
        elapsed = time.monotonic() - self._start
        frame = _SPINNER_FRAMES[self._frame % len(_SPINNER_FRAMES)]
        self._frame += 1

        parts = [f"  {frame} "]
        parts.append(f"{self._phase}")
        parts.append(f"  {elapsed:.0f}s")
        if self._output_tokens > 0:
            parts.append(f"  ↓ {_format_tokens(self._output_tokens)} tokens")

        txt = Text("".join(parts))
        txt.stylize("dim")
        return txt

    async def _tick(self):
        """Background loop that updates the live display every 100ms."""
        try:
            while True:
                if self._live is not None:
                    self._live.update(self._render())
                await asyncio.sleep(0.1)
        except asyncio.CancelledError:
            pass

    def start(self):
        """Start the animated status line and background tick task."""
        self._live = Live(self._render(), console=self._console, refresh_per_second=10, transient=True)
        self._live.start()
        self._task = asyncio.create_task(self._tick())

    def stop(self):
        """Stop the animated status line and cancel the background tick task."""
        if self._task is not None:
            self._task.cancel()
            self._task = None
        if self._live is not None:
            self._live.stop()
            self._live = None

    def set_phase(self, phase: str):
        """Set the current phase label (e.g. 'thinking', 'generating')."""
        self._phase = phase

    def add_tokens(self, input_tokens: int = 0, output_tokens: int = 0):
        """Accumulate input and output token counts for display."""
        self._input_tokens += input_tokens
        self._output_tokens += output_tokens

    def add_output_chars(self, n: int):
        """Estimate tokens from character count (~4 chars per token)."""
        self._output_tokens += max(1, n // 4)

def _get_provider_display() -> tuple[str, str]:
    """Get provider_id and model_id for display."""
    provider_id = os.getenv("VLLM_PROVIDER_ID", "vllm-small")
    model_id = os.getenv("VLLM_MODEL_ID", "hosted_vllm/chat:latest")
    return provider_id, model_id

def _print_help(console: Console):
    """Print available slash commands."""
    from rich.table import Table
    table = Table(show_header=False, box=None, padding=(0, 2), pad_edge=False)
    table.add_column("Command", style="bold cyan", min_width=20)
    table.add_column("Description", style="dim")

    commands = [
        ("/help", "Show this help"),
        ("/exit, /quit, /q", "Exit the session"),
        ("/clear", "Clear the screen"),
        ("/new", "Start a new session"),
        ("", ""),
        ("/mode", "Show current interaction mode"),
        ("/edit", "Supervised — ask before writes/bash (default)"),
        ("/auto", "Auto-approve all tool calls"),
        ("/plan", "Review-only — propose changes, no writes"),
        ("/caveman", "Terse output + auto-approve"),
        ("/approve", "Toggle auto-approve on/off"),
        ("", ""),
        ("/session", "Show session info"),
        ("/cost", "Show token usage for this session"),
        ("/tools", "List available tools"),
        ("/files", "Show files read/written this session"),
        ("/config", "Show active configuration"),
        ("/json <file>", "Read and display a JSON file (local or s3://)"),
        ("/profile", "Show feature profile (minimal/standard/full)"),
        ("", ""),
        ("/diff", "Show git diff (staged + unstaged)"),
        ("/log", "Show recent git log"),
        ("/compact", "Force context compaction"),
        ("", ""),
        ("/browse <url>", "Display a web page as text"),
        ("/browse -i <url>", "Interactive browser (Playwright)"),
        ("/browse -gui <url>", "Visual GUI browser (screenshots in terminal)"),
        ("/browse -scrape <url>", "Scrape page to JSON + Parquet + S3"),
        ("/browse -scrape -auth <url>", "Scrape with login (password hashed)"),
        ("", ""),
        ("/model", "Show current model"),
        ("/models", "List available models"),
        ("/switch <model>", "Switch model"),
        ("/provider <id>", "Switch provider"),
        ("/history", "List recent sessions"),
        ("", ""),
        ("! <cmd>", "Run a shell command"),
    ]
    for cmd, desc in commands:
        table.add_row(cmd, desc)

    console.print()
    console.print(table)
    console.print()
