import json
from typing import Optional

from farmos_client import get_client

# Known plan bundle types — farmOS core has no built-in plan types;
# modules provide them. The most common is 'rotational_grazing' from
# the farm_rotational module. List additional module-provided types here.
PLAN_TYPES: list[str] = []


def _normalize_plan(resource: dict) -> dict:
    attrs = resource.get("attributes", {})
    rels = resource.get("relationships", {})

    owners = [
        {"id": r["id"], "type": r["type"].split("--", 1)[-1]}
        for r in (rels.get("owner", {}).get("data") or [])
        if isinstance(r, dict)
    ]

    return {
        "id": resource.get("id"),
        "type": resource.get("type", "").split("--", 1)[-1],
        "name": attrs.get("name"),
        "status": attrs.get("status"),
        "notes": (attrs.get("notes") or {}).get("value") if isinstance(attrs.get("notes"), dict) else attrs.get("notes"),
        "flags": attrs.get("flags", []),
        "owners": owners,
    }


def get_plans(
    plan_type: Optional[str] = None,
    status: Optional[str] = None,
    limit: int = 20,
    offset: int = 0,
) -> str:
    """List plans from farmOS.

    Plans organise assets and logs around a goal (e.g. a crop rotation or grazing plan).
    Available plan types depend on which farmOS modules are installed.

    Args:
        plan_type: Bundle without prefix (e.g. 'rotational_grazing').
                   Omit to query all known types.
        status: Filter by status, e.g. 'planning', 'active', 'done', 'abandoned'.
        limit: Max plans to return (default 20, max 100).
        offset: Pagination offset — only applies when plan_type is specified.

    Returns:
        JSON with 'plans' list and 'returned' count.
    """
    try:
        client = get_client()
        params: dict = {"sort": "name"}

        if status:
            params["filter[status]"] = status

        if plan_type:
            params["page[limit]"] = min(limit, 100)
            params["page[offset]"] = offset
            result = client.get(f"plan/{plan_type}", params=params)
            plans = [_normalize_plan(r) for r in result.get("data", [])]
            total = result.get("meta", {}).get("count", len(plans))
            return json.dumps({"total": total, "returned": len(plans), "plans": plans}, indent=2)

        if not PLAN_TYPES:
            return json.dumps({
                "returned": 0,
                "plans": [],
                "note": "No plan types configured. Specify plan_type explicitly if you know the bundle name.",
            }, indent=2)

        params["page[limit]"] = min(limit, 100)
        all_plans: list[dict] = []
        for t in PLAN_TYPES:
            try:
                result = client.get(f"plan/{t}", params=params)
                all_plans.extend(_normalize_plan(r) for r in result.get("data", []))
            except Exception:
                pass

        all_plans.sort(key=lambda x: (x.get("name") or "").lower())
        all_plans = all_plans[:limit]
        return json.dumps({"returned": len(all_plans), "plans": all_plans}, indent=2)

    except Exception as e:
        return json.dumps({"error": str(e)})


def get_plan(id: str, plan_type: Optional[str] = None) -> str:
    """Get a single farmOS plan by UUID.

    Args:
        id: UUID of the plan.
        plan_type: Bundle name if known. Required if PLAN_TYPES list is empty.

    Returns:
        JSON with plan details.
    """
    try:
        client = get_client()
        types_to_try = [plan_type] if plan_type else PLAN_TYPES

        if not types_to_try:
            return json.dumps({"error": "plan_type is required when no plan types are configured"})

        for t in types_to_try:
            try:
                result = client.get(f"plan/{t}/{id}")
                data = result.get("data")
                if data:
                    return json.dumps(_normalize_plan(data), indent=2)
            except Exception:
                continue

        return json.dumps({"error": f"Plan {id} not found"})

    except Exception as e:
        return json.dumps({"error": str(e)})


# ---------------------------------------------------------------------------
# Write tools — only registered when FARMOS_READ_ONLY=false
# ---------------------------------------------------------------------------

def create_plan(
    plan_type: str,
    name: str,
    status: str = "planning",
    notes: Optional[str] = None,
    owner_ids: Optional[list[str]] = None,
    flags: Optional[list[str]] = None,
) -> str:
    """Create a new plan in farmOS.

    Plans organise assets and logs around a goal (e.g. a crop rotation or grazing schedule).
    Available plan types depend on which farmOS modules are installed.

    Args:
        plan_type: Bundle name, e.g. 'rotational_grazing'. Must match an installed module's plan type.
        name: Name of the plan.
        status: 'planning' (default), 'active', 'done', or 'abandoned'.
        notes: Optional plain-text notes.
        owner_ids: UUIDs of users assigned as owners of this plan.
        flags: Flag strings — 'priority', 'needs_review', 'monitor'.

    Returns:
        JSON of the created plan including its UUID.
    """
    try:
        client = get_client()
        payload: dict = {
            "type": f"plan--{plan_type}",
            "attributes": {
                "name": name,
                "status": status,
            },
        }
        if notes is not None:
            payload["attributes"]["notes"] = {"value": notes, "format": "default"}
        if flags is not None:
            payload["attributes"]["flags"] = flags

        if owner_ids:
            payload["relationships"] = {
                "owner": {"data": [{"type": "user--user", "id": uid} for uid in owner_ids]}
            }

        result = client.post(f"plan/{plan_type}", payload)
        return json.dumps(_normalize_plan(result.get("data", {})), indent=2)

    except Exception as e:
        return json.dumps({"error": str(e)})


def update_plan(
    id: str,
    plan_type: str,
    name: Optional[str] = None,
    status: Optional[str] = None,
    notes: Optional[str] = None,
    owner_ids: Optional[list[str]] = None,
    flags: Optional[list[str]] = None,
) -> str:
    """Update an existing farmOS plan.

    Args:
        id: UUID of the plan.
        plan_type: Bundle of the plan (required for PATCH), e.g. 'rotational_grazing'.
        name: New name (optional).
        status: New status — 'planning', 'active', 'done', or 'abandoned' (optional).
        notes: New notes text (optional). Replaces existing notes.
        owner_ids: Replace assigned owners. Pass [] to clear all.
        flags: Replace flags list. Pass [] to clear all.

    Returns:
        JSON of the updated plan.
    """
    try:
        client = get_client()
        payload: dict = {
            "type": f"plan--{plan_type}",
            "id": id,
            "attributes": {},
        }
        if name is not None:
            payload["attributes"]["name"] = name
        if status is not None:
            payload["attributes"]["status"] = status
        if notes is not None:
            payload["attributes"]["notes"] = {"value": notes, "format": "default"}
        if flags is not None:
            payload["attributes"]["flags"] = flags

        if owner_ids is not None:
            payload["relationships"] = {
                "owner": {"data": [{"type": "user--user", "id": uid} for uid in owner_ids]}
            }

        result = client.patch(f"plan/{plan_type}/{id}", payload)
        return json.dumps(_normalize_plan(result.get("data", {})), indent=2)

    except Exception as e:
        return json.dumps({"error": str(e)})
