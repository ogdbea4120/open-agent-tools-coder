"""
MCP server configuration loader.

Loads MCP server definitions from a JSON config file that can be placed in:
1. .coder/mcp_servers.json (project-level)
2. ~/.config/coder/mcp_servers.json (user-level)
3. Path from MCP_SERVERS_CONFIG env var

Eventually this could be managed via a web app, but for now it's file-based.

Environment Variable API Key Resolution
---------------------------------------

For security, API keys in header values can reference environment variables instead
of containing plaintext tokens. The pattern is::

    "headers": {
        "Authorization": "Bearer MCP_SERVER_API_KEY_PYTHON_SOFTWARE_ENGINEER"
    }

At load time, the config resolver detects values matching the pattern
``Bearer MCP_SERVER_API_KEY_<SERVER_NAME>`` and replaces them with the actual
environment variable value. The env var name is derived from the server name:

    - Server: python_software_engineer
    - Env var: MCP_SERVER_API_KEY_PYTHON_SOFTWARE_ENGINEER

If the env var is not set, a warning is logged and the original value is retained
(backward compatibility).

This allows the JSON config file to be safely committed to version control.
"""
from __future__ import annotations

import json
import os
import re
from pathlib import Path
from typing import Any

from oats.log import cl
from oats.mcp.models import MCPServerConfig, MCPServersFile, MCPTransport

log = cl("mcp.config")

# Pattern to detect env var placeholders in header values
# Matches: "Bearer MCP_SERVER_API_KEY_<SERVER_NAME>"
_ENV_VAR_PATTERN = re.compile(r"^Bearer\s+MCP_SERVER_API_KEY_(.+)$", re.IGNORECASE)


def _resolve_env_vars_in_headers(
    server_name: str, headers: dict[str, str]
) -> dict[str, str]:
    """
    Resolve environment variable placeholders in header values.

    Scans all header values for the pattern ``Bearer MCP_SERVER_API_KEY_<SERVER_NAME>``
    and replaces them with the actual environment variable value.

    Args:
        server_name: The MCP server name (used to derive the env var name).
        headers: The headers dict to resolve.

    Returns:
        A new headers dict with resolved values.

    Env var naming convention:
        Server: python_software_engineer
        Env var: MCP_SERVER_API_KEY_PYTHON_SOFTWARE_ENGINEER

    If the env var is not set, a warning is logged and the original value is kept
    (backward compatibility with hardcoded tokens).
    """
    resolved = dict(headers)
    env_prefix = "MCP_SERVER_API_KEY_"
    env_var_name = f"{env_prefix}{server_name.upper()}"

    for key, value in resolved.items():
        match = _ENV_VAR_PATTERN.match(value)
        if match:
            placeholder_server = match.group(1)
            # Derive the expected env var name from the placeholder
            expected_env_var = f"{env_prefix}{placeholder_server.upper()}"
            actual_value = os.getenv(expected_env_var)

            if actual_value:
                log.info(
                    f"env_var_resolved: server={server_name} header={key} "
                    f"env_var={expected_env_var}"
                )
                resolved[key] = actual_value
            else:
                log.warning(
                    f"env_var_not_set: server={server_name} header={key} "
                    f"env_var={expected_env_var} "
                    f"falling_back_to_placeholder"
                )
                # Keep the original placeholder value for backward compatibility
                # If the user has a hardcoded token in the JSON, it will still work
                pass

    return resolved


def load_mcp_config(project_dir: Path | None = None) -> MCPServersFile:
    """
    Load MCP server configuration from the first available source.

    Priority:
    1. MCP_SERVERS_CONFIG env var
    2. .coder/mcp_servers.json (project)
    3. ~/.config/coder/mcp_servers.json (user)

    After loading, resolves environment variable placeholders in server headers
    so that API keys are never stored as plaintext in the config file.
    """
    candidates = []

    env_path = os.getenv("MCP_SERVERS_CONFIG")
    if env_path:
        candidates.append(Path(env_path))

    if project_dir:
        candidates.append(project_dir / ".coder" / "mcp_servers.json")

    candidates.append(Path.home() / ".config" / "coder" / "mcp_servers.json")

    for path in candidates:
        if path.exists():
            try:
                data = json.loads(path.read_text())
                config = MCPServersFile(**data)
                # Resolve env var placeholders in all server headers
                for server_name, server_config in config.servers.items():
                    if server_config.headers:
                        config.servers[server_name].headers = _resolve_env_vars_in_headers(
                            server_name, server_config.headers
                        )
                log.info(f"loaded_mcp_config: {path} ({len(config.servers)} servers)")
                return config
            except Exception as e:
                log.warning(f"failed_to_load_mcp_config: {path}: {e}")

    log.info("no_mcp_config_found, using empty config")
    return MCPServersFile()


def save_mcp_config(config: MCPServersFile, path: Path) -> None:
    """Save MCP server configuration to a JSON file."""
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(config.model_dump(), indent=2))
    log.info(f"saved_mcp_config: {path}")


def add_server_to_config(
    name: str,
    url: str | None = None,
    command: str | None = None,
    description: str = "",
    transport: str = "http",
    tags: list[str] | None = None,
    project_dir: Path | None = None,
) -> MCPServersFile:
    """Add a new MCP server to the configuration."""
    config = load_mcp_config(project_dir)

    server = MCPServerConfig(
        name=name,
        description=description,
        transport=MCPTransport(transport),
        url=url,
        command=command,
        tags=tags or [],
    )

    config.servers[name] = server

    # Save to project-level config
    save_path = (project_dir or Path.cwd()) / ".coder" / "mcp_servers.json"
    save_mcp_config(config, save_path)

    return config


def create_default_mcp_config(project_dir: Path) -> Path:
    """Create a default mcp_servers.json with example structure."""
    config = MCPServersFile(
        version="1.0",
        servers={
            "litellm": MCPServerConfig(
                name="litellm",
                description="LiteLLM proxy for multi-provider LLM access and MCP tool management",
                transport=MCPTransport.HTTP,
                url=os.getenv("LITELLM_API_URL", "https://litellm-api.up.railway.app"),
                tags=["llm", "chat", "completions", "mcp"],
            ),
        },
    )

    save_path = project_dir / ".coder" / "mcp_servers.json"
    save_mcp_config(config, save_path)
    return save_path
