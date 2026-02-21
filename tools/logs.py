import json
from datetime import datetime, timezone
from typing import Optional

from farmos_client import get_client

# Standard log bundle types in farmOS 3.x
LOG_TYPES = [
    "activity",
    "harvest",
    "input",
    "lab_test",
    "maintenance",
    "medical",
    "observation",
    "purchase",      # Ledger module (optional, may not be installed)
    "sale",          # Ledger module (optional, may not be installed)
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


def _parse_qty_value(value) -> Optional[float]:
    """Parse a farmOS quantity value field — handles both decimal and fraction formats."""
    if not value:
        return None
    if value.get("decimal") is not None:
        try:
            return float(value["decimal"])
        except (ValueError, TypeError):
            pass
    if value.get("numerator") is not None and value.get("denominator"):
        try:
            return int(value["numerator"]) / int(value["denominator"])
        except (ValueError, ZeroDivisionError):
            pass
    return None


def _normalize_quantity(resource: dict, included: dict | None = None) -> dict:
    attrs = resource.get("attributes", {})
    rels = resource.get("relationships", {})
    unit_refs = _refs(rels.get("units", {}).get("data"))
    unit_name = None
    if unit_refs and included:
        inc = included.get(unit_refs[0]["id"])
        if inc:
            unit_name = inc.get("attributes", {}).get("name")
    return {
        "id": resource.get("id"),
        "measure": attrs.get("measure"),
        "value": _parse_qty_value(attrs.get("value")),
        "label": attrs.get("label"),
        "unit": unit_name,
        "inventory_adjustment": attrs.get("inventory_adjustment"),
    }


def _normalize_log(resource: dict, included: dict | None = None) -> dict:
    attrs = resource.get("attributes", {})
    rels = resource.get("relationships", {})
    inc = included or {}

    assets = _refs(rels.get("asset", {}).get("data"))
    locations = _refs(rels.get("location", {}).get("data"))
    equipment = _refs(rels.get("equipment", {}).get("data"))
    owners = _refs(rels.get("owner", {}).get("data"))
    categories = _refs(rels.get("category", {}).get("data"))
    qty_refs = _refs(rels.get("quantity", {}).get("data"))

    if inc:
        _resolve_names(assets, inc)
        _resolve_names(locations, inc)
        _resolve_names(equipment, inc)
        _resolve_names(owners, inc)
        _resolve_names(categories, inc)

    quantities = []
    for qref in qty_refs:
        qinc = inc.get(qref["id"])
        if qinc:
            quantities.append(_normalize_quantity(qinc, inc))
        else:
            quantities.append({"id": qref["id"]})

    result = {
        "id": resource.get("id"),
        "type": resource.get("type", "").split("--", 1)[-1],
        "name": attrs.get("name"),
        "status": attrs.get("status"),
        "timestamp": _ts_to_iso(attrs.get("timestamp")),
        "notes": _notes_text(attrs.get("notes")),
        "flags": attrs.get("flags", []),
        "is_movement": attrs.get("is_movement", False),
        "is_group_assignment": attrs.get("is_group_assignment", False),
        "assets": assets,
        "locations": locations,
        "equipment": equipment,
        "owners": owners,
        "categories": categories,
        "quantities": quantities,
    }

    # Type-specific attributes — only include when present
    for field in ("lot_number", "source", "method"):
        val = attrs.get(field)
        if val is not None:
            result[field] = val

    if attrs.get("purchase_date") is not None:
        result["purchase_date"] = _ts_to_iso(attrs.get("purchase_date"))

    if attrs.get("data") is not None:
        result["data"] = attrs.get("data")

    return result


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
                  'input', 'maintenance', 'seeding', 'transplanting', 'purchase', 'sale'.
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
        types_to_try = [log_type] if log_type else LOG_TYPES
        errors: list[str] = []

        for t in types_to_try:
            # Try progressively simpler includes so as much data as possible is
            # resolved. Surface any include failures in the response so the caller
            # can see what farmOS rejected.
            result = None
            included: dict = {}
            include_used: str | None = None
            include_errors: list[str] = []

            for include_str in (*_LOG_INCLUDE_LEVELS, None):
                try:
                    params = {"include": include_str} if include_str else {}
                    result = client.get(f"log/{t}/{id}", params=params)
                    if include_str:
                        included = {r["id"]: r for r in result.get("included", [])}
                    include_used = include_str
                    break
                except Exception as e:
                    msg = f"{t}(include={include_str!r}): {e}"
                    include_errors.append(msg)
                    errors.append(msg)
                    result = None

            if result is None:
                continue
            data = result.get("data")
            if not data:
                continue

            normalized = _normalize_log(data, included)
            if include_errors:
                normalized["_include_warnings"] = include_errors
                normalized["_include_used"] = include_used
            return json.dumps(normalized, indent=2)

        return json.dumps({"error": f"Log {id} not found", "details": errors})

    except Exception as e:
        return json.dumps({"error": str(e)})


# ---------------------------------------------------------------------------
# Write tools — only registered when FARMOS_READ_ONLY=false
# ---------------------------------------------------------------------------

def _iso_to_ts(date_str: str) -> int:
    """Convert ISO 8601 date or datetime string to Unix timestamp."""
    if "T" not in date_str:
        date_str = f"{date_str}T00:00:00Z"
    return int(datetime.fromisoformat(date_str.replace("Z", "+00:00")).timestamp())


# Progressive include levels. farmOS may reject some relationship names (400/422)
# depending on log type or installed modules, so we narrow the include until one works.
_LOG_INCLUDE_LEVELS = [
    "asset,location,equipment,owner,category,quantity,quantity.units",  # full
    "asset,location,owner,category,quantity,quantity.units",            # no equipment
    "asset,location,owner,category,quantity",                           # no nested quantity.units
    "quantity",                                                         # quantities only
]
# Keep aliases for _fetch_log which still needs them by name
_LOG_INCLUDE = _LOG_INCLUDE_LEVELS[0]            # kept for _fetch_log reference
_LOG_INCLUDE_NO_EQUIPMENT = _LOG_INCLUDE_LEVELS[1]  # kept for _fetch_log reference


def _fetch_log(client, log_type: str, log_id: str) -> str:
    """GET a log with full includes and return normalised JSON."""
    for include_str in (*_LOG_INCLUDE_LEVELS, None):
        try:
            params = {"include": include_str} if include_str else {}
            result = client.get(f"log/{log_type}/{log_id}", params=params)
            included = {r["id"]: r for r in result.get("included", [])} if include_str else {}
            return json.dumps(_normalize_log(result.get("data", {}), included), indent=2)
        except Exception:
            if include_str is None:
                raise


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


def _build_asset_rels(client, ids: list[str]) -> list[dict]:
    """Resolve asset UUIDs to typed JSON:API relationship entries."""
    return [{"type": f"asset--{_lookup_asset_type(client, aid)}", "id": aid} for aid in ids]


def _normalize_measure(measure: str) -> str:
    """Normalise a measure string to the lowercase snake_case farmOS expects."""
    return measure.lower().replace(" ", "_").replace("/", "_")


def _create_quantity(client, qty: dict) -> tuple[str, Optional[int]]:
    """POST a new quantity resource and return (uuid, revision_id).

    qty dict fields:
        measure: e.g. 'weight', 'count', 'volume', 'area', 'length',
                 'time', 'temperature', 'pressure', 'water_content',
                 'value', 'rate', 'rating', 'ratio', 'probability'
        value: decimal number
        label: optional string to distinguish multiple quantities on the same log
        units_uuid: optional UUID of a taxonomy_term--unit term
        type: quantity bundle — 'standard' (default), 'material', 'test'
        inventory_adjustment: 'increment', 'decrement', or 'reset'
    """
    qty_type = qty.get("type", "standard")
    payload: dict = {
        "type": f"quantity--{qty_type}",
        "attributes": {"measure": _normalize_measure(qty["measure"])},
    }
    if qty.get("value") is not None:
        payload["attributes"]["value"] = {"decimal": str(float(qty["value"]))}
    if qty.get("label"):
        payload["attributes"]["label"] = qty["label"]
    if qty.get("inventory_adjustment"):
        payload["attributes"]["inventory_adjustment"] = qty["inventory_adjustment"]
    if qty.get("units_uuid"):
        payload["relationships"] = {
            "units": {"data": {"type": "taxonomy_term--unit", "id": qty["units_uuid"]}}
        }
    result = client.post(f"quantity/{qty_type}", payload)
    data = result.get("data", {})
    uuid = data.get("id")
    revision_id = data.get("meta", {}).get("drupal_internal__revision_id")

    # Fallback: if the POST response didn't include the revision ID, fetch it
    if revision_id is None and uuid:
        try:
            fetched = client.get(f"quantity/{qty_type}/{uuid}")
            revision_id = fetched.get("data", {}).get("meta", {}).get("drupal_internal__revision_id")
        except Exception:
            pass

    return uuid, revision_id


def _build_qty_rels(client, quantities: list[dict]) -> list[dict]:
    """Create quantity resources and return relationship entries with revision IDs."""
    rels = []
    for qty in quantities:
        uuid, revision_id = _create_quantity(client, qty)
        entry: dict = {"type": f"quantity--{qty.get('type', 'standard')}", "id": uuid}
        if revision_id is not None:
            entry["meta"] = {"target_revision_id": revision_id}
        rels.append(entry)
    return rels


def create_log(
    log_type: str,
    name: str,
    status: str = "pending",
    notes: Optional[str] = None,
    timestamp: Optional[str] = None,
    asset_ids: Optional[list[str]] = None,
    location_ids: Optional[list[str]] = None,
    owner_ids: Optional[list[str]] = None,
    category_ids: Optional[list[str]] = None,
    equipment_ids: Optional[list[str]] = None,
    flags: Optional[list[str]] = None,
    is_movement: Optional[bool] = None,
    is_group_assignment: Optional[bool] = None,
    quantities: Optional[list[dict]] = None,
    data: Optional[str] = None,
    lot_number: Optional[str] = None,
    purchase_date: Optional[str] = None,
    source: Optional[str] = None,
    method: Optional[str] = None,
) -> str:
    """Create a new log in farmOS.

    Args:
        log_type: Log bundle — 'activity', 'observation', 'harvest', 'input',
                  'maintenance', 'seeding', 'transplanting', 'purchase', 'sale'.
        name: Name/title of the log.
        status: 'pending' (default), 'done', or 'abandoned'.
        notes: Optional plain-text notes.
        timestamp: ISO 8601 datetime. Defaults to now.
        asset_ids: UUIDs of assets this log relates to.
        location_ids: UUIDs of location assets where this took place.
        owner_ids: UUIDs of users assigned to this log.
        category_ids: UUIDs of log_category taxonomy terms for categorisation.
        equipment_ids: UUIDs of equipment assets used.
        flags: Flag strings — 'priority', 'needs_review', 'monitor'.
        is_movement: If true, assets are moved to the specified locations.
        is_group_assignment: If true, assets are assigned to the referenced groups.
        quantities: List of quantity dicts. Each may include:
                    'measure' (required, e.g. 'weight', 'count', 'volume', 'area',
                    'length', 'time', 'temperature', 'pressure', 'water_content',
                    'value', 'rate', 'rating', 'ratio', 'probability'),
                    'value' (decimal), 'label', 'units_uuid' (UUID of unit term),
                    'type' ('standard'|'material'|'test'),
                    'inventory_adjustment' ('increment'|'decrement'|'reset').
        data: Arbitrary string (JSON/YAML) stored as API-only metadata.
        lot_number: Lot/batch number (harvest, input, seeding logs).
        purchase_date: ISO 8601 date of purchase (input, seeding logs).
        source: Source description (input, seeding logs).
        method: Method description (input logs).

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

        if notes is not None:
            payload["attributes"]["notes"] = {"value": notes, "format": "default"}
        if flags is not None:
            payload["attributes"]["flags"] = flags
        if is_movement is not None:
            payload["attributes"]["is_movement"] = is_movement
        if is_group_assignment is not None:
            payload["attributes"]["is_group_assignment"] = is_group_assignment
        if data is not None:
            payload["attributes"]["data"] = data
        if lot_number is not None:
            payload["attributes"]["lot_number"] = lot_number
        if purchase_date is not None:
            payload["attributes"]["purchase_date"] = _iso_to_ts(purchase_date)
        if source is not None:
            payload["attributes"]["source"] = source
        if method is not None:
            payload["attributes"]["method"] = method

        rels: dict = {}
        if asset_ids:
            rels["asset"] = {"data": _build_asset_rels(client, asset_ids)}
        if location_ids:
            rels["location"] = {"data": _build_asset_rels(client, location_ids)}
        if equipment_ids:
            rels["equipment"] = {"data": [{"type": "asset--equipment", "id": eid} for eid in equipment_ids]}
        if owner_ids:
            rels["owner"] = {"data": [{"type": "user--user", "id": uid} for uid in owner_ids]}
        if category_ids:
            rels["category"] = {"data": [{"type": "taxonomy_term--log_category", "id": cid} for cid in category_ids]}
        if quantities:
            rels["quantity"] = {"data": _build_qty_rels(client, quantities)}
        if rels:
            payload["relationships"] = rels

        result = client.post(f"log/{log_type}", payload)
        log_id = result.get("data", {}).get("id")
        if log_id:
            return _fetch_log(client, log_type, log_id)
        return json.dumps(_normalize_log(result.get("data", {})), indent=2)

    except Exception as e:
        return json.dumps({"error": str(e)})


def update_log(
    id: str,
    log_type: str,
    name: Optional[str] = None,
    status: Optional[str] = None,
    notes: Optional[str] = None,
    timestamp: Optional[str] = None,
    asset_ids: Optional[list[str]] = None,
    location_ids: Optional[list[str]] = None,
    owner_ids: Optional[list[str]] = None,
    category_ids: Optional[list[str]] = None,
    equipment_ids: Optional[list[str]] = None,
    flags: Optional[list[str]] = None,
    is_movement: Optional[bool] = None,
    is_group_assignment: Optional[bool] = None,
    quantities: Optional[list[dict]] = None,
    data: Optional[str] = None,
    lot_number: Optional[str] = None,
    purchase_date: Optional[str] = None,
    source: Optional[str] = None,
    method: Optional[str] = None,
) -> str:
    """Update fields on an existing farmOS log.

    Args:
        id: UUID of the log.
        log_type: Bundle of the log (required for PATCH), e.g. 'observation'.
        name: New name (optional).
        status: New status — 'pending', 'done', or 'abandoned' (optional).
        notes: New notes text (optional). Replaces existing notes.
        timestamp: New ISO 8601 datetime (optional).
        asset_ids: Replace linked assets. Pass [] to clear all.
        location_ids: Replace linked locations. Pass [] to clear all.
        owner_ids: Replace assigned owners. Pass [] to clear all.
        category_ids: Replace categories. Pass [] to clear all.
        equipment_ids: Replace equipment used. Pass [] to clear all.
        flags: Replace flags list. Pass [] to clear all.
        is_movement: Update movement flag (optional).
        is_group_assignment: Update group assignment flag (optional).
        quantities: Replace quantities with new ones. Each dict: 'measure' (e.g.
                    'weight', 'count', 'volume'), 'value', 'label', 'units_uuid',
                    'type', 'inventory_adjustment'.
        data: Replace API-only metadata string (optional).
        lot_number: Update lot number (harvest, input, seeding logs).
        purchase_date: Update purchase date ISO 8601 (input, seeding logs).
        source: Update source description (input, seeding logs).
        method: Update method description (input logs).

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
        if timestamp is not None:
            payload["attributes"]["timestamp"] = _iso_to_ts(timestamp)
        if flags is not None:
            payload["attributes"]["flags"] = flags
        if is_movement is not None:
            payload["attributes"]["is_movement"] = is_movement
        if is_group_assignment is not None:
            payload["attributes"]["is_group_assignment"] = is_group_assignment
        if data is not None:
            payload["attributes"]["data"] = data
        if lot_number is not None:
            payload["attributes"]["lot_number"] = lot_number
        if purchase_date is not None:
            payload["attributes"]["purchase_date"] = _iso_to_ts(purchase_date)
        if source is not None:
            payload["attributes"]["source"] = source
        if method is not None:
            payload["attributes"]["method"] = method

        rels: dict = {}
        if asset_ids is not None:
            rels["asset"] = {"data": _build_asset_rels(client, asset_ids)}
        if location_ids is not None:
            rels["location"] = {"data": _build_asset_rels(client, location_ids)}
        if equipment_ids is not None:
            rels["equipment"] = {"data": [{"type": "asset--equipment", "id": eid} for eid in equipment_ids]}
        if owner_ids is not None:
            rels["owner"] = {"data": [{"type": "user--user", "id": uid} for uid in owner_ids]}
        if category_ids is not None:
            rels["category"] = {"data": [{"type": "taxonomy_term--log_category", "id": cid} for cid in category_ids]}
        if quantities is not None:
            rels["quantity"] = {"data": _build_qty_rels(client, quantities)}
        if rels:
            payload["relationships"] = rels

        client.patch(f"log/{log_type}/{id}", payload)
        return _fetch_log(client, log_type, id)

    except Exception as e:
        return json.dumps({"error": str(e)})
