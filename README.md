# farmOS MCP Server

An [MCP](https://modelcontextprotocol.io) server that connects [Claude Desktop](https://claude.ai/download) to your self-hosted [farmOS](https://farmos.org) installation. Chat with Claude about your farm using live data.

## Tools

| Tool | Description |
|---|---|
| `get_logs` | List and filter logs by type, status, date range, or asset |
| `get_log` | Fetch a single log by UUID |
| `get_assets` | List and filter assets by type, status, or name |
| `get_asset` | Fetch a single asset by UUID |
| `create_log` | *(write mode only)* Create a new log |
| `update_log` | *(write mode only)* Update name, status, or notes on a log |

## Prerequisites

- Python 3.10+
- A running farmOS 2.x instance
- An OAuth2 client configured in farmOS

## farmOS OAuth2 client setup

1. In your farmOS instance go to **Admin → Config → Simple OAuth → Clients**
2. Add a new client
3. Choose **Confidential** (client credentials flow) or **Public** (password grant is fine for personal use)
4. Note the **Client ID** and **Client Secret**

## Installation

```bash
git clone https://github.com/rkioski/farmos-mcp
cd farmos-mcp
pip install -e .
```

Or with [uv](https://docs.astral.sh/uv/):

```bash
uv pip install -e .
```

## Configuration

Copy `.env.example` to `.env` and fill in your values:

```bash
cp .env.example .env
```

### Password grant (recommended for personal use)

```env
FARMOS_URL=https://myfarm.example.com
FARMOS_CLIENT_ID=farm
FARMOS_CLIENT_SECRET=
FARMOS_USERNAME=admin
FARMOS_PASSWORD=yourpassword
FARMOS_READ_ONLY=true
```

### Client credentials flow

Leave `FARMOS_USERNAME` and `FARMOS_PASSWORD` unset (or empty). The client must have the `farm_manager` or `farm_worker` scope enabled in farmOS.

```env
FARMOS_URL=https://myfarm.example.com
FARMOS_CLIENT_ID=myclient
FARMOS_CLIENT_SECRET=mysecret
FARMOS_READ_ONLY=true
```

## Claude Desktop setup

Edit `~/Library/Application Support/Claude/claude_desktop_config.json` (macOS) or `%APPDATA%\Claude\claude_desktop_config.json` (Windows):

```json
{
  "mcpServers": {
    "farmos": {
      "command": "python",
      "args": ["/absolute/path/to/farmos-mcp/server.py"],
      "env": {
        "FARMOS_URL": "https://myfarm.example.com",
        "FARMOS_CLIENT_ID": "farm",
        "FARMOS_CLIENT_SECRET": "",
        "FARMOS_USERNAME": "admin",
        "FARMOS_PASSWORD": "yourpassword",
        "FARMOS_READ_ONLY": "true"
      }
    }
  }
}
```

> **Tip:** If you use a `.env` file, you can omit the `env` block from the Claude config — the server loads `.env` automatically on startup.

If you installed with `uv`, replace `"command": "python"` with `"command": "uv"` and `"args": ["run", "python", "/path/to/server.py"]`.

## Enabling write mode

Set `FARMOS_READ_ONLY=false` to enable `create_log` and `update_log`. Use with care — Claude will be able to write to your farmOS.

## Example prompts

- *"What did I do on the farm last week?"*
- *"Show me all pending observations for the south field"*
- *"List my active plant assets"*
- *"Did I apply any inputs to bed 3 this season?"*
- *"Create an observation log: saw aphids on tomatoes in the greenhouse"* *(write mode)*
