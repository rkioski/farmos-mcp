import json
from datetime import datetime, timezone
from typing import Optional

from farmos_client import get_client

# Standard asset bundle types in farmOS 3.x
ASSET_TYPES = [
    "animal",
    "compost",
    "equipment",
    "group",
    "land",
    "material",
    "plant",
    "product",
    "sensor",
    "structure",
    "water",
]

# Relationships to sideload when fetching a single asset
_ASSET_INCLUDE = "parent,owner,animal_type,plant_type,season,equipment_type,material_type"


# ---------------------------------------------------------------------------
# Normalisation helpers
# ---------------------------------------------------------------------------

def _notes_text(field) -> Optional[str]:
    if field is None:
        return None
    if isinstance(field, dict):
        return field.get("value")
    return str(field)


def _ts_to_iso(ts) -> Optional[str]:
    if ts is None:
        return None
    try:
        return datetime.fromtimestamp(int(ts), tz=timezone.utc).isoformat()
    except (ValueError, TypeError):
        return str(ts)


def _iso_to_ts(date_str: str) -> int:
    if "T" not in date_str:
        date_str = f"{date_str}T00:00:00Z"
    return int(datetime.fromisoformat(date_str.replace("Z", "+00:00")).timestamp())


def _refs(rel_data) -> list[dict]:
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


def _normalize_asset(resource: dict, included: dict | None = None) -> dict:
    attrs = resource.get("attributes", {})
    rels = resource.get("relationships", {})
    asset_type = resource.get("type", "").split("--", 1)[-1]
    inc = included or {}

    parents = _refs(rels.get("parent", {}).get("data"))
    owners = _refs(rels.get("owner", {}).get("data"))
    if inc:
        _resolve_names(parents, inc)
        _resolve_names(owners, inc)

    result = {
        "id": resource.get("id"),
        "type": asset_type,
        "name": attrs.get("name"),
        "status": attrs.get("status"),
        "notes": _notes_text(attrs.get("notes")),
        "parents": parents,
        "owners": owners,
    }

    # Inventory is computed (read-only) — summarises stock levels from quantity logs
    inventory = attrs.get("inventory")
    if inventory:
        result["inventory"] = inventory

    # --- Type-specific fields ---
    if asset_type == "animal":
        for field in ("sex", "nicknames", "is_sterile"):
            val = attrs.get(field)
            if val is not None:
                result[field] = val
        if attrs.get("birthdate") is not None:
            result["birthdate"] = _ts_to_iso(attrs["birthdate"])
        animal_type_refs = _refs(rels.get("animal_type", {}).get("data"))
        if inc:
            _resolve_names(animal_type_refs, inc)
        if animal_type_refs:
            result["animal_type"] = animal_type_refs

    elif asset_type == "plant":
        plant_type_refs = _refs(rels.get("plant_type", {}).get("data"))
        season_refs = _refs(rels.get("season", {}).get("data"))
        if inc:
            _resolve_names(plant_type_refs, inc)
            _resolve_names(season_refs, inc)
        if plant_type_refs:
            result["plant_type"] = plant_type_refs
        if season_refs:
            result["season"] = season_refs

    elif asset_type == "equipment":
        for field in ("manufacturer", "model", "serial_number"):
            val = attrs.get(field)
            if val is not None:
                result[field] = val
        eq_type_refs = _refs(rels.get("equipment_type", {}).get("data"))
        if inc:
            _resolve_names(eq_type_refs, inc)
        if eq_type_refs:
            result["equipment_type"] = eq_type_refs

    elif asset_type == "land":
        val = attrs.get("land_type")
        if val is not None:
            result["land_type"] = val

    elif asset_type == "structure":
        val = attrs.get("structure_type")
        if val is not None:
            result["structure_type"] = val

    elif asset_type == "material":
        mat_type_refs = _refs(rels.get("material_type", {}).get("data"))
        if inc:
            _resolve_names(mat_type_refs, inc)
        if mat_type_refs:
            result["material_type"] = mat_type_refs

    return result


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
    """Get a single farmOS asset by UUID, including type-specific fields and resolved names.

    Args:
        id: UUID of the asset.
        asset_type: Bundle if known (e.g. 'land'). Speeds up the lookup.

    Returns:
        JSON with full asset details including type-specific fields and inventory.
    """
    try:
        client = get_client()
        types_to_try = [asset_type] if asset_type else ASSET_TYPES
        errors: list[str] = []

        for t in types_to_try:
            result = None
            included: dict = {}
            for use_include in (True, False):
                try:
                    params = {"include": _ASSET_INCLUDE} if use_include else {}
                    result = client.get(f"asset/{t}/{id}", params=params)
                    if use_include:
                        included = {r["id"]: r for r in result.get("included", [])}
                    break
                except Exception as e:
                    errors.append(f"{t}{'(+include)' if use_include else ''}: {e}")
                    result = None

            if result is None:
                continue
            data = result.get("data")
            if not data:
                continue
            return json.dumps(_normalize_asset(data, included), indent=2)

        return json.dumps({"error": f"Asset {id} not found", "details": errors})

    except Exception as e:
        return json.dumps({"error": str(e)})


# ---------------------------------------------------------------------------
# Write tools — only registered when FARMOS_READ_ONLY=false
# ---------------------------------------------------------------------------

def _resolve_parent_rels(client, parent_ids: list[str]) -> list[dict]:
    rels = []
    for pid in parent_ids:
        for t in ASSET_TYPES:
            try:
                result = client.get(f"asset/{t}/{pid}")
                if result.get("data"):
                    rels.append({"type": f"asset--{t}", "id": pid})
                    break
            except Exception:
                continue
    return rels


def create_asset(
    asset_type: str,
    name: str,
    status: str = "active",
    notes: Optional[str] = None,
    parent_ids: Optional[list[str]] = None,
    # Animal-specific
    sex: Optional[str] = None,
    birthdate: Optional[str] = None,
    is_sterile: Optional[bool] = None,
    animal_type_id: Optional[str] = None,
    # Plant-specific
    plant_type_ids: Optional[list[str]] = None,
    season_ids: Optional[list[str]] = None,
    # Equipment-specific
    manufacturer: Optional[str] = None,
    model: Optional[str] = None,
    serial_number: Optional[str] = None,
    equipment_type_id: Optional[str] = None,
    # Land-specific
    land_type: Optional[str] = None,
    # Structure-specific
    structure_type: Optional[str] = None,
    # Material-specific
    material_type_ids: Optional[list[str]] = None,
) -> str:
    """Create a new asset in farmOS.

    Args:
        asset_type: Bundle — 'land', 'plant', 'animal', 'equipment', 'structure',
                    'water', 'material', 'sensor', 'product', 'compost', 'group'.
        name: Name of the asset.
        status: 'active' (default) or 'archived'.
        notes: Optional plain-text notes.
        parent_ids: UUIDs of parent assets (e.g. a bed's parent field).
        sex: Animal sex — 'M' or 'F'.
        birthdate: Animal birthdate as ISO 8601 date, e.g. '2023-04-15'.
        is_sterile: Whether the animal is castrated/spayed.
        animal_type_id: UUID of an animal_type taxonomy term.
        plant_type_ids: UUIDs of plant_type taxonomy terms (crop variety).
        season_ids: UUIDs of season taxonomy terms.
        manufacturer: Equipment manufacturer name.
        model: Equipment model name.
        serial_number: Equipment serial number.
        equipment_type_id: UUID of an equipment_type taxonomy term.
        land_type: Land classification — 'field', 'bed', 'greenhouse', 'building',
                   'landmark', 'property', 'water', 'other'.
        structure_type: Structure classification, e.g. 'greenhouse', 'barn'.
        material_type_ids: UUIDs of material_type taxonomy terms.

    Returns:
        JSON of the created asset including its UUID.
    """
    try:
        client = get_client()
        payload: dict = {
            "type": f"asset--{asset_type}",
            "attributes": {
                "name": name,
                "status": status,
            },
        }
        if notes is not None:
            payload["attributes"]["notes"] = {"value": notes, "format": "default"}
        if sex is not None:
            payload["attributes"]["sex"] = sex
        if birthdate is not None:
            payload["attributes"]["birthdate"] = _iso_to_ts(birthdate)
        if is_sterile is not None:
            payload["attributes"]["is_sterile"] = is_sterile
        if manufacturer is not None:
            payload["attributes"]["manufacturer"] = manufacturer
        if model is not None:
            payload["attributes"]["model"] = model
        if serial_number is not None:
            payload["attributes"]["serial_number"] = serial_number
        if land_type is not None:
            payload["attributes"]["land_type"] = land_type
        if structure_type is not None:
            payload["attributes"]["structure_type"] = structure_type

        rels: dict = {}
        if parent_ids:
            parent_rels = _resolve_parent_rels(client, parent_ids)
            if parent_rels:
                rels["parent"] = {"data": parent_rels}
        if animal_type_id is not None:
            rels["animal_type"] = {"data": {"type": "taxonomy_term--animal_type", "id": animal_type_id}}
        if plant_type_ids is not None:
            rels["plant_type"] = {"data": [{"type": "taxonomy_term--plant_type", "id": i} for i in plant_type_ids]}
        if season_ids is not None:
            rels["season"] = {"data": [{"type": "taxonomy_term--season", "id": i} for i in season_ids]}
        if equipment_type_id is not None:
            rels["equipment_type"] = {"data": {"type": "taxonomy_term--equipment_type", "id": equipment_type_id}}
        if material_type_ids is not None:
            rels["material_type"] = {"data": [{"type": "taxonomy_term--material_type", "id": i} for i in material_type_ids]}
        if rels:
            payload["relationships"] = rels

        result = client.post(f"asset/{asset_type}", payload)
        return json.dumps(_normalize_asset(result.get("data", {})), indent=2)

    except Exception as e:
        return json.dumps({"error": str(e)})


def update_asset(
    id: str,
    asset_type: str,
    name: Optional[str] = None,
    status: Optional[str] = None,
    notes: Optional[str] = None,
    parent_ids: Optional[list[str]] = None,
    # Animal-specific
    sex: Optional[str] = None,
    birthdate: Optional[str] = None,
    is_sterile: Optional[bool] = None,
    animal_type_id: Optional[str] = None,
    # Plant-specific
    plant_type_ids: Optional[list[str]] = None,
    season_ids: Optional[list[str]] = None,
    # Equipment-specific
    manufacturer: Optional[str] = None,
    model: Optional[str] = None,
    serial_number: Optional[str] = None,
    equipment_type_id: Optional[str] = None,
    # Land-specific
    land_type: Optional[str] = None,
    # Structure-specific
    structure_type: Optional[str] = None,
    # Material-specific
    material_type_ids: Optional[list[str]] = None,
) -> str:
    """Update an existing farmOS asset.

    Args:
        id: UUID of the asset.
        asset_type: Bundle of the asset (required for PATCH), e.g. 'land'.
        name: New name (optional).
        status: New status — 'active' or 'archived' (optional).
        notes: New notes text (optional). Replaces existing notes.
        parent_ids: Replace parent assets. Pass [] to clear all.
        sex: Animal sex — 'M' or 'F'.
        birthdate: Animal birthdate as ISO 8601 date.
        is_sterile: Whether the animal is castrated/spayed.
        animal_type_id: UUID of an animal_type taxonomy term.
        plant_type_ids: UUIDs of plant_type terms. Pass [] to clear.
        season_ids: UUIDs of season terms. Pass [] to clear.
        manufacturer: Equipment manufacturer name.
        model: Equipment model name.
        serial_number: Equipment serial number.
        equipment_type_id: UUID of an equipment_type taxonomy term.
        land_type: Land classification string.
        structure_type: Structure classification string.
        material_type_ids: UUIDs of material_type terms. Pass [] to clear.

    Returns:
        JSON of the updated asset.
    """
    try:
        client = get_client()
        payload: dict = {
            "type": f"asset--{asset_type}",
            "id": id,
            "attributes": {},
        }
        if name is not None:
            payload["attributes"]["name"] = name
        if status is not None:
            payload["attributes"]["status"] = status
        if notes is not None:
            payload["attributes"]["notes"] = {"value": notes, "format": "default"}
        if sex is not None:
            payload["attributes"]["sex"] = sex
        if birthdate is not None:
            payload["attributes"]["birthdate"] = _iso_to_ts(birthdate)
        if is_sterile is not None:
            payload["attributes"]["is_sterile"] = is_sterile
        if manufacturer is not None:
            payload["attributes"]["manufacturer"] = manufacturer
        if model is not None:
            payload["attributes"]["model"] = model
        if serial_number is not None:
            payload["attributes"]["serial_number"] = serial_number
        if land_type is not None:
            payload["attributes"]["land_type"] = land_type
        if structure_type is not None:
            payload["attributes"]["structure_type"] = structure_type

        rels: dict = {}
        if parent_ids is not None:
            rels["parent"] = {"data": _resolve_parent_rels(client, parent_ids)}
        if animal_type_id is not None:
            rels["animal_type"] = {"data": {"type": "taxonomy_term--animal_type", "id": animal_type_id}}
        if plant_type_ids is not None:
            rels["plant_type"] = {"data": [{"type": "taxonomy_term--plant_type", "id": i} for i in plant_type_ids]}
        if season_ids is not None:
            rels["season"] = {"data": [{"type": "taxonomy_term--season", "id": i} for i in season_ids]}
        if equipment_type_id is not None:
            rels["equipment_type"] = {"data": {"type": "taxonomy_term--equipment_type", "id": equipment_type_id}}
        if material_type_ids is not None:
            rels["material_type"] = {"data": [{"type": "taxonomy_term--material_type", "id": i} for i in material_type_ids]}
        if rels:
            payload["relationships"] = rels

        result = client.patch(f"asset/{asset_type}/{id}", payload)
        return json.dumps(_normalize_asset(result.get("data", {})), indent=2)

    except Exception as e:
        return json.dumps({"error": str(e)})
