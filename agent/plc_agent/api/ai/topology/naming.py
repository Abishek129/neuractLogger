# mypy: ignore-errors
"""Topology-aware device/table name suggestions."""
from __future__ import annotations

from typing import Dict

from .types import DeviceNode, HierarchyLevel, LoadPattern, TopologyGraph


def suggest_names(graph: TopologyGraph) -> Dict[str, str]:
    """Generate topology-aware name suggestions for devices.

    Returns ``{device_id: suggested_name}``.

    Naming rules (from spec):
    - Incomer:    ``incomer_main``  or ``incomer_{idx}``
    - Feeder:     ``feeder_{section}_{idx}``
    - Sub-feeder: ``sub_feeder_{parent}_{idx}``
    - Load:       ``{pattern}_{idx}``  (e.g. ``motor_001``, ``lighting_002``)
    """
    names: Dict[str, str] = {}
    counters: Dict[str, int] = {}

    def _next(prefix: str) -> str:
        counters[prefix] = counters.get(prefix, 0) + 1
        return f"{prefix}_{counters[prefix]:03d}"

    # Sort nodes by power descending for stable naming
    sorted_nodes = sorted(
        graph.nodes.values(),
        key=lambda n: n.active_power,
        reverse=True,
    )

    for node in sorted_nodes:
        if node.level == HierarchyLevel.INCOMER:
            if counters.get("incomer", 0) == 0:
                names[node.device_id] = "incomer_main"
                counters["incomer"] = 1
            else:
                names[node.device_id] = _next("incomer")

        elif node.level == HierarchyLevel.FEEDER:
            parent_name = names.get(node.parent_id, "")
            section = parent_name.replace("incomer_", "") if parent_name else "a"
            names[node.device_id] = _next(f"feeder_{section}")

        elif node.level == HierarchyLevel.SUB_FEEDER:
            parent_name = names.get(node.parent_id, "feeder")
            short = parent_name.split("_")[-1] if parent_name else "x"
            names[node.device_id] = _next(f"sub_feeder_{short}")

        elif node.level == HierarchyLevel.LOAD:
            pattern = _pattern_prefix(node.load_pattern)
            names[node.device_id] = _next(pattern)

        else:
            names[node.device_id] = _next("device")

    return names


def _pattern_prefix(pattern: LoadPattern) -> str:
    return {
        LoadPattern.MOTOR: "motor",
        LoadPattern.LIGHTING: "lighting",
        LoadPattern.UPS: "ups",
        LoadPattern.MIXED: "load",
        LoadPattern.UNKNOWN: "load",
    }.get(pattern, "load")
