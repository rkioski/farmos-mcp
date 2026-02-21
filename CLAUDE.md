# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project Overview

MCP (Model Context Protocol) server that bridges Claude Desktop with a self-hosted farmOS 2.x instance via its JSON:API. Exposes farmOS logs and assets as MCP tools and prompt templates.

## Commands

```bash
# Install dependencies (editable)
pip install -e .
# or
uv pip install -e .

# Run the MCP server
python server.py
# or via entry point
farmos-mcp

# Run with MCP Inspector (for development/debugging)
mcp dev server.py
```

No automated tests or linting are configured.

## Architecture

**Entry point:** `server.py` — initializes FastMCP and conditionally registers tools based on `FARMOS_READ_ONLY` env var. Write tools (`create_log`, `update_log`) are only registered when `FARMOS_READ_ONLY=false`.

**HTTP client:** `farmos_client.py` — singleton `FarmOSClient` wrapping httpx with OAuth2 (password grant or client credentials). Tokens are fetched lazily and refreshed automatically on 401 responses. Access via `get_client()`.

**Tools:** `tools/logs.py` and `tools/assets.py` — each tool function is a plain synchronous function registered via `mcp.add_tool(fn)` in `server.py`. All return JSON strings, not Python objects.

**Data normalization pattern:** Every tool module has `_normalize_*()` helpers that flatten farmOS JSON:API responses (which include `attributes` and `relationships` nesting) into flat dicts. `_refs()` extracts relationship references, and `_resolve_names()` enriches them from the `included` sideload array.

## Configuration

Copy `.env.example` to `.env`. Required variables:

```
FARMOS_URL=https://your-farmos-instance
FARMOS_CLIENT_ID=farm_mcp
FARMOS_CLIENT_SECRET=your_secret

# Password grant (optional, simpler for personal use)
FARMOS_USERNAME=admin
FARMOS_PASSWORD=your_password

# Set to false to enable write tools
FARMOS_READ_ONLY=true
```

For Claude Desktop, add the server under `mcpServers` in `claude_desktop_config.json` using `python /path/to/server.py` or the `farmos-mcp` entry point, and pass env vars there instead of relying on `.env`.

## farmOS API Notes

- farmOS uses JSON:API; all endpoints follow `/api/{entity_type}/{bundle}` (e.g., `/api/log/activity`)
- Filtering uses JSON:API filter syntax passed as query params
- Dates are Unix timestamps in farmOS API responses but ISO 8601 in tool inputs
- Asset types: `animal`, `equipment`, `land`, `material`, `plant`, `sensor`, `structure`, `water`
- Log types: `activity`, `harvest`, `input`, `observation`, `purchase`, `sale`, `seeding`, `transplanting`
