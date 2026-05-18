"""
MCP Resource Index — built at startup, searched at runtime.

On first boot (or when stale), fetches OpenAPI specs from all configured
MCP servers, extracts every endpoint/tool, and builds a searchable BM25
index. This index is persisted to disk so subsequent startups are instant.

The index supports queries like::

    gg run -m 'search businesswire for investing news'

Which will:

- Classifier detects "search businesswire"
- Reranks MCP tools
- Auto-selects the matching tool and calls it

Or directly search the index::

    gg mcp search "investing"

Architecture
------------

Startup:

1. Load mcp_servers.json
2. For each server: fetch /openapi.json
3. Extract all paths/operations into IndexEntry objects
4. Build BM25 corpus from names, descriptions, and tags
5. Persist index to .coder/mcp_index.json

Runtime:

1. Load index from disk (fast, no network)
2. User prompt into BM25 query into ranked results
3. Top result has call_endpoint and mcp_function_name, ready to call
"""
from __future__ import annotations

import os
import traceback
import json
import math
import time
from pathlib import Path
from typing import Any

import httpx

from oats.log import cl
from oats.mcp.config import load_mcp_config
from oats.mcp.models import MCPServerConfig

log = cl("mcp.index")

INDEX_VERSION = "2"
INDEX_FILENAME = os.getenv('MCP_INDEX_FILE', "mcp_index.json")
INDEX_TTL_SECONDS = 3600  # Re-index after 1 hour


class IndexEntry:
    """A single searchable entry in the MCP index."""

    def __init__(
        self,
        name: str,
        description: str,
        server_name: str,
        mcp_function_name: str,
        call_endpoint: str,
        method: str = "POST",
        tags: list[str] | None = None,
        parameters: dict[str, Any] | None = None,
    ) -> None:
        """Initialize an index entry with the given metadata and build its BM25 corpus."""
        self.name = name
        self.description = description
        self.server_name = server_name
        self.mcp_function_name = mcp_function_name
        self.call_endpoint = call_endpoint
        self.method = method
        self.tags = tags or []
        self.parameters = parameters or {}
        # Searchable text corpus for BM25
        self.corpus = self._build_corpus()

    def _build_corpus(self) -> list[str]:
        """Build tokenized corpus for BM25."""
        text = (
            f"{self.name} {self.description} {self.mcp_function_name} "
            f"{' '.join(self.tags)} {self.server_name}"
        )
        # Simple tokenization: lowercase, split on non-alpha
        import re
        tokens = re.findall(r"[a-z0-9]+", text.lower())
        return tokens

    def to_dict(self) -> dict[str, Any]:
        """Serialize this entry to a plain dict for JSON persistence."""
        return {
            "name": self.name,
            "description": self.description,
            "server_name": self.server_name,
            "mcp_function_name": self.mcp_function_name,
            "call_endpoint": self.call_endpoint,
            "method": self.method,
            "tags": self.tags,
            "parameters": self.parameters,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "IndexEntry":
        """Deserialize an IndexEntry from a plain dict."""
        return cls(
            name=data["name"],
            description=data.get("description", ""),
            server_name=data.get("server_name", ""),
            mcp_function_name=data.get("mcp_function_name", ""),
            call_endpoint=data.get("call_endpoint", ""),
            method=data.get("method", "POST"),
            tags=data.get("tags", []),
            parameters=data.get("parameters", {}),
        )


class MCPIndex:
    """
    Searchable index of all MCP resources across all configured servers.

    Built once at startup, persisted to disk, searched at runtime.
    """

    def __init__(self) -> None:
        """Initialize an empty MCP index with default BM25 parameters."""
        self.entries: list[IndexEntry] = []
        self.built_at: float = 0.0
        self.server_count: int = 0
        # BM25 internals
        self._idf: dict[str, float] = {}
        self._avg_dl: float = 0.0
        self._k1: float = 1.5
        self._b: float = 0.75

    def search(self, query: str, top_k: int = 10) -> list[tuple[float, IndexEntry]]:
        """
        Search the index with BM25 ranking.

        Returns list of (score, entry) tuples sorted by relevance.
        """
        import re
        query_tokens = re.findall(r"[a-z0-9]+", query.lower())
        if not query_tokens or not self.entries:
            return []

        results: list[tuple[float, IndexEntry]] = []

        for entry in self.entries:
            score = self._bm25_score(query_tokens, entry.corpus)
            if score > 0:
                results.append((score, entry))

        results.sort(key=lambda x: x[0], reverse=True)
        return results[:top_k]

    def classify(self, query: str) -> IndexEntry | None:
        """
        Classify a query to the single best matching MCP resource.

        Returns None if no good match found (score too low).
        """
        results = self.search(query, top_k=1)
        if not results:
            return None
        score, entry = results[0]
        # Threshold: require minimum relevance
        if score < 0.1:
            return None
        return entry

    def _bm25_score(self, query_tokens: list[str], doc_tokens: list[str]) -> float:
        """Compute BM25 score for a document against query tokens."""
        dl = len(doc_tokens)
        score = 0.0
        for term in query_tokens:
            tf = doc_tokens.count(term)
            if tf == 0:
                continue
            idf = self._idf.get(term, 0.0)
            numerator = tf * (self._k1 + 1)
            denominator = tf + self._k1 * (1 - self._b + self._b * dl / max(self._avg_dl, 1))
            score += idf * (numerator / max(denominator, 0.001))
        return score

    def _build_bm25(self) -> None:
        """Build BM25 IDF and stats from the current entries."""
        n = len(self.entries)
        if n == 0:
            return

        self._avg_dl = sum(len(e.corpus) for e in self.entries) / n

        # Compute document frequency for each term
        df: dict[str, int] = {}
        for entry in self.entries:
            seen = set()
            for token in entry.corpus:
                if token not in seen:
                    df[token] = df.get(token, 0) + 1
                    seen.add(token)

        # Compute IDF
        self._idf = {}
        for term, freq in df.items():
            self._idf[term] = math.log((n - freq + 0.5) / (freq + 0.5) + 1)

    def to_dict(self) -> dict[str, Any]:
        """Serialize the full index to a plain dict for JSON persistence."""
        return {
            "version": INDEX_VERSION,
            "built_at": self.built_at,
            "server_count": self.server_count,
            "entry_count": len(self.entries),
            "entries": [e.to_dict() for e in self.entries],
        }
    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "MCPIndex":
        """Deserialize an MCPIndex from a plain dict, rebuilding BM25 stats."""
        index = cls()
        index.built_at = data.get("built_at", 0.0)
        index.server_count = data.get("server_count", 0)
        index.entries = [IndexEntry.from_dict(e) for e in data.get("entries", [])]
        index._build_bm25()
        return index

    @property
    def is_stale(self) -> bool:
        """Check if the index has exceeded its TTL and needs rebuilding."""
        return (time.time() - self.built_at) > INDEX_TTL_SECONDS


# ---------------------------------------------------------------------------
# Index building (runs at startup)
# ---------------------------------------------------------------------------

async def build_index(project_dir: Path | None = None) -> MCPIndex:
    """
    Build the MCP index by fetching OpenAPI specs from all configured servers.

    This is the main entry point called at startup.
    """
    config = load_mcp_config(project_dir)
    index = MCPIndex()

    for name, server_config in config.servers.items():
        if not server_config.enabled or not server_config.url:
            continue

        try:
            entries = await _index_server(name, server_config)
            index.entries.extend(entries)
            index.server_count += 1
            log.info(f"indexed: {name} -> {len(entries)} entries")
        except Exception as e:
            log.warning(f"index_failed: {name}: {e}")

    index.built_at = time.time()
    index._build_bm25()

    log.info(
        f"index_built: {len(index.entries)} entries from "
        f"{index.server_count} servers"
    )

    # Persist to disk
    index_path = _index_path(project_dir)
    index_path.parent.mkdir(parents=True, exist_ok=True)
    index_path.write_text(json.dumps(index.to_dict(), indent=2))
    log.info(f"index_saved: {index_path}")

    return index


async def _index_server(
    name: str,
    config: MCPServerConfig,
) -> list[IndexEntry]:
    """Fetch and index a single server's OpenAPI spec."""
    url = config.url.rstrip("/")
    headers = dict(config.headers)
    entries: list[IndexEntry] = []

    async with httpx.AsyncClient(timeout=config.timeout_seconds) as client:
        resp = await client.get(f"{url}/openapi.json", headers=headers)
        if resp.status_code != 200:
            return []

        spec = resp.json()
        paths = spec.get("paths", {})

        for path, methods in paths.items():
            for method, operation in methods.items():
                if method.lower() not in ("get", "post", "put", "patch", "delete"):
                    continue

                op_id = operation.get(
                    "operationId",
                    f"{method}_{path}".replace("/", "_").strip("_"),
                )

                # Detect MCP function patterns
                mcp_fn = ""
                call_ep = path
                if "/tools/call" in path:
                    parts = path.strip("/").split("/")
                    if len(parts) >= 3:
                        mcp_fn = "/".join(parts[:-2])
                        call_ep = path
                elif "/tools/list" in path:
                    # Skip list endpoints — we only index callable ones
                    continue

                # Build tags from path segments
                tags = [
                    seg for seg in path.strip("/").split("/")
                    if seg and not seg.startswith("{") and seg not in ("v1", "tools", "call", "list")
                ]

                entry = IndexEntry(
                    name=op_id,
                    description=operation.get(
                        "summary",
                        operation.get("description", ""),
                    )[:500],
                    server_name=name,
                    mcp_function_name=mcp_fn,
                    call_endpoint=call_ep,
                    method=method.upper(),
                    tags=tags,
                    parameters=_extract_simple_params(operation),
                )
                entries.append(entry)

    return entries


def _extract_simple_params(operation: dict[str, Any]) -> dict[str, Any]:
    """Extract a simplified parameter schema from an OpenAPI operation."""
    props = {}
    for param in operation.get("parameters", []):
        name = param.get("name", "")
        if name:
            props[name] = param.get("schema", {}).get("type", "string")
    return props


# ---------------------------------------------------------------------------
# Index loading (fast path — reads from disk)
# ---------------------------------------------------------------------------

def load_index(project_dir: Path | None = None, verbose: bool = False) -> MCPIndex | None:
    """Load the persisted index from disk. Returns None if not found or stale."""
    path = _index_path(project_dir)
    if not path.exists():
        return None
    if os.path.basename(str(path)) == '.coder':
        return None

    try:
        data = json.loads(path.read_text())
        if data.get("version") != INDEX_VERSION:
            if verbose:
                log.info("index_version_mismatch, will rebuild")
            return None
        index = MCPIndex.from_dict(data)
        if index.is_stale:
            if verbose:
                log.info("index_stale, will rebuild")
            return None
        # log.info(f"index_loaded: {len(index.entries)} entries from {index.server_count} servers")
        return index
    except Exception as e:
        log.warning(f"### Sorrr!! Mcp Load Index Failed\n\n{__file__}\nmcp/index_load_failed:\n```\n{traceback.format_exc()}\n```\npath\n```\n{path}\n```\n")
        return None


async def get_or_build_index(project_dir: Path | None = None) -> MCPIndex:
    """Get the index from disk, or build it if missing/stale."""
    index = load_index(project_dir)
    if index is not None:
        return index
    return await build_index(project_dir)


def _index_path(project_dir: Path | None = None) -> Path:
    """Return the path to the persisted MCP index file."""
    base = project_dir or Path.cwd()
    return base / ".coder" / INDEX_FILENAME
