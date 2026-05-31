"""MCP server exposing the user's iMessage history as structured tools.

Layered on top of the `imsg` package:
  imsg.{db, queries, contacts}  ──► imsg_mcp.store_cache (TTL snapshot + ContactBook)
                                    imsg_mcp.{embeddings, index, indexer}
                                    imsg_mcp.tools  (pure functions)
                                    imsg_mcp.server (FastMCP @mcp.tool decorators)

Run with:
    fastmcp run imsg_mcp/server.py --transport streamable-http --host 127.0.0.1 --port 5000
"""
