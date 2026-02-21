from mcp.server.fastmcp import FastMCP

from farmos_client import is_read_only
from tools.logs import get_log, get_logs
from tools.assets import get_asset, get_assets

mcp = FastMCP("farmOS")

# --- Read tools (always registered) ---
mcp.add_tool(get_logs)
mcp.add_tool(get_log)
mcp.add_tool(get_assets)
mcp.add_tool(get_asset)

# --- Write tools (only when FARMOS_READ_ONLY=false) ---
if not is_read_only():
    from tools.logs import create_log, update_log
    mcp.add_tool(create_log)
    mcp.add_tool(update_log)


# ---------------------------------------------------------------------------
# Prompt templates
# ---------------------------------------------------------------------------

@mcp.prompt()
def recent_activity() -> str:
    """What has happened on the farm recently?"""
    return (
        "Use get_logs to fetch the 20 most recent logs across all types. "
        "Summarise what has been happening on the farm: group activities by type, "
        "mention which assets were involved, and highlight anything that is still pending."
    )


@mcp.prompt()
def pending_tasks() -> str:
    """What tasks and observations are still pending?"""
    return (
        "Use get_logs with status='pending' to fetch all pending logs. "
        "List them grouped by log type, include the name, date, and any associated assets. "
        "Highlight anything that is overdue (timestamp in the past)."
    )


@mcp.prompt()
def farm_overview() -> str:
    """Give me a full overview of my farm: assets and recent activity."""
    return (
        "First call get_assets to list all active assets grouped by type (land, plants, animals, equipment). "
        "Then call get_logs with limit=10 to get the latest activity. "
        "Present a concise overview: what assets exist, what has been done recently, "
        "and what is still pending."
    )


@mcp.prompt()
def season_log(season: str) -> str:
    """Review everything that happened during a growing season. season format: 'YYYY' or 'YYYY spring/summer/autumn/winter'"""
    return (
        f"I want to review the '{season}' growing season. "
        "Use get_logs to fetch seeding, transplanting, input, harvest, and observation logs. "
        "For seedings and transplantings filter by the relevant date range for this season. "
        "Summarise: what was planted, what inputs were applied, what was harvested, "
        "and any notable observations. Highlight successes and issues."
    )


@mcp.prompt()
def asset_history(asset_name: str) -> str:
    """Get the full log history for a specific asset (field, plant, animal, etc.)"""
    return (
        f"I want to see everything recorded for the asset named '{asset_name}'. "
        "First use get_assets with name='{asset_name}' to find its UUID. "
        "Then use get_logs with that asset_id to fetch all related logs. "
        "Present a chronological history of everything that has happened with this asset."
    )


def main():
    mcp.run()


if __name__ == "__main__":
    main()
