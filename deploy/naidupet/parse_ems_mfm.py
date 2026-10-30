"""Parses ems_mfm.md and cross-checks it with the v1 metadata dump.
Usage: python parse_ems_mfm.py <ems_mfm.md> <meta dump .sql.gz> <out.json>"""
import gzip, json, re, sys
from collections import Counter, defaultdict

md = open(sys.argv[1], encoding="utf-8").read().splitlines()


def cells(line):
    return [c.strip() for c in line.strip().strip("|").split("|")]


def name_of(cell):  # "UPS-A [1000204; raw 204]" -> "UPS-A"
    return re.sub(r"\s*\[[^\]]*\]\s*$", "", cell).strip()


panels, standalone, register = [], [], {}
section = None
for line in md:
    m = re.match(r"^## Distribution panel: (.+)$", line)
    if m:
        section = {"name": m.group(1).strip(), "members": []}
        panels.append(section)
        continue
    if line.startswith("## MFMs without"):
        section = "standalone"
        continue
    if line.startswith("## Complete meter"):
        section = "register"
        continue
    if line.startswith("## "):
        section = None
        continue
    if not line.startswith("| ") or line.startswith("| MFM") or line.startswith("|---"):
        continue
    c = cells(line)
    if isinstance(section, dict):
        section["members"].append({"mfm": name_of(c[0]), "role": c[2], "table": c[5], "schema": c[6].split(" (")[0]})
    elif section == "standalone":
        standalone.append({"mfm": name_of(c[0]), "table": c[5], "schema": c[6].split(" (")[0], "nav": c[8]})
    elif section == "register":
        register[c[0]] = {"device": c[3], "schema_id": c[5]}

summary_cat = {}
for line in md:
    m = re.match(r"^\| (.+?) \[Group \d+\] \| (\w+) \| True", line)
    if m:
        summary_cat[m.group(1)] = m.group(2)
for p in panels:
    p["category"] = summary_cat.get(p["name"])

blocks, cur, cols = {}, None, None
with gzip.open(sys.argv[2], "rt", encoding="utf-8") as f:
    for line in f:
        line = line.rstrip("\n")
        m = re.match(r"^COPY public\.(\w+) \((.*)\) FROM stdin;$", line)
        if m:
            cur, cols = m.group(1), [x.strip().strip('"') for x in m.group(2).split(",")]
            blocks[cur] = []
            continue
        if line == "\\.":
            cur = None
            continue
        if cur:
            blocks[cur].append(dict(zip(cols, [None if v == "\\N" else v for v in line.split("\t")])))

tables = defaultdict(list)
for t in blocks["app_device_tables"]:
    tables[t["name"]].append(t)
schemas = {s["id"]: s["name"] for s in blocks["app_schemas"]}
devices = {d["id"]: d for d in blocks["app_devices"]}

problems = []
all_mfms = [(p["name"], m) for p in panels for m in p["members"]] + [("(standalone)", m) for m in standalone]
for where, m in all_mfms:
    rows = tables.get(m["table"])
    if not rows:
        problems.append(f"{where}: {m['mfm']}: table {m['table']} not in LoggerFast")
        continue
    if len(rows) > 1:
        problems.append(f"{where}: {m['mfm']}: table name {m['table']} is used {len(rows)} times")
    t = rows[0]
    if schemas.get(t["schema_id"]) != m["schema"]:
        problems.append(f"{where}: {m['mfm']}: schema {m['schema']} in EMS, {schemas.get(t['schema_id'])} in LoggerFast")
    if t["status"] != "migrated":
        problems.append(f"{where}: {m['mfm']}: table {m['table']} is {t['status']}")
regs = [(k, v) for k, v in register.items()]
used_tables = Counter(m["table"] for _, m in all_mfms)
dup_names = Counter(m["mfm"].lower() for _, m in all_mfms)

print("panels:", [(p["name"], p["category"], dict(Counter(m["role"] for m in p["members"]))) for p in panels])
print("standalone:", len(standalone), Counter(m["nav"] for m in standalone))
print("MFMs:", len(all_mfms), "| register rows:", len(register))
print("tables used twice:", [t for t, n in used_tables.items() if n > 1])
print("MFM names used twice:", [n for n, k in dup_names.items() if k > 1])
print("LoggerFast tables not in the EMS file:", sorted(set(tables) - set(used_tables)))
print("problems:", problems or "none")
json.dump({"panels": panels, "standalone": standalone,
           "table_device": {name: rows[0]["device_id"] for name, rows in tables.items()},
           "device_volts": {d: devices[d].get("nominal_voltage") for d in devices}},
          open(sys.argv[3], "w"), indent=1)
