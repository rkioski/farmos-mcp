import json

from farmos_client import get_client


def get_farm_info() -> str:
    """Get information about the farmOS instance.

    Returns the farm name, farmOS version, system of measurement, and
    the currently authenticated user. Useful for orientation and for
    confirming which farm and user account the server is connected to.

    Returns:
        JSON with farm metadata fields from the JSON:API root document.
    """
    try:
        client = get_client()
        # The JSON:API root document (/api) includes farmOS-specific metadata
        # in the 'meta' field: farm name, version, units system, current user.
        result = client.get("")
        meta = result.get("meta", {})

        info: dict = {}
        for key in ("farm_name", "farmos_version", "system_of_measurement", "user"):
            if key in meta:
                info[key] = meta[key]

        if not info:
            # Unexpected response shape — return raw meta for inspection
            info = {"raw_meta": meta}

        return json.dumps(info, indent=2)

    except Exception as e:
        return json.dumps({"error": str(e)})
