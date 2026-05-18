"""
Plugin loader.

Given a list of ``PluginManifest`` records, filters by activation gates,
imports each plugin's entrypoint module lazily, and calls its ``activate``
function with a :class:`PluginContext` that exposes the stable extension API.

**Contract for plugin authors:**

- Put a ``oats.plugins.json`` in your plugin directory.
- Ship a Python module matching ``entrypoint`` (default ``plugin.py``).
- Export an ``activate(ctx: PluginContext) -> None`` function. Calling
  ``ctx.register_tool``, ``ctx.register_toolset``, or
  ``ctx.register_handler`` is how you add capabilities. Do *not* touch
  global state directly — the context is the API, keeping plugins portable
  if internals change.

Idempotency: :func:`install` tracks which plugin ids have already been
activated so subsequent calls are no-ops, even across process reloads in a
single session.
"""
from __future__ import annotations

import importlib
import importlib.machinery
import importlib.util
import sys
import threading
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Awaitable, Callable, Iterable

from oats.core.features import _is_enabled
from oats.core.profiles import is_feature_enabled
from oats.hook.engine import HookEngine, HookEvent, HookHandler, HookResult, HookContext
from oats.log import cl
from oats.plugins.manifest import PluginManifest, discover_manifests
from oats.tool.registry import Tool, get_tool_registry

log = cl("plugins.loader")


# ── Slash-command extension registry ───────────────────────────────────
# Plugins may register user-facing /commands via PluginContext.register_slash_command.
# The interactive REPL consults this registry when a /word doesn't match a
# built-in handler. Handlers are async and receive (args_str, ctx).

@dataclass
class SlashContext:
    """Minimal context for plugin-registered slash handlers.

    Fields are keyword-only extensible — new fields can be added without
    breaking existing handlers that only read what they need.
    """
    cwd: Path
    console: Any  # rich.Console, kept untyped to avoid hard-importing rich here
    session: Any = None


SlashHandler = Callable[[str, SlashContext], Awaitable[None]]


@dataclass
class SlashCommand:
    """A user-facing /command registered by a plugin.

    Attributes:
        name: The command name (e.g. ``/vi``).
        handler: Async callable ``(args_str, SlashContext) -> None``.
        help_usage: Short usage string shown in ``/help`` (e.g. ``/vi [path]``).
        help_desc: Human-readable description of the command.
        plugin_id: ID of the plugin that registered this command.
    """
    name: str  # e.g. "/vi"
    handler: SlashHandler
    help_usage: str  # e.g. "/vi [path]"
    help_desc: str
    plugin_id: str


_slash_commands: dict[str, SlashCommand] = {}
_slash_lock = threading.Lock()


def get_slash_commands() -> dict[str, SlashCommand]:
    """Snapshot of registered slash commands. Read-only for callers."""
    with _slash_lock:
        return dict(_slash_commands)


def plugins_enabled() -> bool:
    """Master gate for the plugin system."""
    return _is_enabled("CODER_FEATURE_PLUGINS", False)


@dataclass
class PluginContext:
    """Stable extension API handed to each plugin's ``activate`` function.

    Plugins should treat this as their *only* coupling to oats internals.
    If the loader changes how registries or hooks are wired, the context's
    method surface stays the same.
    """
    manifest: PluginManifest

    def register_tool(self, tool: Tool, toolset: str | Iterable[str] | None = None) -> None:
        """Register a :class:`Tool` with the global tool registry.

        Optionally groups the tool under one or more toolset names.
        Falls back gracefully if the registry doesn't support toolsets.

        Args:
            tool: The tool instance to register.
            toolset: Optional toolset name(s) to associate with the tool.
        """
        reg = get_tool_registry()
        try:
            reg.register(tool, toolset=toolset)
        except TypeError:
            # Older ToolRegistry without toolset kwarg — skip toolset grouping.
            reg.register(tool)
        log.info(f"plugin_registered_tool id={self.manifest.id} tool={tool.name} toolset={toolset}")

    def register_toolset(
        self,
        name: str,
        *,
        members: Iterable[str] | None = None,
        includes: Iterable[str] | None = None,
    ) -> None:
        """Register a named toolset with the global tool registry.

        A toolset groups related tools so they can be enabled or disabled
        together. No-op if the registry doesn't support toolsets.

        Args:
            name: The toolset name.
            members: Optional list of tool names belonging to this toolset.
            includes: Optional list of other toolset names to include.
        """
        reg = get_tool_registry()
        rt = getattr(reg, "register_toolset", None)
        if rt is None:
            log.debug(f"plugin_toolset_skipped id={self.manifest.id} toolset={name} (registry has no register_toolset)")
            return
        rt(name, members=members, includes=includes)
        log.info(f"plugin_registered_toolset id={self.manifest.id} toolset={name}")

    def register_slash_command(
        self,
        name: str,
        handler: SlashHandler,
        *,
        usage: str | None = None,
        description: str = "",
    ) -> None:
        """Register a user-facing /command handled inside the interactive REPL.

        ``name`` must start with ``/`` (case-insensitive). Later registrations
        for the same name win, with a warning — keeps plugin reloads sane in dev.
        """
        key = name.lower().strip()
        if not key.startswith("/"):
            raise ValueError(f"slash command must start with '/': {name!r}")
        with _slash_lock:
            if key in _slash_commands:
                log.warn(f"plugin_slash_override name={key} old={_slash_commands[key].plugin_id} new={self.manifest.id}")
            _slash_commands[key] = SlashCommand(
                name=key,
                handler=handler,
                help_usage=usage or key,
                help_desc=description,
                plugin_id=self.manifest.id,
            )
        log.info(f"plugin_registered_slash id={self.manifest.id} name={key}")

    def register_handler(
        self,
        event: HookEvent,
        fn: HookHandler,
        matcher: str | None = None,
        name: str | None = None,
    ) -> None:
        """Register a hook handler on the global :class:`HookEngine`.

        The handler is registered under a name derived from the plugin id
        and the function's ``__name__`` (or the explicit ``name`` argument).

        Args:
            event: The hook event to listen for.
            fn: The async handler callable.
            matcher: Optional matcher string to scope the handler.
            name: Optional explicit name for the handler registration.
        """
        HookEngine.register_global(
            event, fn, matcher=matcher,
            name=name or f"{self.manifest.id}:{getattr(fn, '__name__', 'handler')}",
        )
        log.info(f"plugin_registered_hook id={self.manifest.id} event={event.value}")


# Module-level state — tracks what's already been activated so ``install()``
# is idempotent when called from multiple entry points (CLI, tests, etc.).
_loaded_ids: set[str] = set()
_load_lock = threading.Lock()


def _filter(
    manifests: Iterable[PluginManifest],
    *,
    model_id: str | None,
) -> list[PluginManifest]:
    """Apply activation gates without importing any plugin Python."""
    out: list[PluginManifest] = []
    for m in manifests:
        if not m.enabled_by_default:
            log.info(f"plugin_skipped_disabled id={m.id}")
            continue
        if not m.matches_model(model_id):
            log.info(f"plugin_skipped_model id={m.id} support={m.model_support} model={model_id}")
            continue
        missing = [f for f in m.on_features if not is_feature_enabled(f)]
        if missing:
            log.info(f"plugin_skipped_features id={m.id} missing={missing}")
            continue
        out.append(m)
    return out


def _import_entrypoint(manifest: PluginManifest):
    """Import ``<source_dir>/<entrypoint>.py`` with a synthetic module name.

    The plugin directory is registered as a synthetic package so that
    ``from .sibling import X`` inside the entrypoint resolves correctly.
    Plugin dirs don't need to be on ``sys.path`` — this keeps user-installed
    plugins isolated from the core namespace.
    """
    assert manifest.source_dir is not None
    entry_path = manifest.source_dir / f"{manifest.entrypoint}.py"
    if not entry_path.exists():
        raise FileNotFoundError(f"entrypoint missing: {entry_path}")

    pkg_name = f"oats_coder_plugin_{manifest.id.replace('-', '_')}"

    # Register the plugin directory as a synthetic package so that relative
    # imports inside the entrypoint (e.g. ``from .sources import X``) resolve
    # against the plugin dir.
    if pkg_name not in sys.modules:
        pkg_spec = importlib.machinery.ModuleSpec(pkg_name, loader=None, is_package=True)
        pkg_spec.submodule_search_locations = [str(manifest.source_dir)]
        pkg_module = importlib.util.module_from_spec(pkg_spec)
        pkg_module.__path__ = [str(manifest.source_dir)]
        sys.modules[pkg_name] = pkg_module

    mod_name = f"{pkg_name}.{manifest.entrypoint}"
    spec = importlib.util.spec_from_file_location(
        mod_name,
        entry_path,
        submodule_search_locations=None,
    )
    if spec is None or spec.loader is None:
        raise ImportError(f"could not build spec for {entry_path}")
    module = importlib.util.module_from_spec(spec)
    module.__package__ = pkg_name
    sys.modules[mod_name] = module
    spec.loader.exec_module(module)
    return module


def load_all(
    manifests: list[PluginManifest] | None = None,
    *,
    model_id: str | None = None,
) -> list[PluginManifest]:
    """Activate every manifest that passes the filter; return the activated list.

    ``manifests`` defaults to :func:`discover_manifests`. Errors while
    activating one plugin never take down another — they're logged and the
    plugin is skipped.
    """
    if manifests is None:
        manifests = discover_manifests()

    activated: list[PluginManifest] = []
    for m in _filter(manifests, model_id=model_id):
        with _load_lock:
            if m.id in _loaded_ids:
                log.info(f"plugin_already_loaded id={m.id}")
                continue
            try:
                module = _import_entrypoint(m)
                activate = getattr(module, "activate", None)
                if not callable(activate):
                    log.warn(f"plugin_missing_activate id={m.id}")
                    continue
                activate(PluginContext(manifest=m))
                _loaded_ids.add(m.id)
                activated.append(m)
                log.info(f"plugin_loaded id={m.id} version={m.version}")
            except Exception as e:
                log.error(f"plugin_load_failed id={m.id} err={e}")
    return activated


def install(*, model_id: str | None = None) -> list[PluginManifest]:
    """Entry point called from the interactive CLI. No-op unless the flag is on."""
    if not plugins_enabled():
        return []
    return load_all(model_id=model_id)


def reset_for_tests() -> None:
    """Testing hook — forget which plugins have been loaded."""
    with _load_lock:
        _loaded_ids.clear()
    with _slash_lock:
        _slash_commands.clear()
