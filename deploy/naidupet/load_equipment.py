"""Equipment half of 5-load-equipment.sh. Run by that script as user loggerfast;
not meant to be run on its own.

Imports the workbook through the same code as POST /equipment/import/ems
(all or nothing; a dry run saves nothing). The importer only references types,
so the panel types the EMS categories need are created on first use, inside
the import's own transaction: a dry run or a failed import leaves no type
behind.

Usage: python load_equipment.py <workbook.xlsx> [--commit]
Prints counts and every failed row.
"""
import sys
from pathlib import Path

from plc_agent.api import equipment as eq
from plc_agent.api import equipment_import as imp

_VOLTAGE = {"id": "bus_voltage", "label": "Bus / operating voltage", "kind": "quantity",
            "units": ["kV", "V"], "required": True, "role": "voltage"}
TYPES = {n.lower(): n for n in ("AMF Panel", "PCC Panel", "UPS Panel", "Utility Panel", "Production Panel")}
created_types = set()

_find_type = imp._type_id


def _type_id(c, ref):
    try:
        return _find_type(c, ref)
    except eq.EquipmentError as e:
        if e.code != "TYPE_NOT_FOUND" or ref.lower() not in TYPES:
            raise
    created_types.add(TYPES[ref.lower()])
    return eq.create_type({"name": TYPES[ref.lower()], "fields": [_VOLTAGE]})["id"]


imp._type_id = _type_id


def main():
    path, commit = Path(sys.argv[1]), "--commit" in sys.argv[2:]
    report = imp.import_ems(path.name, path.read_bytes(), dry_run=not commit)
    s = report["summary"]
    for sheet in ("elements", "buses", "connections", "meters"):
        counts = ", ".join(f"{k} {v}" for k, v in s[sheet].items() if v)
        print(f"   {sheet:12} {counts or '-'}")
    print(f"   types the import {'created' if report['saved'] else 'would create'}: {', '.join(sorted(created_types)) or 'none'}")
    failed = [r for r in report["results"] if r["status"] == "failed"]
    for r in failed:
        print(f"   FAILED {r['sheet']} row {r['row']} ({r['key']}): {r['error']}")
    print(f"   errors {len(failed)}; {'SAVED' if report['saved'] else 'nothing saved'}")
    return 0 if report["success"] else 1


if __name__ == "__main__":
    sys.exit(main())
