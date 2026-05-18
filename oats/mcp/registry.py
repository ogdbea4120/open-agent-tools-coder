"""
MCP Server Registry.

Manages discovery, registration, and health checking of MCP servers.
This is the central authority for knowing what tools are available
across all connected MCP servers.

Key design: LiteLLM (and similar) uses per-function MCP endpoints
(e.g. ``GET /{mcp_function_name}/tools/list`` and
``POST /{mcp_function_name}/tools/call``), not a single
``/mcp-rest/tools/call`` for everything.

The registry discovers available MCP function names, then probes each
one for its tools, and stores the correct call_endpoint per tool.
"""
from __future__ import annotations

import asyncio
import os
import time
from pathlib import Path
from typing import Any, Optional

import httpx

from oats.log import cl
from oats.mcp.config import load_mcp_config
from oats.mcp.models import (
    MCPServerConfig,
    MCPServersFile,
    MCPToolDefinition,
    MCPTransport,
)

log = cl("mcp.registry")


class MCPServerRegistry:
    """
    Registry of MCP servers and their tools.

    Handles:
    - Loading server configs from mcp_servers.json
    - Discovering MCP function names from each server
    - Probing each function for tools via /{function_name}/tools/list
    - Building a route table: tool_name -> call_endpoint
    - Health checking servers
    - Providing a unified tool catalog
    """

    def __init__(self, project_dir: Path | None = None) -> None:
        """Initialize the registry, loading server configs from disk."""
        self._project_dir = project_dir or Path.cwd()
        self._servers: dict[str, MCPServerConfig] = {}
        self._tools: dict[str, MCPToolDefinition] = {}
        self._server_tools: dict[str, list[str]] = {}
        self._server_health: dict[str, bool] = {}
        # Route table: qualified_tool_name -> {call_endpoint, list_endpoint, mcp_function_name}
        self._route_table: dict[str, dict[str, str]] = {}
        self._last_discovery: float = 0.0
        self._discovery_ttl: float = 300.0

    async def initialize(self) -> None:
        """Load config and discover all tools."""
        config = load_mcp_config(self._project_dir)
        for name, server_config in config.servers.items():
            if server_config.enabled:
                self._servers[name] = server_config
        await self.discover_all()

    def add_server(self, name: str, config: MCPServerConfig) -> None:
        """Register a new MCP server in the registry."""
        self._servers[name] = config
        log.info(f"server_added: {name}")

    def remove_server(self, name: str) -> None:
        """Remove a server and all its tools from the registry."""
        if name in self._servers:
            del self._servers[name]
        tool_names = self._server_tools.pop(name, [])
        for tool_name in tool_names:
            self._tools.pop(tool_name, None)
            self._route_table.pop(tool_name, None)
        log.info(f"server_removed: {name} (removed {len(tool_names)} tools)")

    async def discover_all(self) -> dict[str, list[MCPToolDefinition]]:
        """Discover tools from all registered servers concurrently."""
        results: dict[str, list[MCPToolDefinition]] = {}

        tasks = []
        for name, config in self._servers.items():
            tasks.append(self._discover_server(name, config))

        discovered = await asyncio.gather(*tasks, return_exceptions=True)

        for name, result in zip(self._servers.keys(), discovered):
            if isinstance(result, Exception):
                log.warning(f"discovery_failed: {name}: {result}")
                self._server_health[name] = False
                results[name] = []
            else:
                results[name] = result
                self._server_health[name] = True

        self._last_discovery = time.time()
        log.info(
            f"discovery_complete: {len(self._servers)} servers, "
            f"{len(self._tools)} total tools, "
            f"{len(self._route_table)} routes"
        )
        return results

    async def _discover_server(
        self, name: str, config: MCPServerConfig
    ) -> list[MCPToolDefinition]:
        """Discover tools from a single MCP server."""
        tools: list[MCPToolDefinition] = []

        if config.transport in (MCPTransport.HTTP, MCPTransport.STREAMABLE_HTTP) and config.url:
            tools = await self._discover_http(name, config)
        elif config.transport == MCPTransport.STDIO and config.command:
            tools = await self._discover_stdio(name, config)

        # Register tools with qualified names
        self._server_tools[name] = []
        for tool in tools:
            tool.server_name = name
            qualified_name = f"{name}.{tool.name}"
            # Preserve the routing info before renaming
            mcp_fn = tool.mcp_function_name
            call_ep = tool.call_endpoint
            list_ep = tool.list_endpoint
            tool.name = qualified_name
            self._tools[qualified_name] = tool
            self._server_tools[name].append(qualified_name)
            # Store route
            self._route_table[qualified_name] = {
                "mcp_function_name": mcp_fn,
                "call_endpoint": call_ep,
                "list_endpoint": list_ep,
            }

        log.info(f"discovered: {name} -> {len(tools)} tools")
        return tools

    async def _discover_http(
        self, name: str, config: MCPServerConfig
    ) -> list[MCPToolDefinition]:
        """
        Discover tools from an HTTP MCP server.

        Strategy (in order):
        1. Try to discover MCP function names via known endpoints
        2. For each function name, probe /{function_name}/tools/list
        3. Fallback: parse OpenAPI spec for paths matching */tools/list pattern
        4. Last resort: extract operations from OpenAPI spec as tools
        """
        url = config.url.rstrip("/")
        headers = dict(config.headers)
        all_tools: list[MCPToolDefinition] = []

        async with httpx.AsyncClient(timeout=config.timeout_seconds) as client:
            # --- Strategy 1: Discover MCP function names ---
            mcp_function_names = await self._discover_mcp_functions(url, headers, client)

            if mcp_function_names:
                log.info(f"discovered_mcp_functions: {name} -> {len(mcp_function_names)} functions")
                # Probe each function for tools
                for fn_name in mcp_function_names:
                    tools = await self._probe_mcp_function(
                        url, fn_name, headers, client, name
                    )
                    all_tools.extend(tools)

                if all_tools:
                    return all_tools

            # --- Strategy 2: Parse OpenAPI spec for MCP patterns ---
            try:
                resp = await client.get(f"{url}/openapi.json", headers=headers)
                if resp.status_code == 200:
                    spec = resp.json()
                    # Look for paths matching /{something}/tools/list or /{something}/tools/call
                    mcp_tools = self._extract_mcp_tools_from_openapi(spec, url, name)
                    if mcp_tools:
                        return mcp_tools
                    # Last resort: extract all operations as tools
                    return self._tools_from_openapi(spec, url, name)
            except Exception as e:
                log.warning(f"openapi_fetch_failed: {name}: {e}")

        return []

    async def _discover_mcp_functions(
        self,
        base_url: str,
        headers: dict[str, str],
        client: httpx.AsyncClient,
    ) -> list[str]:
        """
        Discover available MCP function names from the server.

        Tries multiple approaches to find what MCP functions are registered.
        """
        function_names: list[str] = []

        # Approach 1: /v1/mcp/server (LiteLLM lists registered MCP servers)
        for endpoint in [
            f"{base_url}/v1/mcp/server",
            f"{base_url}/v1/mcp/discover",
            f"{base_url}/mcp/servers",
        ]:
            try:
                resp = await client.get(endpoint, headers=headers)
                if resp.status_code == 200:
                    data = resp.json()
                    names = self._parse_mcp_server_list(data)
                    if names:
                        return names
            except Exception:
                continue

        # Approach 2: Parse OpenAPI spec paths for /{name}/tools/list patterns
        try:
            resp = await client.get(f"{base_url}/openapi.json", headers=headers)
            if resp.status_code == 200:
                spec = resp.json()
                paths = spec.get("paths", {})
                for path in paths:
                    # Match patterns like /{something}/tools/list or /{something}/tools/call
                    if "/tools/list" in path or "/tools/call" in path:
                        parts = path.strip("/").split("/")
                        if len(parts) >= 2 and parts[-1] == "list" and parts[-2] == "tools":
                            fn_name = "/".join(parts[:-2])
                            if fn_name and fn_name not in ("mcp-rest", "v1/mcp"):
                                function_names.append(fn_name)
                        elif len(parts) >= 2 and parts[-1] == "call" and parts[-2] == "tools":
                            fn_name = "/".join(parts[:-2])
                            if fn_name and fn_name not in ("mcp-rest", "v1/mcp"):
                                function_names.append(fn_name)

                # Deduplicate
                function_names = list(dict.fromkeys(function_names))
        except Exception:
            pass

        return function_names

    def _parse_mcp_server_list(self, data: Any) -> list[str]:
        """Parse MCP server list response into function names."""
        names = []
        if isinstance(data, list):
            for item in data:
                if isinstance(item, str):
                    names.append(item)
                elif isinstance(item, dict):
                    name = item.get("name", item.get("server_name", item.get("id", "")))
                    if name:
                        names.append(name)
        elif isinstance(data, dict):
            # Could be {"servers": [...]} or {"data": [...]}
            for key in ("servers", "data", "result", "mcp_servers"):
                if key in data:
                    return self._parse_mcp_server_list(data[key])
            # Or direct name -> config mapping
            for key in data:
                if isinstance(data[key], dict):
                    names.append(key)
        return names

    async def _probe_mcp_function(
        self,
        base_url: str,
        function_name: str,
        headers: dict[str, str],
        client: httpx.AsyncClient,
        server_name: str,
    ) -> list[MCPToolDefinition]:
        """Probe a specific MCP function for its tools."""
        list_endpoint = f"/{function_name}/tools/list"
        call_endpoint = f"/{function_name}/tools/call"

        try:
            resp = await client.get(f"{base_url}{list_endpoint}", headers=headers)
            if resp.status_code == 200:
                data = resp.json()
                tools = self._parse_tools_response(data, server_name)
                # Attach routing info to each tool
                for tool in tools:
                    tool.mcp_function_name = function_name
                    tool.call_endpoint = call_endpoint
                    tool.list_endpoint = list_endpoint
                log.info(
                    f"probed_mcp_function: {function_name} -> {len(tools)} tools "
                    f"(call: {call_endpoint})"
                )
                return tools
        except Exception as e:
            log.debug(f"probe_failed: {function_name}: {e}")

        return []

    def _extract_mcp_tools_from_openapi(
        self,
        spec: dict[str, Any],
        base_url: str,
        server_name: str,
    ) -> list[MCPToolDefinition]:
        """
        Extract MCP tools from OpenAPI spec by finding paths that match
        the /{function_name}/tools/call pattern.

        Each matching path becomes a tool with the correct call_endpoint.
        """
        tools = []
        paths = spec.get("paths", {})

        # Group paths by function name
        # e.g. /search_investing_businesswire.../tools/call -> function = search_investing_businesswire...
        call_paths: dict[str, dict[str, Any]] = {}  # fn_name -> operation
        for path, methods in paths.items():
            if "/tools/call" in path:
                parts = path.strip("/").split("/")
                if len(parts) >= 3 and parts[-1] == "call" and parts[-2] == "tools":
                    fn_name = "/".join(parts[:-2])
                    for method, operation in methods.items():
                        if method.lower() == "post":
                            call_paths[fn_name] = operation
                            call_paths[fn_name]["_path"] = path

        for fn_name, operation in call_paths.items():
            tool = MCPToolDefinition(
                name=fn_name,
                description=operation.get(
                    "summary",
                    operation.get("description", f"MCP function: {fn_name}"),
                )[:500],
                parameters=_extract_params_schema(operation),
                server_name=server_name,
                mcp_function_name=fn_name,
                call_endpoint=f"/{fn_name}/tools/call",
                list_endpoint=f"/{fn_name}/tools/list",
                tags=["mcp", fn_name.split("_")[0] if "_" in fn_name else fn_name],
            )
            tools.append(tool)

        if tools:
            log.info(
                f"extracted_mcp_tools_from_openapi: {server_name} -> {len(tools)} MCP functions"
            )

        return tools

    def _tools_from_openapi(
        self, spec: dict[str, Any], base_url: str, server_name: str
    ) -> list[MCPToolDefinition]:
        """
        Last resort: extract regular API operations as tools.

        Each operation gets a call_endpoint pointing to its actual path.
        """
        tools = []
        paths = spec.get("paths", {})
        for path, methods in paths.items():
            for method, operation in methods.items():
                if method.lower() not in ("get", "post", "put", "patch", "delete"):
                    continue
                op_id = operation.get("operationId", f"{method}_{path}".replace("/", "_"))
                tools.append(
                    MCPToolDefinition(
                        name=op_id,
                        description=operation.get(
                            "summary", operation.get("description", "")
                        )[:500],
                        parameters=_extract_params_schema(operation),
                        server_name=server_name,
                        # For regular API ops, the call endpoint IS the path
                        call_endpoint=path,
                        mcp_function_name="",
                    )
                )
        return tools

    async def _discover_stdio(
        self, name: str, config: MCPServerConfig
    ) -> list[MCPToolDefinition]:
        """Discover tools from a stdio MCP server."""
        if not config.command:
            return []

        try:
            import json as json_mod
            env = {**os.environ, **config.env}
            proc = await asyncio.create_subprocess_exec(
                config.command,
                *config.args,
                stdin=asyncio.subprocess.PIPE,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
                env=env,
            )

            init_msg = (
                '{"jsonrpc":"2.0","id":1,"method":"initialize",'
                '"params":{"protocolVersion":"2024-11-05",'
                '"capabilities":{},"clientInfo":{"name":"coder","version":"1.0"}}}\n'
            )
            proc.stdin.write(init_msg.encode())
            await proc.stdin.drain()
            await asyncio.wait_for(proc.stdout.readline(), timeout=10)

            proc.stdin.write(
                b'{"jsonrpc":"2.0","method":"notifications/initialized"}\n'
            )
            await proc.stdin.drain()

            list_msg = '{"jsonrpc":"2.0","id":2,"method":"tools/list","params":{}}\n'
            proc.stdin.write(list_msg.encode())
            await proc.stdin.drain()

            tools_resp = await asyncio.wait_for(proc.stdout.readline(), timeout=10)
            proc.terminate()

            data = json_mod.loads(tools_resp)
            tools_list = data.get("result", {}).get("tools", [])
            return [
                MCPToolDefinition(
                    name=t["name"],
                    description=t.get("description", ""),
                    parameters=t.get("inputSchema", {}),
                    server_name=name,
                    # stdio tools use JSON-RPC, not HTTP paths
                    call_endpoint="stdio",
                    mcp_function_name="",
                )
                for t in tools_list
            ]
        except Exception as e:
            log.warning(f"stdio_discovery_failed: {name}: {e}")
            return []

    def _parse_tools_response(
        self, data: Any, server_name: str
    ) -> list[MCPToolDefinition]:
        """Parse a tools list response into tool definitions."""
        tools = []
        tool_list = []
        if isinstance(data, list):
            tool_list = data
        elif isinstance(data, dict):
            tool_list = data.get("tools", data.get("data", data.get("result", [])))
            if isinstance(tool_list, dict):
                tool_list = tool_list.get("tools", [])

        for item in tool_list:
            if isinstance(item, dict):
                tools.append(
                    MCPToolDefinition(
                        name=item.get("name", item.get("function", {}).get("name", "")),
                        description=item.get(
                            "description",
                            item.get("function", {}).get("description", ""),
                        ),
                        parameters=item.get(
                            "inputSchema",
                            item.get("parameters", item.get("function", {}).get("parameters", {})),
                        ),
                        server_name=server_name,
                        tags=item.get("tags", []),
                    )
                )
        return tools

    # --- Query methods ---

    def get_tool(self, name: str) -> MCPToolDefinition | None:
        """Look up a tool by its qualified name."""
        return self._tools.get(name)

    def get_route(self, tool_name: str) -> dict[str, str] | None:
        """Get the routing info for a tool (call_endpoint, mcp_function_name)."""
        return self._route_table.get(tool_name)

    def list_tools(self, server_name: str | None = None) -> list[MCPToolDefinition]:
        """List all tools, optionally filtered by server name."""
        if server_name:
            names = self._server_tools.get(server_name, [])
            return [self._tools[n] for n in names if n in self._tools]
        return list(self._tools.values())

    def list_servers(self) -> dict[str, MCPServerConfig]:
        """Return a copy of all registered server configs."""
        return dict(self._servers)

    def search_tools(self, query: str) -> list[MCPToolDefinition]:
        """Search tools by keyword match against name, description, tags, and function name."""
        query_lower = query.lower()
        results = []
        for tool in self._tools.values():
            text = f"{tool.name} {tool.description} {' '.join(tool.tags)} {tool.mcp_function_name}".lower()
            if query_lower in text or any(w in text for w in query_lower.split()):
                results.append(tool)
        return results

    def get_server_health(self) -> dict[str, bool]:
        """Return a copy of the current server health status map."""
        return dict(self._server_health)

    async def health_check(self, server_name: str) -> bool:
        """Probe a server's health endpoint and update its health status."""
        config = self._servers.get(server_name)
        if not config or not config.url:
            return False
        try:
            async with httpx.AsyncClient(timeout=10) as client:
                for path in ["/health", "/"]:
                    try:
                        resp = await client.get(
                            f"{config.url.rstrip('/')}{path}",
                            headers=config.headers,
                        )
                        if resp.status_code < 500:
                            self._server_health[server_name] = True
                            return True
                    except Exception:
                        continue
        except Exception:
            pass
        self._server_health[server_name] = False
        return False

    def get_tools_for_litellm(
        self, server_name: str | None = None, max_tools: int = 50
    ) -> list[dict[str, Any]]:
        """Return tools in LiteLLM/OpenAI function-calling format."""
        tools = self.list_tools(server_name)[:max_tools]
        return [t.to_litellm_format() for t in tools]

    @property
    def needs_rediscovery(self) -> bool:
        """Check if the tool catalog is stale and needs re-discovery."""
        return (time.time() - self._last_discovery) > self._discovery_ttl


def _extract_params_schema(operation: dict[str, Any]) -> dict[str, Any]:
    """Extract parameters schema from an OpenAPI operation."""
    props = {}
    required = []
    for param in operation.get("parameters", []):
        name = param.get("name", "")
        if name:
            props[name] = {
                "type": param.get("schema", {}).get("type", "string"),
                "description": param.get("description", ""),
            }
            if param.get("required"):
                required.append(name)
    return {"type": "object", "properties": props, "required": required}


# ---------------------------------------------------------------------------
# Global registry singleton
# ---------------------------------------------------------------------------

_mcp_registry: MCPServerRegistry | None = None


def get_mcp_registry(project_dir: Path | None = None) -> MCPServerRegistry:
    """Return the process-wide MCP server registry, creating it on first use."""
    global _mcp_registry
    if _mcp_registry is None:
        _mcp_registry = MCPServerRegistry(project_dir)
    return _mcp_registry


async def init_mcp_registry(project_dir: Path | None = None) -> MCPServerRegistry:
    """Get the global registry and initialize it (discover all tools)."""
    registry = get_mcp_registry(project_dir)
    await registry.initialize()
    return registry
