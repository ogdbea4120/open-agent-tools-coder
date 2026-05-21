#!/usr/bin/env python3
"""
Interactive REPL for oats-enabled coder — local-first-tool-calling AI coding agent architecture.

Launch in any directory to get a multi-turn coding assistant powered by your local ai stack (we use vLLM atm).

Usage:
    ot                     # interactive mode
    ot -r last             # resume last session
    ot -m hosted_vllm/Qwen3-32B-AWQ
"""
from rich.console import Console

console = Console()
console.print(f"[yellow]Let's build together!! 🤗 🤖 🔨 🔧 [/yellow]\n[cyan]Starting up oats coder please wait...[/cyan]\nIf you hit an error, please open an issue so we can help fix it:\ngithub.com/district-solutions/open-agent-tools-coder/issues")

async def run_interactive(
    console: Console,
    provider_id: str | None = None,
    model_id: str | None = None,
    session_id: str | None = None,
    project_dir: str | None = None,
    auto_approve: bool = False,
    resume: str | None = None,
):
    """Main interactive REPL loop."""
    import os
    from oats.date import utc
    from oats.date import get_utc_str
    cwd = project_dir or os.getcwd()

    # Resolve provider/model
    if provider_id is None:
        provider_id = os.getenv("VLLM_PROVIDER_ID", "vllm-small")
    if model_id is None:
        model_id = os.getenv("VLLM_MODEL_ID", "hosted_vllm/chat:latest")

    # Set env so config picks it up
    os.environ["VLLM_PROVIDER_ID"] = provider_id
    os.environ["VLLM_MODEL_ID"] = model_id

    # Initialize tools
    from oats.tool.init_tools import init_tools
    init_tools()

    from oats.cli.tui.tui_consts import (
        SYM_OK,
        SYM_ERR,
        SYM_COMPACT,
    )

    # Load declarative plugins (no-op unless CODER_FEATURE_PLUGINS=1).
    try:
        from oats.plugins.loader import install as _install_plugins
        _install_plugins(model_id=model_id)
    except Exception:
        pass

    # Resolve or create session
    from oats.session.session import Session
    session: Session | None = None

    if resume:
        from oats.session.session import get_session
        from oats.session.session import list_sessions
        if resume == "last":
            sessions = await list_sessions()
            if sessions:
                latest = max(sessions, key=lambda s: s.time.updated)
                session = await get_session(latest.id)
                if session:
                    console.print(f"  [green]resumed session {session.id[:8]}[/green]")
        else:
            session = await get_session(resume)
            if session is None:
                sessions = await list_sessions()
                for info in sessions:
                    if info.id.startswith(resume):
                        session = await get_session(info.id)
                        break
            if session:
                console.print(f"  [green]resumed session {session.id[:8]}[/green]")
            else:
                console.print(f"  [yellow]session not found: {resume}, starting new[/yellow]")

    from pathlib import Path
    if session is None:
        now = utc()
        from oats.session.session import create_session
        session = await create_session(
            project_dir=Path(cwd),
            title=f"Interactive - {Path(cwd).name} - {now.strftime('%Y-%m-%d %H:%M')}",
            model_id=model_id,
            provider_id=provider_id,
        )

    from oats.session.processor import SessionProcessor
    processor = SessionProcessor(session)

    # Initialize interaction mode. Default → EDIT (supervised); -y/--auto → AUTO.
    from oats.session.modes import InteractionMode, set_mode, get_mode, describe
    if auto_approve:
        set_mode(InteractionMode.AUTO)
    else:
        set_mode(InteractionMode.EDIT)

    # Print banner
    import sys
    from oats.cli.tui.tui_banner import _print_banner
    _print_banner(console=console, cwd=cwd, session_id=session.id, provider_id=provider_id, model_id=model_id)
    m = get_mode()
    console.print(f"  [dim]mode:[/dim] [cyan]{m.value}[/cyan] [dim]— {describe(m)}. Switch with /edit /auto /plan /caveman[/dim]\n")

    # Setup prompt_toolkit session with history
    history_dir = Path.home() / ".local" / "share" / "coder" / "history"
    history_dir.mkdir(parents=True, exist_ok=True)
    history_file = history_dir / "interactive_history"

    # Key bindings: Alt+Enter for newline, Enter to submit
    from prompt_toolkit import PromptSession
    from prompt_toolkit.history import FileHistory
    from prompt_toolkit.formatted_text import HTML
    from prompt_toolkit.key_binding import KeyBindings
    from prompt_toolkit.keys import Keys
    bindings = KeyBindings()

    @bindings.add(Keys.Escape, Keys.Enter)
    def _newline(event):
        """Insert a newline on Alt+Enter instead of submitting."""
        event.current_buffer.insert_text('\n')

    prompt_session = PromptSession(
        history=FileHistory(str(history_file)),
        key_bindings=bindings,
        multiline=False,
        enable_history_search=True,
    )

    turn_count = 0
    # Images queued by /attach or /screenshot — sent with the next message
    _pending_images: list[dict[str, str]] = []

    # ── Ctrl+C state: first press cancels/warns, second within window exits ──
    _SIGINT_WINDOW = 2.0
    _ctrl_c = {"last_t": 0.0}
    import asyncio
    from typing import Optional
    _turn_task_ref: dict[str, Optional[asyncio.Task]] = {"task": None}

    try:
        import termios
        _saved_tty = termios.tcgetattr(sys.stdin.fileno())
    except Exception:
        termios = None  # type: ignore[assignment]
        _saved_tty = None

    def _restore_tty():
        """Restore the terminal to its saved state and run stty sane."""
        try:
            if _saved_tty is not None and termios is not None:
                termios.tcsetattr(sys.stdin.fileno(), termios.TCSADRAIN, _saved_tty)
        except Exception:
            pass
        try:
            import subprocess
            subprocess.run(["stty", "sane"], check=False, timeout=1)
        except Exception:
            pass

    def _sigint_should_exit() -> bool:
        """Return True if a second Ctrl+C was pressed within the exit window."""
        import time
        now = time.monotonic()
        recent = (now - _ctrl_c["last_t"]) < _SIGINT_WINDOW
        _ctrl_c["last_t"] = now
        return recent

    def _sigint_handler():
        """Handle SIGINT: cancel the current turn or exit on double Ctrl+C."""
        exit_now = _sigint_should_exit()
        t = _turn_task_ref["task"]
        busy = t is not None and not t.done()
        if exit_now:
            if busy:
                t.cancel()
            console.print("\n  [dim]goodbye[/dim]")
            _restore_tty()
            os._exit(0)
        if busy:
            t.cancel()
            console.print("\n  [yellow]cancelling turn — press Ctrl+C again within 2s to exit[/yellow]")
        else:
            console.print("\n  [yellow]press Ctrl+C again within 2s to exit[/yellow]")

    _loop = asyncio.get_event_loop()
    try:
        import signal
        _loop.add_signal_handler(signal.SIGINT, _sigint_handler)
    except (NotImplementedError, RuntimeError):
        pass

    while True:
        try:
            turn_label = f"{turn_count + 1}" if turn_count > 0 else ""
            mode_tag = f" <ansiyellow>[{get_mode().value}]</ansiyellow>"
            if turn_label:
                prompt_html = HTML(f'<ansicyan><b>coder</b></ansicyan>{mode_tag} <ansibrightblack>[{turn_label}]</ansibrightblack><b>❯</b> ')
            else:
                prompt_html = HTML(f'<ansicyan><b>coder</b></ansicyan>{mode_tag}<b>❯</b> ')

            user_input = await asyncio.get_event_loop().run_in_executor(
                None,
                lambda: prompt_session.prompt(prompt_html),
            )
        except EOFError:
            console.print("\n  [dim]goodbye[/dim]")
            break
        except KeyboardInterrupt:
            if _sigint_should_exit():
                console.print("\n  [dim]goodbye[/dim]")
                _restore_tty()
                break
            console.print("\n  [yellow]press Ctrl+C again within 2s to exit[/yellow]")
            continue

        user_input = user_input.strip()
        if not user_input:
            continue

        # ── Slash commands ─────────────────────────────────────────
        if user_input.startswith("/"):
            cmd = user_input.lower().split()[0]

            if cmd in ("/exit", "/quit", "/q"):
                console.print("  [dim]goodbye[/dim]")
                break

            elif cmd == "/help":
                from oats.cli.tui.tui_utils import _print_help
                _print_help(console=console)
                continue

            elif cmd in ("/mode", "/edit", "/auto", "/plan", "/caveman"):
                from oats.session.modes import (
                    InteractionMode, get_mode, set_mode, describe,
                )
                if cmd == "/mode":
                    m = get_mode()
                    console.print(f"  [dim]mode:[/dim] [cyan]{m.value}[/cyan] — {describe(m)}")
                else:
                    target = {
                        "/edit": InteractionMode.EDIT,
                        "/auto": InteractionMode.AUTO,
                        "/plan": InteractionMode.PLAN,
                        "/caveman": InteractionMode.CAVEMAN,
                    }[cmd]
                    set_mode(target)
                    console.print(f"  [green]mode → [cyan]{target.value}[/cyan][/green] [dim]({describe(target)})[/dim]")
                continue

            elif cmd == "/approve":
                from oats.cli.approval import (
                    get_approval_manager, ApprovalMode,
                )
                from oats.session.modes import (
                    InteractionMode, get_mode, set_mode,
                )
                mgr = get_approval_manager()
                if mgr.mode == ApprovalMode.AUTO:
                    set_mode(InteractionMode.EDIT)
                    console.print(f"  [green]approval: [cyan]supervised[/cyan][/green] [dim](asks before writes/bash)[/dim]")
                else:
                    set_mode(InteractionMode.AUTO)
                    console.print(f"  [green]approval: [cyan]auto[/cyan][/green] [dim](auto-approve all)[/dim]")
                continue

            elif cmd == "/clear":
                console.clear()
                from oats.cli.tui.tui_banner import _print_banner
                _print_banner(console=console, cwd=cwd, session_id=session.id, provider_id=provider_id, model_id=model_id)
                continue

            elif cmd == "/session":
                from oats.cli.tui.tui_banner import _print_session_info
                _print_session_info(console=console, session=session, turn_count=turn_count, provider_id=provider_id, model_id=model_id)
                continue

            elif cmd == "/cost":
                from oats.cli.tui.tui_banner import _print_cost
                _print_cost(console=console, session=session)
                continue

            elif cmd == "/config":
                from oats.cli.tui.tui_utils import _print_config
                _print_config(console=console)
                continue

            elif cmd == "/profile":
                from oats.core.profiles import get_profile, describe_profile
                profile = get_profile()
                groups = describe_profile()
                console.print(f"\n  [bold]Active profile:[/bold] [cyan]{profile.name}[/cyan]")
                console.print(f"  [dim]Set via CODER_PROFILE env var (minimal|standard|full|custom)[/dim]\n")
                for group, enabled in groups.items():
                    icon = "[green]\u2713[/green]" if enabled else "[dim]\u2717[/dim]"
                    console.print(f"  {icon}  {group}")
                console.print(f"\n  [dim]Override any group: CODER_FEATURE_<GROUP>=0|1[/dim]\n")
                continue

            elif cmd == "/files":
                from oats.cli.tui.tui_banner import _print_files
                _print_files(console=console, processor=processor)
                continue

            elif cmd == "/diff":
                from oats.cli.tui.tui_utils import _print_diff
                _print_diff(console=console, cwd=cwd)
                continue

            elif cmd == "/log":
                from oats.cli.tui.tui_utils import _print_log
                _print_log(console=console, cwd=cwd)
                continue

            elif cmd == "/history":
                from oats.cli.tui.tui_utils import _print_history
                await _print_history(console=console)
                continue

            elif cmd == "/tools":
                from oats.cli.tui.tui_utils import _print_tools
                _print_tools(console=console)
                continue

            elif cmd == "/model":
                from oats.cli.tui.tui_consts import _short_model
                console.print(f"  [dim]provider:[/dim] {provider_id}")
                console.print(f"  [dim]model:[/dim]    {_short_model(model_id)}")
                continue

            elif cmd == "/new":
                now = utc()
                from oats.session.session import create_session
                session = await create_session(
                    project_dir=Path(cwd),
                    title=f"Interactive - {Path(cwd).name} - {now.strftime('%Y-%m-%d %H:%M')}",
                    model_id=model_id,
                    provider_id=provider_id,
                )
                processor = SessionProcessor(session)
                turn_count = 0
                console.print(f"  [green]new session {session.id[:8]}[/green]")
                continue

            elif cmd == "/models":
                from oats.provider.models import list_models as _lm
                models_list = _lm()
                current_provider = None
                console.print()
                for m in sorted(models_list, key=lambda x: (x.provider_id, x.name)):
                    if m.provider_id != current_provider:
                        current_provider = m.provider_id
                        console.print(f"  [bold cyan]{current_provider}[/bold cyan]")
                    marker = " [green]◀[/green]" if m.id == model_id else ""
                    console.print(f"    [dim]{m.id}[/dim]{marker}")
                console.print()
                continue

            elif cmd == "/switch":
                from oats.cli.tui.tui_consts import _short_model
                parts = user_input.split(maxsplit=1)
                if len(parts) < 2:
                    console.print(f"  [yellow]usage: /switch <model_id>[/yellow]")
                    console.print(f"  [dim]current: {_short_model(model_id)}[/dim]")
                else:
                    new_model = parts[1].strip()
                    model_id = new_model
                    os.environ["VLLM_MODEL_ID"] = model_id
                    session.info.model_id = model_id
                    import oats.core.config as _cfg
                    _cfg._config = None
                    console.print(f"  [green]switched to {_short_model(model_id)}[/green]")
                continue

            elif cmd == "/provider":
                parts = user_input.split(maxsplit=1)
                if len(parts) < 2:
                    console.print(f"  [yellow]usage: /provider <provider_id>[/yellow]")
                    console.print(f"  [dim]current: {provider_id}[/dim]")
                else:
                    new_provider = parts[1].strip()
                    provider_id = new_provider
                    os.environ["VLLM_PROVIDER_ID"] = provider_id
                    session.info.provider_id = provider_id
                    import oats.core.config as _cfg
                    import oats.provider.provider as _prov
                    _cfg._config = None
                    _prov._registry = None
                    console.print(f"  [green]switched to {provider_id}[/green]")
                continue

            elif cmd == "/compact":
                from oats.session.compaction import ConversationCompactor
                ctx_len = int(os.getenv('CODER_CTX_LEN', '262100'))
                compactor = ConversationCompactor(
                    model_context_length=ctx_len,
                    provider_id=provider_id,
                    model_id=model_id,
                )
                session.messages = await compactor.compact(session.messages, session.id)
                console.print(f"  [green]{SYM_COMPACT} compacted to {len(session.messages)} messages[/green]")
                continue

            elif cmd == "/browse":
                from oats.core.profiles import is_feature_enabled
                if not is_feature_enabled("browser") and not is_feature_enabled("web_tools"):
                    console.print(f"  [yellow]browser feature is disabled in current profile[/yellow]")
                    console.print(f"  [dim]enable with: CODER_FEATURE_BROWSER=1 or CODER_PROFILE=full[/dim]")
                    continue
                parts = user_input.split(maxsplit=1)
                if len(parts) < 2:
                    console.print(f"  [yellow]usage: /browse <url>[/yellow]")
                    console.print(f"  [dim]  /browse <url>          fetch and display as text[/dim]")
                    console.print(f"  [dim]  /browse -i <url>       interactive browser (Playwright)[/dim]")
                    console.print(f"  [dim]  /browse -gui <url>     visual GUI browser (screenshots)[/dim]")
                    console.print(f"  [dim]  /browse -scrape <url>  scrape page to JSON + Parquet + S3[/dim]")
                    console.print(f"  [dim]  /browse -scrape -auth <url>  scrape with login prompt[/dim]")
                else:
                    arg = parts[1].strip()
                    if arg.startswith("-scrape"):
                        # Scrape mode
                        scrape_arg = arg[7:].strip()
                        with_auth = False
                        if scrape_arg.startswith("-auth"):
                            with_auth = True
                            scrape_arg = scrape_arg[5:].strip()
                        browse_url = scrape_arg
                        if not browse_url:
                            console.print(f"  [yellow]usage: /browse -scrape [-auth] <url>[/yellow]")
                        else:
                            from oats.cli.scraper import run_scrape_browser
                            await run_scrape_browser(
                                browse_url,
                                session_id=session.id,
                                with_auth=with_auth,
                            )
                    elif arg.startswith("-gui"):
                        # Visual GUI browser mode
                        browse_url = arg[4:].strip().lstrip()
                        if not browse_url:
                            console.print(f"  [yellow]usage: /browse -gui <url>[/yellow]")
                        else:
                            from oats.cli.browser import run_gui_browser
                            await run_gui_browser(browse_url, session_id=session.id)
                    elif arg.startswith("-i"):
                        # Interactive browser mode
                        browse_url = arg[2:].strip().lstrip()
                        if not browse_url:
                            console.print(f"  [yellow]usage: /browse -i <url>[/yellow]")
                        else:
                            from oats.cli.browser import run_interactive_browser
                            await run_interactive_browser(browse_url, session_id=session.id)
                    else:
                        from oats.cli.tui.tui_utils import _browse_url
                        _browse_url(console=console, url=arg)
                continue

            else:
                # Plugin-registered slash commands (via PluginContext.register_slash_command).
                from oats.plugins.loader import SlashContext, get_slash_commands
                try:
                    _plugin_cmds = get_slash_commands()
                except Exception:
                    _plugin_cmds = {}
                if cmd in _plugin_cmds:
                    args_str = user_input[len(cmd):].strip()
                    sc = _plugin_cmds[cmd]
                    sctx = SlashContext(cwd=Path(cwd), console=console, session=session)
                    try:
                        await sc.handler(args_str, sctx)
                    except Exception as e:
                        console.print(f"  [red]{SYM_ERR} /{sc.name} failed: {e}[/red]")
                    continue
                console.print(f"  [yellow]unknown: {cmd} — /help for commands[/yellow]")
                continue

        # ── Shell escape ───────────────────────────────────────────
        if user_input.startswith("!"):
            shell_cmd = user_input[1:].strip()
            if shell_cmd:
                import subprocess
                try:
                    result = subprocess.run(
                        shell_cmd, shell=True, capture_output=True, text=True,
                        cwd=cwd, timeout=60,
                    )
                    if result.stdout:
                        console.print(result.stdout, end="")
                    if result.stderr:
                        console.print(f"[red]{result.stderr}[/red]", end="")
                except subprocess.TimeoutExpired:
                    console.print(f"  [red]{SYM_ERR} timed out[/red]")
                except Exception as e:
                    console.print(f"  [red]{SYM_ERR} {e}[/red]")
            continue

        # ── Process message ────────────────────────────────────────
        turn_count += 1
        from oats.cli.tui.tui_utils import _turn_separator
        _turn_separator(console=console)
        from oats.cli.approval import get_approval_manager, ApprovalMode
        turn_auto_approve = get_approval_manager().mode == ApprovalMode.AUTO
        from oats.cli.process_message import process_message
        turn_task = _loop.create_task(process_message(console=console, processor=processor, message=user_input, session=session, auto_approve=turn_auto_approve, images=[]))
        _turn_task_ref["task"] = turn_task
        try:
            await turn_task
        except asyncio.CancelledError:
            console.print("  [yellow]turn cancelled[/yellow]")
        except KeyboardInterrupt:
            if _sigint_should_exit():
                console.print("  [dim]goodbye[/dim]")
                _restore_tty()
                break
            console.print("  [yellow]turn cancelled — press Ctrl+C again within 2s to exit[/yellow]")
        finally:
            _turn_task_ref["task"] = None
        console.print()

def main():
    """Entry point for the interactive CLI."""
    import asyncio
    import os
    import argparse
    parser = argparse.ArgumentParser(description="Run the Open Agent Tools Coder in Interactive Agentic TUI mode")
    parser.add_argument("-p", "--provider", help="Provider ID", default=None)
    parser.add_argument("-m", "--model", help="Model ID", default=None)
    parser.add_argument("-d", "--dir", help="Project directory", default=None)
    parser.add_argument("-r", "--resume", help="Resume session (ID or 'last')", default=None)
    parser.add_argument("-y", "--auto", action="store_true", help="Start in AUTO mode (auto-approve all tools)")
    parser.add_argument("--no-approve", action="store_true", help="(deprecated; default) Start in EDIT mode")
    args = parser.parse_args()
    asyncio.run(run_interactive(
        console=console,
        provider_id=args.provider,
        model_id=args.model,
        project_dir=args.dir,
        resume=args.resume,
        auto_approve=args.auto,
    ))

if __name__ == "__main__":
    main()
