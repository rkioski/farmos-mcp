import json
from datetime import datetime, timezone
from typing import Optional

from farmos_client import get_client

# All standard log bundle types in farmOS 2.x
LOG_TYPES = [
    "activity",
    "harvest",
    "input",
    "observation",
    "purchase",
    "sale",
    "seeding",
    "transplanting",
]


# ---------------------------------------------------------------------------
# Normalisation helpers
# ---------------------------------------------------------------------------

def _ts_to_iso(ts) -> Optional[str]:
    if ts is None:
        return None
    try:
        return datetime.fromtimestamp(int(ts), tz=timezone.utc).isoformat()
    except (ValueError, TypeError):
        return str(ts)


def _notes_text(field) -> Optional[str]:
    if field is None:
        return None
    if isinstance(field, dict):
        return field.get("value")
    return str(field)


def _refs(rel_data) -> list[dict]:
    """Extract id+type pairs from a JSON:API relationship data array."""
    items = rel_data if isinstance(rel_data, list) else ([rel_data] if rel_data else [])
    return [
        {"id": r["id"], "type": r["type"].split("--", 1)[-1]}
        for r in items
        if isinstance(r, dict) and r.get("id")
    ]


def _resolve_names(refs: list[dict], included: dict) -> list[dict]:
    """Add name to refs if the resource was included in the response."""
    for ref in refs:
        inc = included.get(ref["id"])
        if inc:
            ref["name"] = inc.get("attributes", {}).get("name")
    return refs


def _normalize_log(resource: dict, included: dict | None = None) -> dict:
    attrs = resource.get("attributes", {})
    rels = resource.get("relationships", {})

    assets = _refs(rels.get("asset", {}).get("data"))
    locations = _refs(rels.get("location", {}).get("data"))

    if included:
        _resolve_names(assets, included)
        _resolve_names(locations, included)

    return {
        "id": resource.get("id"),
        "type": resource.get("type", "").split("--", 1)[-1],
        "name": attrs.get("name"),
        "status": attrs.get("status"),
        "timestamp": _ts_to_iso(attrs.get("timestamp")),
        "notes": _notes_text(attrs.get("notes")),
        "assets": assets,
        "locations": locations,
        "is_movement": attrs.get("is_movement", False),
    }


def _build_date_params(params: dict, date_from: Optional[str], date_to: Optional[str]) -> None:
    if date_from:
        dt = date_from if "T" in date_from else f"{date_from}T00:00:00Z"
        params["filter[date_from][condition][path]"] = "timestamp"
        params["filter[date_from][condition][value]"] = dt
        params["filter[date_from][condition][operator]"] = ">="
    if date_to:
        dt = date_to if "T" in date_to else f"{date_to}T23:59:59Z"
        params["filter[date_to][condition][path]"] = "timestamp"
        params["filter[date_to][condition][value]"] = dt
        params["filter[date_to][condition][operator]"] = "<="


# ---------------------------------------------------------------------------
# Read tools
# ---------------------------------------------------------------------------

def get_logs(
    log_type: Optional[str] = None,
    status: Optional[str] = None,
    date_from: Optional[str] = None,
    date_to: Optional[str] = None,
    asset_id: Optional[str] = None,
    limit: int = 20,
    offset: int = 0,
) -> str:
    """List logs from farmOS, newest first. Filter by type, status, date range, or asset.

    Args:
        log_type: Log bundle without prefix: 'activity', 'observation', 'harvest',
                  'input', 'seeding', 'transplanting', 'purchase', 'sale'.
                  Omit to query all types (multiple requests, no pagination offset).
        status: 'pending' or 'done'. Omit for both.
        date_from: ISO 8601 date, e.g. '2024-06-01'. Returns logs on or after this date.
        date_to: ISO 8601 date, e.g. '2024-06-30'. Returns logs on or before this date.
        asset_id: UUID of an asset. Returns only logs referencing it.
        limit: Max logs to return (default 20, max 100).
        offset: Pagination offset — only applies when log_type is specified.

    Returns:
        JSON with 'logs' list and 'returned' count.
    """
    try:
        client = get_client()
        params: dict = {"sort": "-timestamp"}

        if status:
            params["filter[status]"] = status
        if asset_id:
            params["filter[asset.id]"] = asset_id
        _build_date_params(params, date_from, date_to)

        if log_type:
            params["page[limit]"] = min(limit, 100)
            params["page[offset]"] = offset
            result = client.get(f"log/{log_type}", params=params)
            logs = [_normalize_log(r) for r in result.get("data", [])]
            total = result.get("meta", {}).get("count", len(logs))
            return json.dumps({"total": total, "returned": len(logs), "logs": logs}, indent=2)

        # No type specified — query all known types, merge, trim to limit
        params["page[limit]"] = min(limit, 100)
        all_logs: list[dict] = []
        for t in LOG_TYPES:
            try:
                result = client.get(f"log/{t}", params=params)
                all_logs.extend(_normalize_log(r) for r in result.get("data", []))
            except Exception:
                pass  # type may not be enabled on this instance

        all_logs.sort(key=lambda x: x.get("timestamp") or "", reverse=True)
        all_logs = all_logs[:limit]
        return json.dumps({"returned": len(all_logs), "logs": all_logs}, indent=2)

    except Exception as e:
        return json.dumps({"error": str(e)})


def get_log(id: str, log_type: Optional[str] = None) -> str:
    """Get a single farmOS log by UUID, including full details and related asset names.

    Args:
        id: UUID of the log.
        log_type: Bundle name if known (e.g. 'observation'). Speeds up the lookup —
                  without it all types are tried.

    Returns:
        JSON with full log details.
    """
    try:
        client = get_client()
        # Include related asset and location data in a single request
        params = {"include": "asset,location"}
        types_to_try = [log_type] if log_type else LOG_TYPES

        for t in types_to_try:
            try:
                result = client.get(f"log/{t}/{id}", params=params)
                data = result.get("data")
                if not data:
                    continue
                included = {r["id"]: r for r in result.get("included", [])}
                return json.dumps(_normalize_log(data, included), indent=2)
            except Exception:
                continue

        return json.dumps({"error": f"Log {id} not found"})

    except Exception as e:
        return json.dumps({"error": str(e)})


# ---------------------------------------------------------------------------
# Write tools — only registered when FARMOS_READ_ONLY=false
# ---------------------------------------------------------------------------

def _lookup_asset_type(client, asset_id: str) -> str:
    """Resolve an asset UUID to its bundle type (e.g. 'land', 'plant')."""
    from tools.assets import ASSET_TYPES
    for t in ASSET_TYPES:
        try:
            result = client.get(f"asset/{t}/{asset_id}")
            if result.get("data"):
                return t
        except Exception:
            continue
    raise ValueError(f"Asset {asset_id} not found — cannot determine its type")


def create_log(
    log_type: str,
    name: str,
    status: str = "pending",
    notes: Optional[str] = None,
    timestamp: Optional[str] = None,
    asset_ids: Optional[list[str]] = None,
) -> str:
    """Create a new log in farmOS.

    Args:
        log_type: Log bundle, e.g. 'activity', 'observation', 'harvest'.
        name: Name/title of the log.
        status: 'pending' (default) or 'done'.
        notes: Optional plain-text notes.
        timestamp: ISO 8601 datetime. Defaults to now.
        asset_ids: UUIDs of assets to link to this log. Their types are resolved automatically.

    Returns:
        JSON of the created log.
    """
    try:
        client = get_client()

        ts = int(
            datetime.fromisoformat(timestamp.replace("Z", "+00:00")).timestamp()
            if timestamp
            else datetime.now(tz=timezone.utc).timestamp()
        )

        payload: dict = {
            "type": f"log--{log_type}",
            "attributes": {
                "name": name,
                "status": status,
                "timestamp": ts,
            },
        }

        if notes:
            payload["attributes"]["notes"] = {"value": notes, "format": "default"}

        if asset_ids:
            asset_rels = []
            for aid in asset_ids:
                atype = _lookup_asset_type(client, aid)
                asset_rels.append({"type": f"asset--{atype}", "id": aid})
            payload["relationships"] = {"asset": {"data": asset_rels}}

        result = client.post(f"log/{log_type}", payload)
        return json.dumps(_normalize_log(result.get("data", {})), indent=2)

    except Exception as e:
        return json.dumps({"error": str(e)})


def update_log(
    id: str,
    log_type: str,
    name: Optional[str] = None,
    status: Optional[str] = None,
    notes: Optional[str] = None,
) -> str:
    """Update fields on an existing farmOS log.

    Args:
        id: UUID of the log.
        log_type: Bundle of the log (required for PATCH), e.g. 'observation'.
        name: New name (optional).
        status: New status — 'pending' or 'done' (optional).
        notes: New notes text (optional). Replaces existing notes.

    Returns:
        JSON of the updated log.
    """
    try:
        client = get_client()

        payload: dict = {
            "type": f"log--{log_type}",
            "id": id,
            "attributes": {},
        }

        if name is not None:
            payload["attributes"]["name"] = name
        if status is not None:
            payload["attributes"]["status"] = status
        if notes is not None:
            payload["attributes"]["notes"] = {"value": notes, "format": "default"}

        result = client.patch(f"log/{log_type}/{id}", payload)
        return json.dumps(_normalize_log(result.get("data", {})), indent=2)

    except Exception as e:
        return json.dumps({"error": str(e)})
