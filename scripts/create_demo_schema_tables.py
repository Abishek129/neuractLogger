from __future__ import annotations

import random
import sys
from pathlib import Path


def _repo_root() -> Path:
    return Path(__file__).resolve().parents[2]


def _normalize_type(ftype: str) -> str:
    t = (ftype or "").strip().lower()
    if t in ("int", "integer"):
        return "int"
    if t in ("bool", "boolean"):
        return "bool"
    if t in ("string", "str", "text"):
        return "string"
    return "float"


def main() -> int:
    sys.path.insert(0, str(_repo_root()))

    from plc_logger.agent.plc_agent.api.store import Store
    from plc_logger.agent.plc_agent.api.routers import mappings as mappings_router
    from plc_logger.agent.plc_agent.api.routers import tables as tables_router

    schema_name = "DemoSchema10"
    table_names = [f"Device{i}" for i in range(1, 11)]
    device_nodes = [f"Device{i}" for i in range(1, 11)]

    store = Store.instance()
    store.load_from_app_db()

    schema = next((s for s in store.list_schemas() if (s.get("name") or "").strip() == schema_name), None)
    if not schema:
        print(f"Schema not found: {schema_name}")
        return 1

    fields = schema.get("fields") or []
    if not fields:
        print(f"Schema has no fields: {schema_name}")
        return 1

    opcua_devices = [d for d in store.list_devices() if (d.get("protocol") or "").lower() == "opcua"]
    if not opcua_devices:
        print("No OPC UA device found. Create/connect an OPC UA device first.")
        return 1
    device_id = opcua_devices[0]["id"]

    default_target = store.get_default_db_target()
    existing = {t.get("name"): t for t in store.list_tables(parent_schema_id=schema.get("id"))}
    missing = [name for name in table_names if name not in existing]

    if missing:
        created = store.add_tables_bulk(schema.get("id"), missing, default_target)
        for t in created:
            existing[t.get("name")] = t

    table_ids = []
    for name in table_names:
        tbl = existing.get(name)
        if not tbl:
            print(f"Skipping missing table entry: {name}")
            continue
        table_ids.append(tbl.get("id"))
        rows = {}
        for fld in fields:
            key = fld.get("key")
            if not key:
                continue
            device_pick = random.choice(device_nodes)
            rows[key] = {
                "protocol": "opcua",
                "address": f"ns=2;s={device_pick}.Temperature",
                "dataType": _normalize_type(fld.get("type") or ""),
                "scale": fld.get("scale") if fld.get("scale") is not None else 1,
                "deadband": 0,
            }
        store.replace_mapping(tbl.get("id"), {"deviceId": device_id, "rows": rows})
        mappings_router._replace_mapping_in_user_db(tbl, rows, device_id=device_id)

    if table_ids:
        tables_router.migrate({"ids": table_ids})

    print(f"Created/updated {len(table_names)} tables for schema {schema_name}.")
    print("Mappings point to random Device1..Device10 Temperature nodes (repetitions allowed).")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
