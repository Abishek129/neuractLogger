# mypy: ignore-errors
"""
Modbus unit ID enumerator — find which slave IDs respond at a given IP.

Uses a single TCP connection and iterates unit IDs, probing a register
to determine which slaves are present.
"""
from __future__ import annotations

import asyncio
import logging
import time as _time

from .types import RespondingUnit

logger = logging.getLogger("loggerfast.ai.discovery.enumerator")


async def enumerate_unit_ids_impl(
    ip: str,
    port: int = 502,
    start: int = 1,
    end: int = 10,
    probe_address: int = 0,
    probe_count: int = 2,
    timeout_ms: int = 500,
) -> list[RespondingUnit]:
    """Find which Modbus unit IDs respond at an IP.

    Creates a single TCP connection, iterates unit IDs, reads a probe
    register. Returns list of responding units with raw values.

    Args:
        ip: Target IP address
        port: Modbus TCP port (default 502)
        start: First unit ID to probe (1-247)
        end: Last unit ID to probe (1-247)
        probe_address: Register address to read as probe
        probe_count: Number of registers to read (default 2)
        timeout_ms: Per-read timeout in ms

    Returns:
        List of RespondingUnit for unit IDs that returned valid data.
    """
    # Clamp range
    start = max(1, min(start, 247))
    end = max(start, min(end, 247))

    loop = asyncio.get_running_loop()

    def _enumerate():
        try:
            from pymodbus.client import ModbusTcpClient
        except ImportError:
            logger.warning("pymodbus not available")
            return []

        client = ModbusTcpClient(host=ip, port=port, timeout=timeout_ms / 1000.0)
        if not client.connect():
            logger.warning("modbus_connect_failed ip=%s port=%d", ip, port)
            return []

        units = []
        try:
            for uid in range(start, end + 1):
                t0 = _time.perf_counter()
                try:
                    rr = client.read_holding_registers(
                        address=probe_address,
                        count=probe_count,
                        slave=uid,
                    )
                    latency = int((_time.perf_counter() - t0) * 1000)

                    if rr and not rr.isError() and hasattr(rr, "registers"):
                        units.append(RespondingUnit(
                            unit_id=uid,
                            raw_values=list(rr.registers),
                            latency_ms=latency,
                        ))
                        logger.debug("unit_found ip=%s uid=%d regs=%s lat=%dms",
                                     ip, uid, rr.registers, latency)
                except Exception:
                    # Expected — most unit IDs won't respond
                    pass
        finally:
            client.close()

        logger.info("enumerate_complete ip=%s:%d range=%d-%d found=%d",
                     ip, port, start, end, len(units))
        return units

    return await loop.run_in_executor(None, _enumerate)
