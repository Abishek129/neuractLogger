from typing import Dict, Any, List

import socket
import time
import logging

from fastapi import APIRouter, HTTPException


router = APIRouter(prefix="/networking")
logger = logging.getLogger(__name__)


@router.get("/nics")
def list_nics() -> Dict[str, Any]:
    adapters: List[Dict[str, Any]] = []
    try:
        import psutil  # type: ignore

        addrs = psutil.net_if_addrs()
        stats = psutil.net_if_stats()
        for name, recs in addrs.items():
            if not stats.get(name) or not stats[name].isup:
                continue
            ipv4 = next((r for r in recs if getattr(r, 'family', None) == socket.AF_INET), None)
            if not ipv4:
                continue
            adapters.append({
                "id": name,
                "label": name,
                "ip": ipv4.address,
                "cidr": 24,  # psutil doesn't directly give cidr; keep simple
                "gateway": None,
            })
    except Exception:
        # Fallback: loopback only
        adapters.append({"id": "lo", "label": "Loopback", "ip": "127.0.0.1", "cidr": 8, "gateway": None})
    return {"items": adapters}


@router.post("/ping")
def ping_target(params: Dict[str, Any]) -> Dict[str, Any]:
    target = params.get("target") or params.get("host")
    count = int(params.get("count", 4))
    timeout = float(params.get("timeoutMs", 800)) / 1000.0
    if not target:
        raise HTTPException(status_code=400, detail="TARGET_REQUIRED")
    try:
        from icmplib import ping  # type: ignore

        h = ping(target, count=count, interval=0.2, timeout=timeout, privileged=False)
        samples = []
        # icmplib doesn't expose per-packet by default in simple mode; synthesize from stats
        if h.packets_sent:
            samples = [int(h.min_rtt or 0), int(h.avg_rtt or 0), int(h.max_rtt or 0)]
        return {
            "ok": h.is_alive,
            "lossPct": int((1 - (h.packets_received / max(1, h.packets_sent))) * 100),
            "min": int(h.min_rtt or 0),
            "avg": int(h.avg_rtt or 0),
            "max": int(h.max_rtt or 0),
            "samples": samples,
        }
    except Exception as e:
        logger.exception("Ping failed target=%s count=%s timeout=%.3fs", target, count, timeout)
        return {"ok": False, "code": "PING_ICMP_BLOCKED", "message": str(e)}


@router.post("/tcp_test")
def tcp_test(params: Dict[str, Any]) -> Dict[str, Any]:
    host = params.get("host") or params.get("target") or "127.0.0.1"
    port = int(params.get("port", 502))
    timeout = float(params.get("timeoutMs", 1000)) / 1000.0
    t0 = time.perf_counter()
    try:
        with socket.create_connection((host, port), timeout=timeout):
            dt = int((time.perf_counter() - t0) * 1000)
            return {"ok": True, "status": "open", "timeMs": dt}
    except TimeoutError:
        dt = int((time.perf_counter() - t0) * 1000)
        logger.warning("TCP timeout host=%s port=%s timeMs=%s", host, port, dt)
        return {"ok": False, "status": "timeout", "timeMs": dt}
    except OSError as e:
        dt = int((time.perf_counter() - t0) * 1000)
        logger.info("TCP closed host=%s port=%s timeMs=%s err=%s", host, port, dt, e)
        return {"ok": False, "status": "closed", "message": str(e), "timeMs": dt}


@router.post("/modbus/test")
def test_modbus(params: Dict[str, Any]) -> Dict[str, Any]:
    host = params.get("host") or params.get("ip") or "127.0.0.1"
    port = int(params.get("port", 502))
    unit = int(params.get("unitId", 1))
    address = int(params.get("address", 1))
    count = int(params.get("count", 1))
    try:
        from pymodbus.client import ModbusTcpClient  # type: ignore

        t0 = time.perf_counter()
        client = ModbusTcpClient(host=host, port=port)
        ok = client.connect()
        if not ok:
            return {"ok": False, "protocol": "modbus", "message": "TCP_CONNECT_FAILED"}
        rr = client.read_holding_registers(address=address, count=count, unit=unit)
        client.close()
        dt = int((time.perf_counter() - t0) * 1000)
        if hasattr(rr, 'isError') and rr.isError():
            return {"ok": False, "protocol": "modbus", "message": str(rr), "latencyMs": dt}
        vals = getattr(rr, 'registers', None)
        return {"ok": True, "protocol": "modbus", "values": vals, "latencyMs": dt}
    except ImportError:
        logger.warning("Modbus test: pymodbus missing")
        return {"ok": False, "protocol": "modbus", "message": "PYMODBUS_MISSING"}
    except Exception as e:
        logger.exception("Modbus test failed host=%s port=%s unit=%s address=%s count=%s", host, port, unit, address, count)
        return {"ok": False, "protocol": "modbus", "message": str(e)}


@router.post("/opcua/test")
def test_opcua(params: Dict[str, Any]) -> Dict[str, Any]:
    endpoint = params.get("endpoint", "opc.tcp://127.0.0.1:4840")
    if isinstance(endpoint, str) and "0.0.0.0" in endpoint:
        endpoint = endpoint.replace("0.0.0.0", "127.0.0.1")
    nodeid = params.get("nodeId")
    try:
        from opcua import Client  # type: ignore

        t0 = time.perf_counter()
        client = Client(endpoint)
        try:
            client.connect()
        except Exception as e:
            return {"ok": False, "protocol": "opcua", "endpoint": endpoint, "message": str(e)}
        val = None
        if nodeid:
            try:
                node = client.get_node(nodeid)
                val = node.get_value()
            except Exception as e:
                client.disconnect()
                return {"ok": False, "protocol": "opcua", "endpoint": endpoint, "message": f"NODE_READ_FAILED: {e}"}
        client.disconnect()
        dt = int((time.perf_counter() - t0) * 1000)
        return {"ok": True, "protocol": "opcua", "endpoint": endpoint, "value": val, "latencyMs": dt}
    except ImportError:
        logger.warning("OPC UA test: opcua package missing")
        return {"ok": False, "protocol": "opcua", "endpoint": endpoint, "message": "OPCUA_PKG_MISSING"}
    except Exception as e:
        logger.exception("OPC UA test failed endpoint=%s", endpoint)
        return {"ok": False, "protocol": "opcua", "endpoint": endpoint, "message": str(e)}


@router.post("/opcua/browse")
def opcua_browse(params: Dict[str, Any]) -> Dict[str, Any]:
    endpoint = params.get("endpoint", "opc.tcp://127.0.0.1:4840/freeopcua/server/")
    if isinstance(endpoint, str) and "0.0.0.0" in endpoint:
        endpoint = endpoint.replace("0.0.0.0", "127.0.0.1")
    nodeid = params.get("nodeId") or "i=85"  # RootFolder
    try:
        from opcua import Client, ua  # type: ignore
        client = Client(endpoint)
        client.connect()
        try:
            node = client.get_node(nodeid)
            children = node.get_children()
            items = []
            for ch in children:
                try:
                    bn = ch.get_browse_name()
                    nid = ch.nodeid.to_string()
                    items.append({
                        "nodeId": nid,
                        "browseName": f"{bn.NamespaceIndex}:{bn.Name}",
                    })
                except Exception:
                    pass
        finally:
            client.disconnect()
        return {"ok": True, "items": items}
    except ImportError:
        return {"ok": False, "message": "OPCUA_PKG_MISSING"}
    except Exception as e:
        logger.exception("OPC UA browse failed endpoint=%s node=%s", endpoint, nodeid)
        return {"ok": False, "message": str(e)}


@router.get("/gateways")
def list_gateways() -> Dict[str, Any]:
    from ..store import Store
    return {"items": Store.instance().list_gateways()}


@router.post("/gateways")
def add_gateway(payload: Dict[str, Any]) -> Dict[str, Any]:
    from ..store import Store
    try:
        gw = Store.instance().add_gateway(payload)
        return {"success": True, "item": gw}
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))


@router.put("/gateways/{gid}")
def update_gateway(gid: str, payload: Dict[str, Any]) -> Dict[str, Any]:
    from ..store import Store
    updated = Store.instance().update_gateway(gid, payload)
    if not updated:
        raise HTTPException(status_code=404, detail="GATEWAY_NOT_FOUND")
    return {"success": True, "item": updated}


@router.delete("/gateways/{gid}")
def delete_gateway(gid: str) -> Dict[str, Any]:
    from ..store import Store
    st = Store.instance()
    existed = st.get_gateway(gid) is not None
    ok = st.delete_gateway(gid)
    if not ok:
        if existed:
            raise HTTPException(status_code=400, detail="GATEWAY_IN_USE")
        raise HTTPException(status_code=404, detail="GATEWAY_NOT_FOUND")
    return {"success": True}


def _gw_rate_limited(gid: str, min_interval: float = 3.0) -> bool:
    from ..store import Store
    st = Store.instance()
    now = time.perf_counter()
    last = st._gw_rate.get(gid) if hasattr(st, "_gw_rate") else None  # type: ignore[attr-defined]
    if last is not None and (now - last) < min_interval:
        return True
    # record
    try:
        st._gw_rate[gid] = now  # type: ignore[attr-defined]
    except Exception:
        pass
    return False


@router.post("/gateways/{gid}/ping")
def ping_gateway(gid: str, params: Dict[str, Any]) -> Dict[str, Any]:
    from ..store import Store
    if _gw_rate_limited(gid):
        raise HTTPException(status_code=429, detail="RATE_LIMITED")
    gw = Store.instance().get_gateway(gid)
    if not gw:
        raise HTTPException(status_code=404, detail="GATEWAY_NOT_FOUND")
    target = gw.get("host")
    count = int(params.get("count", 4))
    timeout_ms = int(params.get("timeoutMs", 800))
    res = ping_target({"target": target, "count": count, "timeoutMs": timeout_ms})
    # Update health cache
    Store.instance().set_gateway_health(gid, last_ping=res)
    return {"ok": res.get("ok"), **res}


@router.post("/gateways/{gid}/tcp")
def tcp_gateway(gid: str, params: Dict[str, Any]) -> Dict[str, Any]:
    from ..store import Store
    if _gw_rate_limited(gid):
        raise HTTPException(status_code=429, detail="RATE_LIMITED")
    gw = Store.instance().get_gateway(gid)
    if not gw:
        raise HTTPException(status_code=404, detail="GATEWAY_NOT_FOUND")
    host = gw.get("host")
    ports = params.get("ports") or gw.get("ports") or []
    results: List[Dict[str, Any]] = []
    for p in ports:
        r = tcp_test({"host": host, "port": p, "timeoutMs": params.get("timeoutMs", 1000)})
        results.append({"port": p, **r})
    Store.instance().set_gateway_health(gid, last_tcp=results)
    return {"ok": True, "results": results}
