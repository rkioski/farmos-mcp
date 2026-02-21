import json
from typing import Optional

from farmos_client import get_client

# Standard taxonomy vocabularies in farmOS 3.x
VOCABULARIES = [
    "animal_type",
    "crop_family",
    "equipment_type",
    "lab",
    "log_category",
    "material_type",
    "plant_type",
    "product_type",
    "season",
    "test_method",
    "unit",
]


def _normalize_term(resource: dict) -> dict:
    attrs = resource.get("attributes", {})
    return {
        "id": resource.get("id"),
        "vocabulary": resource.get("type", "").split("--", 1)[-1],
        "name": attrs.get("name"),
        "description": (attrs.get("description") or {}).get("value") if isinstance(attrs.get("description"), dict) else attrs.get("description"),
    }


def get_terms(
    vocabulary: str,
    name: Optional[str] = None,
    limit: int = 100,
    offset: int = 0,
) -> str:
    """List taxonomy terms from a farmOS vocabulary.

    Useful for discovering available units, categories, animal types, plant types, etc.
    Use term UUIDs when setting category_ids or units_uuid on logs and quantities.

    Args:
        vocabulary: Vocabulary machine name — one of:
                    'unit' (quantity units: kg, L, m², etc.),
                    'log_category' (log categories),
                    'animal_type' (animal species/breeds),
                    'plant_type' (plant varieties/crops),
                    'crop_family' (botanical families),
                    'material_type' (input/material types),
                    'equipment_type' (equipment categories),
                    'season' (seasons/time periods),
                    'lab' (laboratories for lab test logs),
                    'product_type' (product categories),
                    'test_method' (methods for test quantities).
        name: Filter by name (optional).
        limit: Max terms to return (default 100).
        offset: Pagination offset.

    Returns:
        JSON with 'terms' list and 'returned' count.
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

        result = client.get(f"taxonomy_term/{vocabulary}", params=params)
        terms = [_normalize_term(r) for r in result.get("data", [])]
        total = result.get("meta", {}).get("count", len(terms))
        return json.dumps({"total": total, "returned": len(terms), "terms": terms}, indent=2)

    except Exception as e:
        return json.dumps({"error": str(e)})


# ---------------------------------------------------------------------------
# Write tools — only registered when FARMOS_READ_ONLY=false
# ---------------------------------------------------------------------------

def create_term(
    vocabulary: str,
    name: str,
    description: Optional[str] = None,
) -> str:
    """Create a new taxonomy term in a farmOS vocabulary.

    Useful for adding units (e.g. 'l', 'kg', 'ha'), log categories, plant types, etc.

    Args:
        vocabulary: Vocabulary machine name — 'unit', 'log_category', 'animal_type',
                    'plant_type', 'crop_family', 'material_type', 'equipment_type',
                    'season', 'lab', 'product_type', 'test_method'.
        name: Name of the new term.
        description: Optional description.

    Returns:
        JSON of the created term including its UUID.
    """
    try:
        client = get_client()
        payload: dict = {
            "type": f"taxonomy_term--{vocabulary}",
            "attributes": {"name": name},
        }
        if description is not None:
            payload["attributes"]["description"] = {"value": description, "format": "default"}

        result = client.post(f"taxonomy_term/{vocabulary}", payload)
        return json.dumps(_normalize_term(result.get("data", {})), indent=2)

    except Exception as e:
        return json.dumps({"error": str(e)})


def update_term(
    id: str,
    vocabulary: str,
    name: Optional[str] = None,
    description: Optional[str] = None,
) -> str:
    """Update an existing taxonomy term.

    Args:
        id: UUID of the term.
        vocabulary: Vocabulary machine name (required for PATCH), e.g. 'unit'.
        name: New name (optional).
        description: New description (optional). Pass empty string to clear.

    Returns:
        JSON of the updated term.
    """
    try:
        client = get_client()
        payload: dict = {
            "type": f"taxonomy_term--{vocabulary}",
            "id": id,
            "attributes": {},
        }
        if name is not None:
            payload["attributes"]["name"] = name
        if description is not None:
            payload["attributes"]["description"] = {"value": description, "format": "default"}

        result = client.patch(f"taxonomy_term/{vocabulary}/{id}", payload)
        return json.dumps(_normalize_term(result.get("data", {})), indent=2)

    except Exception as e:
        return json.dumps({"error": str(e)})
