# farmOS MCP Server

An [MCP](https://modelcontextprotocol.io) server that runs on your local computer and connects [Claude Desktop](https://claude.ai/download) to your [farmOS](https://farmos.org) instance over the network. Your farmOS can be hosted anywhere — this server runs on the same machine as Claude Desktop and talks to it via its API. Chat with Claude about your farm using live data. Tested with farmOS 3.x.

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

On your **local machine** (where Claude Desktop is installed):
- Python 3.10+ — download from [python.org](https://www.python.org/downloads/) if not already installed

On your **farmOS server**:
- A running farmOS 3.x instance
- An OAuth2 client configured in farmOS

## farmOS OAuth2 client setup

1. In your farmOS instance go to **Admin → Config → Simple OAuth → Clients**
2. Add a new client
3. Choose **Confidential** (client credentials flow) or **Public** (password grant is fine for personal use)
4. Note the **Client ID** and **Client Secret**

## Installation

Run the following on your **local machine** in a terminal:

```bash
git clone https://github.com/rkioski/farmos-mcp
cd farmos-mcp
pip install -e .
```

Or with [uv](https://docs.astral.sh/uv/):

```bash
git clone https://github.com/rkioski/farmos-mcp
cd farmos-mcp
uv pip install -e .
```

## Configuration

Copy `.env.example` to `.env`:

- **macOS/Linux:** `cp .env.example .env`
- **Windows:** `copy .env.example .env`

Then open `.env` in a text editor and fill in your values.

### Password grant (recommended for personal use)

```env
FARMOS_URL=https://myfarm.example.com
FARMOS_CLIENT_ID=farm
FARMOS_CLIENT_SECRET=          # leave empty for Public clients
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
      "command": "python3",
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

Replace `/absolute/path/to/farmos-mcp/server.py` with the actual path to where you cloned the repository. On Windows use `python` instead of `python3`.

> **Tip:** If you use a `.env` file, you can omit the `env` block from the Claude config — the server loads `.env` automatically on startup.

If you installed with `uv`, replace `"command": "python3"` with `"command": "uv"` and `"args": ["run", "--project", "/absolute/path/to/farmos-mcp", "farmos-mcp"]`.

**After saving the config, restart Claude Desktop.**

## Enabling write mode

Set `FARMOS_READ_ONLY=false` in your `.env` file or in the `env` block of your Claude Desktop config to enable `create_log` and `update_log`. Use with care — Claude will be able to write to your farmOS.

## AI agent instructions

Claude's ability to query your farmOS data depends on how it interprets your requests. The default behavior (e.g. filtering logs by `asset_id`) may miss related logs that appear as locations rather than assets, or logs linked to multiple fields at once.

You can improve results significantly by giving Claude a custom instruction file. Create or have the ai agent generate a markdown file describing your farm's structure and preferred query patterns — such as which log types exist on your instance, your field names and UUIDs, and instructions to fetch all log types and filter manually rather than relying on API-level filters. 

Add the file to Claude Desktop via **Settings → Profile → Custom instructions** or by referencing it in a Project.

## Example prompts

- *"What did I do on the farm last week?"*
- *"Show me all pending observations for the south field"*
- *"List my active plant assets"*
- *"Did I apply any inputs to bed 3 this season?"*
- *"Create an observation log: saw aphids on tomatoes in the greenhouse"* *(write mode)*
