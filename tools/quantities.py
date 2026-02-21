import json
from typing import Optional

from farmos_client import get_client

QUANTITY_TYPES = ["standard", "material", "test"]


def _parse_qty_value(value) -> Optional[float]:
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


def _normalize_quantity(resource: dict) -> dict:
    attrs = resource.get("attributes", {})
    rels = resource.get("relationships", {})

    unit_data = rels.get("units", {}).get("data")
    unit = None
    if isinstance(unit_data, dict) and unit_data.get("id"):
        unit = {"id": unit_data["id"], "type": unit_data["type"].split("--", 1)[-1]}

    result = {
        "id": resource.get("id"),
        "type": resource.get("type", "").split("--", 1)[-1],
        "measure": attrs.get("measure"),
        "value": _parse_qty_value(attrs.get("value")),
        "label": attrs.get("label"),
        "unit": unit,
        "inventory_adjustment": attrs.get("inventory_adjustment"),
    }

    # material quantities can reference material_type terms
    mat_type_data = rels.get("material_type", {}).get("data")
    if mat_type_data:
        items = mat_type_data if isinstance(mat_type_data, list) else [mat_type_data]
        refs = [{"id": r["id"], "type": r["type"].split("--", 1)[-1]} for r in items if isinstance(r, dict) and r.get("id")]
        if refs:
            result["material_type"] = refs

    # test quantities can reference test_method terms
    test_method_data = rels.get("test_method", {}).get("data")
    if isinstance(test_method_data, dict) and test_method_data.get("id"):
        result["test_method"] = {"id": test_method_data["id"], "type": test_method_data["type"].split("--", 1)[-1]}

    return result


def get_quantities(
    quantity_type: Optional[str] = None,
    measure: Optional[str] = None,
    limit: int = 50,
    offset: int = 0,
) -> str:
    """List quantity entities from farmOS.

    Quantities record measured values on logs (weight, count, volume, etc.)
    and can carry inventory adjustments. Useful for auditing stock levels
    or reviewing measurements across logs.

    Args:
        quantity_type: Bundle — 'standard', 'material', or 'test'.
                       Omit to query all three types.
        measure: Filter by measure type, e.g. 'weight', 'count', 'volume',
                 'area', 'length', 'time', 'temperature', 'pressure',
                 'water_content', 'value', 'rate', 'rating', 'ratio', 'probability'.
        limit: Max quantities to return (default 50, max 100).
        offset: Pagination offset — only applies when quantity_type is specified.

    Returns:
        JSON with 'quantities' list and 'returned' count.
    """
    try:
        client = get_client()
        params: dict = {}
        if measure:
            params["filter[measure]"] = measure

        if quantity_type:
            params["page[limit]"] = min(limit, 100)
            params["page[offset]"] = offset
            result = client.get(f"quantity/{quantity_type}", params=params)
            quantities = [_normalize_quantity(r) for r in result.get("data", [])]
            total = result.get("meta", {}).get("count", len(quantities))
            return json.dumps({"total": total, "returned": len(quantities), "quantities": quantities}, indent=2)

        params["page[limit]"] = min(limit, 100)
        all_quantities: list[dict] = []
        for t in QUANTITY_TYPES:
            try:
                result = client.get(f"quantity/{t}", params=params)
                all_quantities.extend(_normalize_quantity(r) for r in result.get("data", []))
            except Exception:
                pass

        all_quantities = all_quantities[:limit]
        return json.dumps({"returned": len(all_quantities), "quantities": all_quantities}, indent=2)

    except Exception as e:
        return json.dumps({"error": str(e)})
