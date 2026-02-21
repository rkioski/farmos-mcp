import json
from typing import Optional

from farmos_client import get_client

# All standard asset bundle types in farmOS 2.x
ASSET_TYPES = [
    "animal",
    "equipment",
    "land",
    "material",
    "plant",
    "sensor",
    "structure",
    "water",
]


# ---------------------------------------------------------------------------
# Normalisation helpers
# ---------------------------------------------------------------------------

def _notes_text(field) -> Optional[str]:
    if field is None:
        return None
    if isinstance(field, dict):
        return field.get("value")
    return str(field)


def _refs(rel_data) -> list[dict]:
    items = rel_data if isinstance(rel_data, list) else ([rel_data] if rel_data else [])
    return [
        {"id": r["id"], "type": r["type"].split("--", 1)[-1]}
        for r in items
        if isinstance(r, dict) and r.get("id")
    ]


def _normalize_asset(resource: dict) -> dict:
    attrs = resource.get("attributes", {})
    rels = resource.get("relationships", {})

    return {
        "id": resource.get("id"),
        "type": resource.get("type", "").split("--", 1)[-1],
        "name": attrs.get("name"),
        "status": attrs.get("status"),
        "notes": _notes_text(attrs.get("notes")),
        "parents": _refs(rels.get("parent", {}).get("data")),
    }


# ---------------------------------------------------------------------------
# Read tools
# ---------------------------------------------------------------------------

def get_assets(
    asset_type: Optional[str] = None,
    status: Optional[str] = None,
    name: Optional[str] = None,
    limit: int = 20,
    offset: int = 0,
) -> str:
    """List assets from farmOS. Filter by type, status, or name.

    Common asset types: 'land' (fields, beds, greenhouses), 'plant', 'animal',
    'equipment', 'structure', 'water', 'material', 'sensor'.

    Args:
        asset_type: Bundle without prefix: 'land', 'plant', 'animal', 'equipment', etc.
                    Omit to query all types.
        status: 'active' or 'archived'. Omit for both.
        name: Filter by exact name.
        limit: Max assets to return (default 20, max 100).
        offset: Pagination offset — only applies when asset_type is specified.

    Returns:
        JSON with 'assets' list and 'returned' count.
    """
    try:
        client = get_client()
        params: dict = {"sort": "name"}

        if status:
            params["filter[status]"] = status
        if name:
            params["filter[name]"] = name

        if asset_type:
            params["page[limit]"] = min(limit, 100)
            params["page[offset]"] = offset
            result = client.get(f"asset/{asset_type}", params=params)
            assets = [_normalize_asset(r) for r in result.get("data", [])]
            total = result.get("meta", {}).get("count", len(assets))
            return json.dumps({"total": total, "returned": len(assets), "assets": assets}, indent=2)

        # No type — query all known types, merge, trim
        params["page[limit]"] = min(limit, 100)
        all_assets: list[dict] = []
        for t in ASSET_TYPES:
            try:
                result = client.get(f"asset/{t}", params=params)
                all_assets.extend(_normalize_asset(r) for r in result.get("data", []))
            except Exception:
                pass

        all_assets.sort(key=lambda x: (x.get("name") or "").lower())
        all_assets = all_assets[:limit]
        return json.dumps({"returned": len(all_assets), "assets": all_assets}, indent=2)

    except Exception as e:
        return json.dumps({"error": str(e)})


def get_asset(id: str, asset_type: Optional[str] = None) -> str:
    """Get a single farmOS asset by UUID.

    Args:
        id: UUID of the asset.
        asset_type: Bundle if known (e.g. 'land'). Speeds up the lookup.

    Returns:
        JSON with asset details.
    """
    try:
        client = get_client()
        types_to_try = [asset_type] if asset_type else ASSET_TYPES

        for t in types_to_try:
            try:
                result = client.get(f"asset/{t}/{id}")
                data = result.get("data")
                if data:
                    return json.dumps(_normalize_asset(data), indent=2)
            except Exception:
                continue

        return json.dumps({"error": f"Asset {id} not found"})

    except Exception as e:
        return json.dumps({"error": str(e)})
