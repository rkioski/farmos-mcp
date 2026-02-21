import json
from typing import Optional

from farmos_client import get_client


def _normalize_user(resource: dict) -> dict:
    attrs = resource.get("attributes", {})
    return {
        "id": resource.get("id"),
        "name": attrs.get("name") or attrs.get("display_name"),
        "roles": attrs.get("roles", []),
    }


def get_users(
    name: Optional[str] = None,
    limit: int = 50,
    offset: int = 0,
) -> str:
    """List farmOS user accounts.

    Use this to look up user UUIDs when setting owner_ids on logs.

    Args:
        name: Filter by username (optional).
        limit: Max users to return (default 50, max 100).
        offset: Pagination offset.

    Returns:
        JSON with 'users' list and 'returned' count.
    """
    try:
        client = get_client()
        params: dict = {
            "sort": "name",
            "page[limit]": min(limit, 100),
            "page[offset]": offset,
        }
        if name:
            params["filter[name]"] = name

        result = client.get("user/user", params=params)
        users = [_normalize_user(r) for r in result.get("data", [])]
        total = result.get("meta", {}).get("count", len(users))
        return json.dumps({"total": total, "returned": len(users), "users": users}, indent=2)

    except Exception as e:
        return json.dumps({"error": str(e)})
