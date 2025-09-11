from __future__ import annotations

import threading
import time
from typing import Dict, Any, List, Optional
import logging

from . import appdb


class Store:
    _inst: Optional["Store"] = None
    _lock = threading.Lock()

    def __init__(self) -> None:
        self._mtx = threading.RLock()
        self._schemas: List[Dict[str, Any]] = []
        self._jobs: List[Dict[str, Any]] = []
        self._db_targets: Dict[str, Dict[str, Any]] = {}
        self._default_db_target_id: Optional[str] = None
        # Device tables & mappings
        self._tables: List[Dict[str, Any]] = []
        # mappings: tableId -> { deviceId: str|None, rows: { fieldKey: {protocol,address,dataType,scale,deadband} } }
        self._mappings: Dict[str, Dict[str, Any]] = {}
        # simple migration history (append-only)
        self._migrations: List[Dict[str, Any]] = []
        # Saved devices
        self._devices: Dict[str, Dict[str, Any]] = {}
        # Saved gateways (reachability)
        self._gateways: List[Dict[str, Any]] = []
        # Rate limit tests per gateway id
        self._gw_rate: Dict[str, float] = {}
        # Device reconnect loop state
        self._dev_backoff: Dict[str, Dict[str, Any]] = {}
        self._dev_thread: Optional[threading.Thread] = None
        self._dev_thread_started: bool = False
        # Logger
        self._log = logging.getLogger(__name__)

    @classmethod
    def instance(cls) -> "Store":
        with cls._lock:
            if cls._inst is None:
                cls._inst = Store()
            return cls._inst

    # ---------------- Schemas ----------------
    def list_schemas(self) -> List[Dict[str, Any]]:
        with self._mtx:
            return list(self._schemas)

    def create_schema(self, payload: Dict[str, Any]) -> Dict[str, Any]:
        name = (payload.get("name") or "").strip()
        if not name:
            raise ValueError("name required")
        schema = {
            "id": payload.get("id") or f"sch_{int(time.time()*1000)}",
            "name": name,
            "fields": payload.get("fields") or [],
        }
        with self._mtx:
            # Persist to App Local DB
            appdb.save_schema(schema)
            self._schemas = appdb.load_schemas()
        return schema

    def import_schemas(self, items: List[Dict[str, Any]]) -> int:
        if not isinstance(items, list):
            return 0
        with self._mtx:
            appdb.import_schemas(items)
            self._schemas = appdb.load_schemas()
        return len(items)

    def get_schema(self, schema_id: str) -> Optional[Dict[str, Any]]:
        with self._mtx:
            return next((s for s in self._schemas if s.get("id") == schema_id), None)

    # ---------------- Jobs ----------------
    def list_jobs(self) -> List[Dict[str, Any]]:
        with self._mtx:
            return list(self._jobs)

    def get_job(self, job_id: str) -> Optional[Dict[str, Any]]:
        with self._mtx:
            return next((j for j in self._jobs if j.get("id") == job_id), None)

    def create_job(self, payload: Dict[str, Any]) -> Dict[str, Any]:
        name = (payload.get("name") or "").strip()
        if not name:
            raise ValueError("name required")
        jtype = (payload.get("type") or "continuous").strip().lower()
        if jtype not in ("continuous", "trigger", "triggered"):
            raise ValueError("TYPE_INVALID")
        # Normalize type
        if jtype == "triggered":
            jtype = "trigger"
        tables = payload.get("tables") or []
        if not isinstance(tables, list) or len(tables) == 0:
            raise ValueError("NO_TABLES")
        # Preflight: reject tables with Unmapped status
        for tid in tables:
            health = self.mapping_health(tid, required_fields=[f.get("key") for f in (self.get_schema(self.get_table(tid).get("schemaId") or "") or {}).get("fields", [])]) if self.get_table(tid) else "Unmapped"
            if health == "Unmapped":
                raise ValueError("NO_MAPPED_COLUMNS")
        job = {
            "id": payload.get("id") or f"job_{int(time.time()*1000)}",
            "name": name,
            "type": jtype,
            "tables": tables,
            "columns": payload.get("columns") or "all",
            "intervalMs": payload.get("intervalMs") or 1000,
            "enabled": bool(payload.get("enabled", False)),
            "status": payload.get("status") or "stopped",
            "batching": payload.get("batching") or {},
            "cpuBudget": payload.get("cpuBudget") or "balanced",
            "metrics": payload.get("metrics") or {},
            "triggers": payload.get("triggers") or [],
        }
        with self._mtx:
            self._jobs.append(job)
            # Persist to App Local DB
            appdb.upsert_job(job)
        return job

    def set_job_status(self, job_id: str, status: str) -> Optional[Dict[str, Any]]:
        with self._mtx:
            for j in self._jobs:
                if j.get("id") == job_id:
                    j["status"] = status
                    try:
                        appdb.update_job_status(job_id, status)
                    except Exception:
                        pass
                    return j
        return None

    def delete_job(self, job_id: str) -> bool:
        """Remove job from memory and App Local DB. Returns True if deleted."""
        with self._mtx:
            before = len(self._jobs)
            self._jobs = [j for j in self._jobs if j.get("id") != job_id]
        try:
            ok = appdb.delete_job(job_id)
        except Exception:
            ok = False
        # ok indicates DB removal; still consider memory removal for response truthiness
        return ok or (len(self._jobs) < before)

    # -------------- DB Targets --------------
    def add_db_target(self, payload: Dict[str, Any]) -> Dict[str, Any]:
        provider = (payload.get("provider") or "").strip() or "sqlite"
        conn = (payload.get("conn") or "").strip() or ":memory:"
        tid = payload.get("id") or f"db_{int(time.time()*1000)}"
        item = {"id": tid, "provider": provider, "conn": conn, "status": payload.get("status") or "untested", "lastMsg": payload.get("lastMsg")}
        with self._mtx:
            # Deduplicate by provider+conn
            for existing in self._db_targets.values():
                if (existing.get("provider") or "").lower() == provider.lower() and str(existing.get("conn") or "").lower() == conn.lower():
                    if payload.get("status"):
                        existing["status"] = payload.get("status")
                    if payload.get("lastMsg") is not None:
                        existing["lastMsg"] = payload.get("lastMsg")
                    appdb.save_target(existing)
                    return existing
            self._db_targets[tid] = item
            appdb.save_target(item)
        return item

    def get_db_target(self, tid: str) -> Optional[Dict[str, Any]]:
        with self._mtx:
            return self._db_targets.get(tid)

    def set_default_db_target(self, tid: str) -> None:
        with self._mtx:
            self._default_db_target_id = tid
            appdb.set_default_target(tid)

    def get_default_db_target(self) -> Optional[str]:
        with self._mtx:
            return self._default_db_target_id

    # -------------- Device Tables --------------
    def add_tables_bulk(self, parent_schema_id: str, names: List[str], db_target_id: Optional[str]) -> List[Dict[str, Any]]:
        now = int(time.time() * 1000)
        out: List[Dict[str, Any]] = []
        with self._mtx:
            for n in names:
                tbl = {
                    "id": f"tbl_{now}_{len(self._tables)+1}",
                    "name": n,
                    "schemaId": parent_schema_id,
                    "dbTargetId": db_target_id,
                    "status": "not_migrated",
                    "lastMigratedAt": None,
                    "mappingHealth": None,
                    "deviceId": None,
                }
                self._tables.append(tbl)
                out.append(tbl)
            appdb.add_tables_bulk(out)
        return out

    def list_tables(self, *, parent_schema_id: Optional[str] = None, db_target_id: Optional[str] = None, status: Optional[str] = None, name_like: Optional[str] = None) -> List[Dict[str, Any]]:
        with self._mtx:
            items = list(self._tables)
        if parent_schema_id:
            items = [t for t in items if t.get("schemaId") == parent_schema_id]
        if db_target_id:
            items = [t for t in items if (t.get("dbTargetId") or self._default_db_target_id) == db_target_id]
        if status:
            items = [t for t in items if t.get("status") == status]
        if name_like:
            s = name_like.lower()
            items = [t for t in items if s in (t.get("name","" ).lower())]
        return items

    def get_table(self, table_id: str) -> Optional[Dict[str, Any]]:
        with self._mtx:
            return next((t for t in self._tables if t.get("id") == table_id), None)

    def set_table_status(self, table_id: str, status: str, *, migrated_at_iso: Optional[str] = None) -> Optional[Dict[str, Any]]:
        with self._mtx:
            for t in self._tables:
                if t.get("id") == table_id:
                    t["status"] = status
                    if migrated_at_iso is not None:
                        t["lastMigratedAt"] = migrated_at_iso
                    appdb.set_table_status(table_id, status, migrated_at_iso)
                    return t
        return None

    def delete_table(self, table_id: str) -> bool:
        with self._mtx:
            before = len(self._tables)
            self._tables = [t for t in self._tables if t.get("id") != table_id]
        appdb.delete_table(table_id)
        return len(self._tables) < before

    # -------------- Mappings --------------
    def get_mapping(self, table_id: str) -> Dict[str, Any]:
        with self._mtx:
            cur = self._mappings.get(table_id) or {}
            device_id = cur.get("deviceId")
            # Fallback: if in-memory mapping lacks binding, use table's persisted deviceId
            if not device_id:
                t = self.get_table(table_id)
                if t and t.get("deviceId"):
                    device_id = t.get("deviceId")
                    # Note: don't mutate rows here; just present the binding for callers
                    try:
                        # Helpful for diagnostics, but keep it quiet by default
                        self._log.debug(f"mapping.get: using table fallback deviceId for {table_id}: {device_id}")
                    except Exception:
                        pass
            return {
                "deviceId": device_id,
                "rows": dict((cur.get("rows") or {})),
            }

    def upsert_mapping(self, table_id: str, *, device_id: Optional[str] = None, rows_patch: Optional[Dict[str, Dict[str, Any]]] = None) -> Dict[str, Any]:
        with self._mtx:
            cur = self._mappings.get(table_id) or {"deviceId": None, "rows": {}}
            if device_id is not None:
                cur["deviceId"] = device_id
            if rows_patch:
                cur_rows = cur.get("rows") or {}
                for k, v in rows_patch.items():
                    cur_rows[k] = {**(cur_rows.get(k) or {}), **v}
                cur["rows"] = cur_rows
            self._mappings[table_id] = cur
            # Persist device binding in App Local DB for restart
            appdb.set_table_device_binding(table_id, cur.get("deviceId"))
            # Update health snapshot in App Local DB
            health = self.mapping_health(table_id, required_fields=list((rows_patch or {}).keys()))
            appdb.update_mapping_health(table_id, health)
            # Keep table cache in sync for fallback reads
            try:
                for t in self._tables:
                    if t.get("id") == table_id:
                        t["deviceId"] = cur.get("deviceId")
                        break
            except Exception:
                pass
            try:
                self._log.info(f"mapping.upsert: table={table_id} deviceId={cur.get('deviceId')} rows={len((rows_patch or {}))}")
            except Exception:
                pass
            return {"deviceId": cur.get("deviceId"), "rows": dict(cur.get("rows") or {})}

    def replace_mapping(self, table_id: str, mapping: Dict[str, Any]) -> Dict[str, Any]:
        with self._mtx:
            device_id = mapping.get("deviceId")
            rows = mapping.get("rows") or {}
            self._mappings[table_id] = {"deviceId": device_id, "rows": rows}
            appdb.set_table_device_binding(table_id, device_id)
            health = self.mapping_health(table_id, required_fields=list(rows.keys()))
            appdb.update_mapping_health(table_id, health)
            # Keep table cache in sync for fallback reads
            try:
                for t in self._tables:
                    if t.get("id") == table_id:
                        t["deviceId"] = device_id
                        break
            except Exception:
                pass
            try:
                self._log.info(f"mapping.replace: table={table_id} deviceId={device_id} rows={len(rows)}")
            except Exception:
                pass
            return self.get_mapping(table_id)

    def mapping_health(self, table_id: str, *, required_fields: List[str]) -> str:
        m = self.get_mapping(table_id)
        rows = m.get("rows") or {}
        if not rows:
            return "Unmapped"
        # If no schema is defined (no required fields), treat any mapping as Mapped
        if not required_fields:
            return "Mapped"
        ok = 0
        for f in required_fields:
            r = rows.get(f) or {}
            p = (r.get("protocol") or "").lower()
            if p == "opcua":
                if r.get("address") or r.get("nodeId"):
                    ok += 1
            elif p == "modbus":
                if r.get("address") and r.get("dataType"):
                    ok += 1
            else:
                # unknown protocol, do not count
                pass
        if ok == 0:
            return "Unmapped"
        if ok == len(required_fields):
            return "Mapped"
        return "Partially Mapped"

    def delete_mapping_row(self, table_id: str, field_key: str) -> Dict[str, Any]:
        with self._mtx:
            cur = self._mappings.get(table_id) or {"deviceId": None, "rows": {}}
            rows = cur.get("rows") or {}
            if field_key in rows:
                rows.pop(field_key, None)
            cur["rows"] = rows
            self._mappings[table_id] = cur
            return self.get_mapping(table_id)

    def set_table_device_binding(self, table_id: str, device_id: Optional[str]) -> None:
        """Set device binding for a table in both memory and App DB.
        Keeps _tables and _mappings consistent.
        """
        with self._mtx:
            # Update table cache
            try:
                for t in self._tables:
                    if t.get("id") == table_id:
                        t["deviceId"] = device_id
                        break
            except Exception:
                pass
            # Update mapping cache
            try:
                cur = self._mappings.get(table_id) or {"deviceId": None, "rows": {}}
                cur["deviceId"] = device_id
                self._mappings[table_id] = cur
            except Exception:
                pass
        try:
            appdb.set_table_device_binding(table_id, device_id)
            self._log.info(f"table.bind: table={table_id} deviceId={device_id}")
        except Exception:
            pass

    def copy_mapping(self, src_table_id: str, dst_table_id: str) -> Dict[str, Any]:
        with self._mtx:
            src = self._mappings.get(src_table_id) or {"deviceId": None, "rows": {}}
            # Do not copy device binding by default; copy only rows
            dst = self._mappings.get(dst_table_id) or {"deviceId": None, "rows": {}}
            dst_rows = dict(src.get("rows") or {})
            dst["rows"] = dst_rows
            self._mappings[dst_table_id] = dst
            return self.get_mapping(dst_table_id)

    # -------------- Devices --------------
    def add_device(self, payload: Dict[str, Any]) -> Dict[str, Any]:
        name = (payload.get("name") or "").strip() or f"Device-{int(time.time()*1000)}"
        protocol = (payload.get("protocol") or "").strip() or "modbus"
        # params may include secrets like password; store but redact on read
        params = payload.get("params") or {}
        dev_id = payload.get("id") or f"dev_{int(time.time()*1000)}"
        auto_reconnect = bool(payload.get("autoReconnect", True))
        item = {
            "id": dev_id,
            "name": name,
            "protocol": protocol,
            "status": "disconnected",
            "latencyMs": None,
            "lastError": None,
            "params": params,
            "autoReconnect": auto_reconnect,
        }
        with self._mtx:
            # Prevent duplicate by name (case-insensitive)
            for d in self._devices.values():
                if (d.get("name") or "").lower() == name.lower():
                    return self._redact_device(d) or d
            self._devices[dev_id] = item
            appdb.upsert_device(item)
        return self.get_device(dev_id) or item

    def list_devices(self) -> List[Dict[str, Any]]:
        with self._mtx:
            return [self._redact_device(d) for d in self._devices.values()]

    def get_device(self, dev_id: str) -> Optional[Dict[str, Any]]:
        with self._mtx:
            dev = self._devices.get(dev_id)
            return self._redact_device(dev) if dev else None

    def delete_device(self, dev_id: str) -> bool:
        with self._mtx:
            ok = self._devices.pop(dev_id, None) is not None
        if ok:
            appdb.delete_device(dev_id)
        return ok

    def update_device_metadata(self, dev_id: str, patch: Dict[str, Any]) -> Optional[Dict[str, Any]]:
        with self._mtx:
            dev = self._devices.get(dev_id)
            if not dev:
                return None
            for k in ("name",):
                if k in patch:
                    dev[k] = patch[k]
            if "autoReconnect" in patch:
                dev["autoReconnect"] = bool(patch.get("autoReconnect"))
        appdb.update_device_metadata(dev_id, name=patch.get("name"), auto_reconnect=patch.get("autoReconnect"))
        return self._redact_device(self._devices.get(dev_id))

    def set_device_status(self, dev_id: str, *, status: str, latency_ms: Optional[int] = None, last_error: Optional[str] = None) -> Optional[Dict[str, Any]]:
        with self._mtx:
            dev = self._devices.get(dev_id)
            if not dev:
                return None
            dev["status"] = status
            dev["latencyMs"] = latency_ms
            dev["lastError"] = last_error
        appdb.update_device_status(dev_id, status=status, latency_ms=latency_ms, last_error=last_error)
        return self._redact_device(self._devices.get(dev_id))

    def _redact_device(self, dev: Optional[Dict[str, Any]]) -> Optional[Dict[str, Any]]:
        if not dev:
            return None
        params = dict(dev.get("params") or {})
        if "pass" in params:
            params["pass"] = "***"
        if "password" in params:
            params["password"] = "***"
        d = dict(dev)
        d["params"] = params
        return d

    # -------------- Gateways --------------
    def list_gateways(self) -> List[Dict[str, Any]]:
        with self._mtx:
            return list(self._gateways)

    def add_gateway(self, payload: Dict[str, Any]) -> Dict[str, Any]:
        name = (payload.get("name") or "").strip()
        host = (payload.get("host") or "").strip()
        adapter_id = payload.get("adapterId")
        nic_hint = payload.get("nic_hint") or adapter_id
        ports = payload.get("ports") or []
        protocol_hint = payload.get("protocol_hint")
        tags = payload.get("tags") or []
        if not name or not host:
            raise ValueError("NAME_AND_HOST_REQUIRED")
        # basic validation of ports
        try:
            ports = sorted({int(p) for p in ports if int(p) > 0 and int(p) <= 65535})
        except Exception:
            raise ValueError("INVALID_PORTS")
        with self._mtx:
            for g in self._gateways:
                if (g.get("name") or "").lower() == name.lower() or (g.get("host") or "").lower() == host.lower():
                    return g
            gid = payload.get("id") or f"gw_{int(time.time()*1000)}"
            gw = {
                "id": gid,
                "name": name,
                "host": host,
                "adapterId": adapter_id,
                "nic_hint": nic_hint,
                "ports": list(ports),
                "protocol_hint": protocol_hint,
                "tags": list(tags),
                "status": "unknown",
                "last_ping": None,
                "last_tcp": None,
            }
            self._gateways.append(gw)
            appdb.upsert_gateway(gw)
            return gw

    def update_gateway(self, gid: str, patch: Dict[str, Any]) -> Optional[Dict[str, Any]]:
        with self._mtx:
            gw = next((g for g in self._gateways if g.get("id") == gid), None)
            if not gw:
                return None
            # Apply allowed fields
            for k in ("name", "host", "nic_hint", "adapterId", "protocol_hint"):
                if k in patch:
                    gw[k] = patch[k]
            if "ports" in patch and isinstance(patch.get("ports"), list):
                try:
                    ports = sorted({int(p) for p in patch.get("ports") if int(p) > 0 and int(p) <= 65535})
                except Exception:
                    raise ValueError("INVALID_PORTS")
                gw["ports"] = list(ports)
            if "tags" in patch and isinstance(patch.get("tags"), list):
                gw["tags"] = list(patch.get("tags") or [])
        # Persist
        saved = appdb.update_gateway(gid, patch)
        # Sync from DB canonical copy if available
        if saved is not None:
            with self._mtx:
                for i, g in enumerate(self._gateways):
                    if g.get("id") == gid:
                        # maintain adapterId for UI compatibility
                        self._gateways[i] = {
                            **g,
                            **saved,
                            "adapterId": saved.get("adapter_id") or g.get("adapterId"),
                        }
                        break
        return self.get_gateway(gid)

    def get_gateway(self, gid: str) -> Optional[Dict[str, Any]]:
        with self._mtx:
            return next((g for g in self._gateways if g.get("id") == gid), None)

    def delete_gateway(self, gid: str) -> bool:
        with self._mtx:
            # Block deletion if referenced by any saved device (Option A)
            for d in self._devices.values():
                params = d.get("params") or {}
                if params.get("gatewayId") == gid:
                    return False
            before = len(self._gateways)
            self._gateways = [g for g in self._gateways if g.get("id") != gid]
        appdb.delete_gateway(gid)
        return len(self._gateways) < before

    def set_gateway_health(self, gid: str, *, last_ping: Optional[Dict[str, Any]] = None, last_tcp: Optional[List[Dict[str, Any]]] = None) -> Optional[Dict[str, Any]]:
        # Determine status
        status: Optional[str] = None
        if last_ping is not None or last_tcp is not None:
            ok_ping = bool((last_ping or {}).get("ok")) if isinstance(last_ping, dict) else None
            any_open = False
            if isinstance(last_tcp, list):
                any_open = any(bool(r.get("status") == "open" or r.get("open")) for r in last_tcp if isinstance(r, dict))
            if ok_ping or any_open:
                status = "reachable"
                if (ok_ping is False) and any_open:
                    status = "limited"
            else:
                status = "unreachable"
        saved = appdb.set_gateway_health(gid, status=status, last_ping=last_ping, last_tcp=last_tcp)
        if not saved:
            return None
        with self._mtx:
            for i, g in enumerate(self._gateways):
                if g.get("id") == gid:
                    # Merge minimal updates
                    self._gateways[i] = {
                        **g,
                        "status": saved.get("status") or status or g.get("status") or "unknown",
                        "last_ping": saved.get("last_ping") if saved.get("last_ping") is not None else last_ping,
                        "last_tcp": saved.get("last_tcp") if saved.get("last_tcp") is not None else last_tcp,
                    }
                    return self._gateways[i]
        return None

    # -------------- Init/load --------------
    def load_from_app_db(self) -> None:
        with self._mtx:
            appdb.init()
            # Schemas
            self._schemas = appdb.load_schemas()
            # Targets + default
            tgs, default_id = appdb.load_targets()
            self._db_targets = {t["id"]: t for t in tgs}
            self._default_db_target_id = default_id
            # Device tables
            raw = appdb.load_device_tables()
            self._tables = [
                {
                    "id": r["id"],
                    "name": r["name"],
                    "schemaId": r["schema_id"],
                    "dbTargetId": r["db_target_id"],
                    "status": r["status"],
                    "lastMigratedAt": r["last_migrated_at"],
                    "mappingHealth": r.get("mapping_health"),
                    "deviceId": r.get("device_id"),
                }
                for r in raw
            ]
            # Provide mapping fallbacks on startup for any tables with a saved deviceId
            try:
                bound = 0
                for t in self._tables:
                    did = t.get("deviceId")
                    if did:
                        self._mappings.setdefault(t.get("id"), {"deviceId": did, "rows": {}})
                        bound += 1
                # Best-effort: hydrate mapping rows from User DB so mapping status is correct immediately
                hydrated = 0
                try:
                    # Local import to avoid hard dependency if FastAPI deps are missing while scripting
                    from .routers import mappings as _mp  # type: ignore
                    for t in self._tables:
                        try:
                            loaded = _mp._load_mapping_from_user_db({
                                "id": t.get("id"),
                                "name": t.get("name"),
                                "dbTargetId": t.get("dbTargetId"),
                            })
                        except Exception:
                            loaded = None
                        if loaded and (loaded.get("rows") or {}):
                            self._mappings[t.get("id")] = {
                                "deviceId": loaded.get("deviceId") or self._mappings.get(t.get("id"),{}).get("deviceId"),
                                "rows": loaded.get("rows") or {},
                            }
                            hydrated += 1
                except Exception:
                    pass
                self._log.info(f"store.load: tables={len(self._tables)} device_bound={bound} mappings_hydrated={hydrated}")
            except Exception:
                pass
            # Gateways
            self._gateways = []
            for g in appdb.load_gateways():
                self._gateways.append(
                    {
                        "id": g.get("id"),
                        "name": g.get("name"),
                        "host": g.get("host"),
                        "adapterId": g.get("adapter_id"),
                        "nic_hint": g.get("nic_hint"),
                        "ports": g.get("ports") or [],
                        "protocol_hint": g.get("protocol_hint"),
                        "tags": g.get("tags") or [],
                        "status": g.get("status") or "unknown",
                        "last_ping": g.get("last_ping"),
                        "last_tcp": g.get("last_tcp"),
                    }
                )
            # Devices
            devs = appdb.load_devices()
            self._devices = {d["id"]: d for d in devs}
            # Jobs
            try:
                self._jobs = appdb.load_jobs()
            except Exception:
                self._jobs = []

    # -------------- Device reconnect loop --------------
    def start_device_reconnector(self) -> None:
        with self._mtx:
            if self._dev_thread_started:
                return
            self._dev_thread_started = True
        th = threading.Thread(target=self._reconnect_loop, name="dev-reconnect", daemon=True)
        self._dev_thread = th
        try:
            th.start()
        except Exception:
            pass

    def _reconnect_loop(self) -> None:
        import random
        while True:
            # Snapshot to avoid holding lock too long
            with self._mtx:
                devices = list(self._devices.values())
            now = time.perf_counter()
            for d in devices:
                try:
                    if not d.get("autoReconnect", True):
                        continue
                    status = d.get("status") or "disconnected"
                    if status == "connected":
                        # Optionally, could verify health here
                        continue
                    bid = self._dev_backoff.get(d["id"]) or {"delay": 1.0, "next": 0.0}
                    if now < bid.get("next", 0.0):
                        continue
                    # Mark reconnecting
                    self.set_device_status(d["id"], status="reconnecting", latency_ms=None)
                    ok, lat, err = self._attempt_connect(d)
                    if ok:
                        # Connected; reset backoff
                        self._dev_backoff[d["id"]] = {"delay": 1.0, "next": now + 5.0}
                        self.set_device_status(d["id"], status="connected", latency_ms=lat, last_error=None)
                    else:
                        # Failure; increase backoff
                        delay = max(1.0, min(30.0, (bid.get("delay", 1.0) * 1.7)))
                        jitter = random.uniform(0.0, 0.3 * delay)
                        nxt = now + delay + jitter
                        self._dev_backoff[d["id"]] = {"delay": delay, "next": nxt}
                        self.set_device_status(d["id"], status="reconnecting", latency_ms=None, last_error=err or "CONNECT_FAILED")
                except Exception:
                    pass
            time.sleep(1.0)

    def _attempt_connect(self, dev: Dict[str, Any]) -> (bool, int, Optional[str]):
        proto = (dev.get("protocol") or "").lower()
        params = dev.get("params") or {}
        t0 = time.perf_counter()
        try:
            if proto == "modbus":
                host = (params.get("host") or params.get("ip") or "").strip()
                port = int(params.get("port", 502))
                if not host:
                    return False, 0, "HOST_REQUIRED"
                try:
                    from pymodbus.client import ModbusTcpClient  # type: ignore
                except Exception:
                    return False, 0, "PYMODBUS_MISSING"
                client = ModbusTcpClient(host=host, port=port)
                ok = False
                try:
                    ok = client.connect()
                finally:
                    try:
                        client.close()
                    except Exception:
                        pass
                dt = int((time.perf_counter() - t0) * 1000)
                return (True, dt, None) if ok else (False, dt, "TCP_CONNECT_FAILED")
            elif proto == "opcua":
                ep = (params.get("endpoint") or "").strip()
                if "0.0.0.0" in ep:
                    ep = ep.replace("0.0.0.0", "127.0.0.1")
                if not ep:
                    return False, 0, "ENDPOINT_REQUIRED"
                try:
                    from opcua import Client  # type: ignore
                except Exception:
                    return False, 0, "OPCUA_PKG_MISSING"
                client = Client(ep)
                try:
                    client.connect(); client.disconnect()
                except Exception as e:
                    dt = int((time.perf_counter() - t0) * 1000)
                    return False, dt, str(e)
                dt = int((time.perf_counter() - t0) * 1000)
                return True, dt, None
            else:
                dt = int((time.perf_counter() - t0) * 1000)
                return False, dt, "PROTOCOL_UNSUPPORTED"
        except Exception as e:
            dt = int((time.perf_counter() - t0) * 1000)
            return False, dt, str(e)
