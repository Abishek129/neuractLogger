# mypy: ignore-errors
"""
Network scanner — async subnet sweep via ICMP ping + TCP port scan.

Uses icmplib.multiping() for bulk ping (in executor), then
asyncio.open_connection() for parallel port scanning.
"""
from __future__ import annotations

import asyncio
import ipaddress
import logging
import time as _time
from typing import Any

from .types import DiscoveredHost, PortResult

logger = logging.getLogger("loggerfast.ai.discovery.scanner")

# Concurrency limit for port scanning
_PORT_SCAN_SEMAPHORE = 100


async def scan_subnet_impl(
    subnet: str,
    ports: list[int] | None = None,
    timeout_ms: int = 800,
    max_hosts: int = 254,
) -> list[DiscoveredHost]:
    """Ping sweep + port scan a subnet.

    Args:
        subnet: CIDR notation (e.g. '10.10.1.0/24')
        ports: TCP ports to check (default [502, 4840])
        timeout_ms: timeout per host in ms
        max_hosts: cap on number of hosts to scan

    Returns:
        List of DiscoveredHost (all hosts, with alive flag + port results).
    """
    if ports is None:
        ports = [502, 4840]

    # Parse CIDR
    try:
        network = ipaddress.ip_network(subnet, strict=False)
    except ValueError as e:
        logger.warning("invalid_subnet %s: %s", subnet, e)
        return []

    # Enumerate hosts (skip network + broadcast for /24 and larger)
    all_ips = [str(ip) for ip in network.hosts()][:max_hosts]
    if not all_ips:
        # Single host (e.g. /32)
        all_ips = [str(network.network_address)]

    logger.info("scan_start subnet=%s hosts=%d ports=%s", subnet, len(all_ips), ports)

    # Phase 1: Ping sweep
    alive_set = await _ping_sweep(all_ips, timeout_ms)

    # Phase 2: Port scan alive hosts
    alive_ips = [ip for ip in all_ips if ip in alive_set]
    if not alive_ips:
        # No ping responses — try port scan on all hosts (some block ICMP)
        alive_ips = all_ips
        logger.info("no_ping_responses, falling back to full port scan")

    port_results = await _port_scan_parallel(alive_ips, ports, timeout_ms)

    # Build results
    hosts = []
    for ip in all_ips:
        alive = ip in alive_set
        pr = port_results.get(ip, [])
        # If host didn't respond to ping but has open ports, mark as alive
        if not alive and any(p.open for p in pr):
            alive = True
        hosts.append(DiscoveredHost(ip=ip, alive=alive, ports=pr))

    alive_count = sum(1 for h in hosts if h.alive)
    with_ports = sum(1 for h in hosts if any(p.open for p in h.ports))
    logger.info("scan_complete subnet=%s alive=%d with_ports=%d", subnet, alive_count, with_ports)

    return hosts


async def _ping_sweep(ips: list[str], timeout_ms: int) -> set[str]:
    """Bulk ICMP ping using icmplib.multiping(). Returns set of alive IPs."""
    loop = asyncio.get_running_loop()

    def _do_multiping():
        try:
            from icmplib import multiping
            timeout_s = max(timeout_ms / 1000.0, 0.5)
            results = multiping(ips, count=1, timeout=timeout_s, privileged=False)
            return {r.address for r in results if r.is_alive}
        except ImportError:
            logger.warning("icmplib not available, skipping ping sweep")
            return set()
        except Exception as e:
            logger.warning("multiping failed: %s", e)
            return set()

    return await loop.run_in_executor(None, _do_multiping)


async def _port_scan_parallel(
    ips: list[str],
    ports: list[int],
    timeout_ms: int,
) -> dict[str, list[PortResult]]:
    """Parallel TCP port scan with concurrency limit."""
    sem = asyncio.Semaphore(_PORT_SCAN_SEMAPHORE)
    results: dict[str, list[PortResult]] = {ip: [] for ip in ips}

    async def _check(ip: str, port: int):
        async with sem:
            t0 = _time.perf_counter()
            try:
                _, writer = await asyncio.wait_for(
                    asyncio.open_connection(ip, port),
                    timeout=timeout_ms / 1000.0,
                )
                latency = int((_time.perf_counter() - t0) * 1000)
                writer.close()
                try:
                    await writer.wait_closed()
                except Exception:
                    pass
                results[ip].append(PortResult(port=port, open=True, latency_ms=latency))
            except (asyncio.TimeoutError, OSError):
                results[ip].append(PortResult(port=port, open=False, latency_ms=0))

    tasks = [_check(ip, port) for ip in ips for port in ports]
    await asyncio.gather(*tasks, return_exceptions=True)

    return results
