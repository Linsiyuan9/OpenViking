#!/usr/bin/env python3
"""
MCP Server that exposes OpenViking file tools (list, search, grep, glob, read, add_resource, memory_commit).

Usage:
  # HTTP mode (default, port 2033)
  python -m vikingbot.mcp_server

  # Custom port
  python -m vikingbot.mcp_server --port 9000

  # stdio mode (for Claude Desktop / Claude Code)
  python -m vikingbot.mcp_server --transport stdio

Connect from Claude Code:
  claude mcp add --transport http openviking http://127.0.0.1:2033/mcp
"""

import argparse
import asyncio
import os
from typing import Optional

from mcp.server.fastmcp import FastMCP

from vikingbot.openviking_mount.ov_server import VikingClient

# ---------------------------------------------------------------------------
# Shared state
# ---------------------------------------------------------------------------
_client: Optional[VikingClient] = None
_agent_id: str = "mcp-server"


async def _get_client() -> VikingClient:
    global _client
    if _client is None:
        _client = await VikingClient.create(agent_id=_agent_id)
    return _client


# ---------------------------------------------------------------------------
# MCP server factory
# ---------------------------------------------------------------------------

def create_server(host: str = "0.0.0.0", port: int = 2033) -> FastMCP:
    mcp = FastMCP(
        name="viki-tools",
        instructions=(
            "Code repository retrieval toolkit. "
            "Use 'openviking_search' for semantic code search — find code by intent or description, not exact text. "
            "Use 'openviking_grep' for exact pattern matching with regex, like grep/rg. "
            "Use 'openviking_glob' to find files by name pattern (e.g. **/*.py, src/**/*.ts). "
            "Use 'openviking_list' to browse the repository directory tree. "
            "Use 'openviking_multi_read' to fetch full file contents by URI. "
            "Typical workflow: search/grep/glob to locate relevant files → multi_read to get their contents."
        ),
        host=host,
        port=port,
        stateless_http=True,
        json_response=True,
    )

    # ---- openviking_list ----
    @mcp.tool()
    async def openviking_list(uri: str, recursive: bool = False) -> str:
        """List resources in an OpenViking folder path.

        Args:
            uri: The parent Viking URI to list (e.g. viking://resources/).
            recursive: Whether to list recursively.
        """
        client = await _get_client()
        entries = await client.list_resources(path=uri, recursive=recursive)
        if not entries:
            return f"No resources found at {uri}"
        lines = []
        for entry in entries:
            lines.append(str({
                "name": entry["name"],
                "size": entry["size"],
                "uri": entry["uri"],
                "isDir": entry["isDir"],
            }))
        return "\n".join(lines)

    # ---- openviking_search ----
    @mcp.tool()
    async def openviking_search(query: str, target_uri: str = "") -> str:
        """Semantic search for resources in OpenViking.

        Args:
            query: The search query.
            target_uri: Optional URI to limit search scope (e.g. viking://resources/).
        """
        client = await _get_client()
        search_client = getattr(client, "admin_user_client", client)
        results = await search_client.search(query, target_uri=target_uri)
        if not results:
            return f"No results found for query: {query}"
        if isinstance(results, list):
            return "\n".join(f"{i}. {r}" for i, r in enumerate(results, 1))
        return str(results)

    # ---- openviking_add_resource ----
    # @mcp.tool()
    # async def openviking_add_resource(path: str, description: str) -> str:
    #     """Add a resource (URL, git repo, or local file) to OpenViking. Async operation.
    #
    #     Args:
    #         path: URL or local file path.
    #         description: Description of the resource.
    #     """
    #     from pathlib import Path as P
    #     if path and not path.startswith("http"):
    #         local = P(path).expanduser().resolve()
    #         if not local.exists():
    #             return f"Error: File not found: {path}"
    #         if not local.is_file():
    #             return f"Error: Not a file: {path}"
    #     client = await VikingClient.create(agent_id=_agent_id)
    #     try:
    #         result = await client.add_resource(path, description)
    #         if result:
    #             return f"Successfully added resource: {result.get('root_uri', '')}"
    #         return "Failed to add resource"
    #     finally:
    #         await client.close()

    # ---- openviking_grep ----
    @mcp.tool()
    async def openviking_grep(
        uri: str, pattern: list[str], case_insensitive: bool = False
    ) -> str:
        """Search Viking resources using regex patterns (like grep). Supports multiple patterns.

        Args:
            uri: Viking URI to search within (e.g. viking://resources/).
            pattern: Regex pattern(s) to search for.
            case_insensitive: Case-insensitive search.
        """
        client = await _get_client()
        patterns = pattern if isinstance(pattern, list) else [pattern]
        semaphore = asyncio.Semaphore(10)

        async def run_grep(p: str):
            async with semaphore:
                try:
                    result = await client.grep(uri, p, case_insensitive=case_insensitive)
                    matches = result.get("matches", []) if isinstance(result, dict) else getattr(result, "matches", [])
                    return (p, matches)
                except Exception:
                    return (p, [])

        results = await asyncio.gather(*(run_grep(p) for p in patterns))

        merged: dict[str, list] = {}
        total = 0
        for p, matches in results:
            total += len(matches)
            for m in matches:
                m_uri = m.get("uri", "unknown") if isinstance(m, dict) else getattr(m, "uri", "unknown")
                line = m.get("line", "?") if isinstance(m, dict) else getattr(m, "line", "?")
                content = m.get("content", "") if isinstance(m, dict) else getattr(m, "content", "")
                merged.setdefault(m_uri, []).append((line, content, p))

        if not merged:
            return f"No matches found for patterns: {', '.join(patterns)}"

        lines = [f"Found {total} matches across {len(patterns)} patterns:"]
        for m_uri, hits in merged.items():
            hits.sort(key=lambda x: int(x[0]) if str(x[0]).isdigit() else 0)
            lines.append(f"\n{m_uri}")
            for line, content, pname in hits:
                lines.append(f"   Line {line} (pattern: '{pname}'):")
                lines.append(f"   {content}")
        return "\n".join(lines)

    # ---- openviking_glob ----
    @mcp.tool()
    async def openviking_glob(pattern: str, uri: str = "") -> str:
        """Find Viking resources using glob patterns (e.g. **/*.md, *.py).

        Args:
            pattern: Glob pattern to match.
            uri: Viking URI to search within (e.g. viking://resources/).
        """
        client = await _get_client()
        result = await client.glob(pattern, uri=uri or None)
        matches = result.get("matches", []) if isinstance(result, dict) else getattr(result, "matches", [])
        count = result.get("count", 0) if isinstance(result, dict) else getattr(result, "count", 0)
        if not matches:
            return f"No files found for pattern: {pattern}"
        lines = [f"Found {count} files:"]
        for m in matches:
            m_uri = m.get("uri", str(m)) if isinstance(m, dict) else str(m)
            lines.append(f"  {m_uri}")
        return "\n".join(lines)

    # ---- openviking_multi_read ----
    @mcp.tool()
    async def openviking_multi_read(uris: list[str]) -> str:
        """Read full content from multiple OpenViking resources concurrently.

        Args:
            uris: List of Viking file URIs to read.
        """
        if not uris:
            return "Error: No URIs provided."
        client = await _get_client()
        semaphore = asyncio.Semaphore(10)

        async def read_one(u: str):
            async with semaphore:
                try:
                    content = await client.read_content(u, level="read")
                    return (u, content, True)
                except Exception as e:
                    return (u, str(e), False)

        results = await asyncio.gather(*(read_one(u) for u in uris))
        lines = [f"Multi-read results for {len(uris)} resources:"]
        for u, content, ok in results:
            lines.append(f"\n--- START OF {u} ---")
            lines.append(content if ok else f"ERROR: {content}")
            lines.append(f"--- END OF {u} ---")
        return "\n".join(lines)

    # # ---- openviking_memory_commit ----
    # @mcp.tool()
    # async def openviking_memory_commit(
    #     messages: list[dict], session_id: str = "mcp-session", sender_id: str = "mcp-user"
    # ) -> str:
    #     """Commit messages to OpenViking for memory storage.
    #
    #     Args:
    #         messages: List of messages, each with 'role' (user/assistant) and 'content'.
    #         session_id: Session identifier.
    #         sender_id: Sender identifier.
    #     """
    #     client = await _get_client()
    #     await client.commit(session_id, messages, sender_id)
    #     return f"Successfully committed to session {session_id}"

    return mcp


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def main():
    parser = argparse.ArgumentParser(description="OpenViking Tools MCP Server")
    parser.add_argument("--host", default="0.0.0.0")
    parser.add_argument("--port", type=int, default=int(os.getenv("OV_MCP_PORT", "2033")))
    parser.add_argument("--transport", choices=["streamable-http", "stdio"], default="streamable-http")
    parser.add_argument("--agent-id", default=os.getenv("OV_AGENT_ID", "mcp-server"))
    args = parser.parse_args()

    global _agent_id
    _agent_id = args.agent_id

    mcp = create_server(host=args.host, port=args.port)

    if args.transport == "streamable-http":
        print(f"OpenViking MCP Server: http://{args.host}:{args.port}/mcp")
        mcp.run(transport="streamable-http")
    else:
        mcp.run(transport="stdio")


if __name__ == "__main__":
    main()
