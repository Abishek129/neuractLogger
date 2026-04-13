from typing import Dict, Any, Optional, List
from fastapi import APIRouter, HTTPException
from ..store import Store

router = APIRouter(prefix="/bulk_import")


@router.post("/devices")
def bulk_import_devices(payload: Dict[str, Any]) -> Dict[str, Any]:
    """
    Bulk import devices from spreadsheet data.

    For each device row:
    1. Find or create gateway based on IP address and protocol
    2. Create device linked to that gateway
    3. Set protocol-specific fields (unitId for Modbus)

    Returns summary and per-row results.
    """
    devices_data = payload.get("devices") or []
    if not devices_data or not isinstance(devices_data, list):
        raise HTTPException(status_code=400, detail="DEVICES_ARRAY_REQUIRED")

    store = Store.instance()
    results = []
    created_gateways = 0
    created_devices = 0
    skipped = 0
    failed = 0

    for idx, row in enumerate(devices_data):
        try:
            # Extract fields
            name = (row.get("name") or "").strip()
            ip = (row.get("ip") or "").strip()
            port = row.get("port")
            mac = (row.get("mac") or "").strip()
            protocol = (row.get("protocol") or "modbus").strip().lower()
            unit = row.get("unit")
            connections = (row.get("connections") or "").strip()
            mqtt_gateway = (row.get("mqtt_gateway") or "").strip()

            # Validate required fields
            if not name:
                results.append({
                    "row": idx,
                    "status": "failed",
                    "error": "NAME_REQUIRED",
                    "input": row
                })
                failed += 1
                continue

            if not ip:
                results.append({
                    "row": idx,
                    "status": "failed",
                    "error": "IP_REQUIRED",
                    "input": row
                })
                failed += 1
                continue

            # Validate protocol
            if not store.is_valid_protocol(protocol):
                results.append({
                    "row": idx,
                    "status": "failed",
                    "error": f"PROTOCOL_INVALID: '{protocol}'",
                    "input": row
                })
                failed += 1
                continue

            # Check if device already exists
            existing_devices = store.list_devices()
            existing = next((d for d in existing_devices if (d.get("name") or "").lower() == name.lower()), None)
            if existing:
                results.append({
                    "row": idx,
                    "status": "skipped",
                    "device": existing,
                    "message": "Device already exists"
                })
                skipped += 1
                continue

            # Find or create gateway
            # For discovery/lookup, use the same host string we would persist on the gateway.
            # This avoids mismatches (e.g. OPC UA endpoints) and ensures we truly key by host/IP.
            gateway_host = ip
            gateway_ports = [port] if port else []

            # For OPC UA, store uses full endpoint-style host.
            if protocol == "opcua":
                port_num = int(port or 4840)
                gateway_host = f"opc.tcp://{ip}:{port_num}"
                # Keep ports consistent with the endpoint we will advertise.
                gateway_ports = [port_num]

            gateway = store.find_gateway_by_host(gateway_host)
            # Backward-compat: some existing gateways may have been stored as raw IP even for OPC UA.
            if (not gateway) and protocol == "opcua":
                gateway = store.find_gateway_by_host(ip)
            gateway_created = False

            if not gateway:
                # Create gateway
                gateway_name = connections or f"Gateway-{ip}"
                # Avoid Store.add_gateway de-duping by name and returning a gateway with a different host.
                # If the name already exists for another host, suffix with the host to force uniqueness.
                try:
                    existing_by_name = next(
                        (
                            g
                            for g in store.list_gateways()
                            if (g.get("name") or "").strip().lower() == gateway_name.lower()
                        ),
                        None,
                    )
                except Exception:
                    existing_by_name = None
                if existing_by_name and (existing_by_name.get("host") or "").strip().lower() != gateway_host.lower():
                    gateway_name = f"{gateway_name} ({gateway_host})"

                gateway_payload = {
                    "name": gateway_name,
                    "host": gateway_host,
                    "protocol_hint": protocol,
                    "ports": gateway_ports,
                }

                try:
                    gateway = store.add_gateway(gateway_payload)
                    gateway_created = True
                    created_gateways += 1
                except Exception as e:
                    results.append({
                        "row": idx,
                        "status": "failed",
                        "error": f"GATEWAY_CREATE_FAILED: {str(e)}",
                        "input": row
                    })
                    failed += 1
                    continue

            # Build device payload
            device_payload = {
                "name": name,
                "protocol": protocol,
                "gatewayId": gateway.get("id"),
                "params": {}
            }

            # Add port if specified
            if port:
                device_payload["port"] = int(port)

            # Add unitId for Modbus and MQTT (meter id)
            if protocol in ("modbus", "mqtt"):
                device_payload["unitId"] = int(unit) if unit else 1

            # Add MAC address to params if provided
            if mac:
                device_payload["params"]["mac"] = mac

            # Store broker IP in params for job runner host resolution
            device_payload["params"]["host"] = ip
            # Store MQTT logical gateway label (e.g. "GW-01") for filtering MQTT payloads
            if mqtt_gateway:
                device_payload["params"]["mqtt_gateway"] = mqtt_gateway

            # Connection test before creating (mirrors POST /devices)
            extra = {}
            if device_payload.get("gatewayId"):
                extra["gatewayId"] = device_payload["gatewayId"]
            if device_payload.get("port") is not None:
                extra["port"] = device_payload["port"]
            if device_payload.get("unitId") is not None:
                extra["unitId"] = device_payload["unitId"]

            try:
                conn_ok, latency, conn_err = store.test_device_params(
                    protocol, device_payload.get("params") or {}, **extra
                )
            except Exception:
                conn_ok, latency, conn_err = False, None, "CONNECTION_TEST_ERROR"

            # Create device
            try:
                device = store.add_device(device_payload)
                if conn_ok:
                    store.mark_manual_disconnect(device["id"], False)
                    store.set_device_status(
                        device["id"], status="connected",
                        latency_ms=latency, last_error=None,
                    )
                else:
                    store.set_device_status(
                        device["id"], status="degraded",
                        latency_ms=None,
                        last_error=conn_err or "TEST_FAILED",
                    )
                stored = store.get_device(device["id"]) or device
                results.append({
                    "row": idx,
                    "status": "created",
                    "device": stored,
                    "gateway": gateway,
                    "gateway_created": gateway_created,
                    "connected": conn_ok,
                    "latencyMs": latency,
                    "connectionError": conn_err if not conn_ok else None,
                    "message": f"Device created{' with new gateway' if gateway_created else ''}"
                })
                created_devices += 1
            except Exception as e:
                results.append({
                    "row": idx,
                    "status": "failed",
                    "error": f"DEVICE_CREATE_FAILED: {str(e)}",
                    "input": row
                })
                failed += 1

        except Exception as e:
            results.append({
                "row": idx,
                "status": "failed",
                "error": f"UNEXPECTED_ERROR: {str(e)}",
                "input": row
            })
            failed += 1

    return {
        "success": True,
        "summary": {
            "total": len(devices_data),
            "created_gateways": created_gateways,
            "created_devices": created_devices,
            "skipped": skipped,
            "failed": failed
        },
        "results": results
    }
