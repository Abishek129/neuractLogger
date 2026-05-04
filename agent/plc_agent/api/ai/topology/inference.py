# mypy: ignore-errors
"""SLD topology inference engine — infers incomer/feeder/load hierarchy from power flow."""
from __future__ import annotations

import logging
import math
from datetime import datetime, timezone
from itertools import combinations
from typing import Any, Dict, List, Optional

from .types import (
    DeviceNode,
    HierarchyLevel,
    LoadPattern,
    TopologyGraph,
)

logger = logging.getLogger("loggerfast.ai.topology")

# ── Power parameter keys (from validation/params.py canonical names) ──
_POWER_KEYS = {
    "active_power", "active_power_total", "p_total", "active_power_w",
    "total_active_power", "kw_total", "watts_total",
}
_APPARENT_KEYS = {
    "apparent_power", "apparent_power_total", "s_total", "apparent_power_va",
    "total_apparent_power", "kva_total",
}
_PF_KEYS = {
    "power_factor", "power_factor_total", "pf", "pf_total",
    "total_power_factor", "cos_phi",
}


class TopologyInferenceEngine:
    """Infers SLD hierarchy from power flow patterns across devices."""

    POWER_BALANCE_TOLERANCE = 0.15  # 15% parent–children match tolerance
    MIN_POWER_W = 100.0             # ignore devices below 100W
    MAX_CHILDREN_SEARCH = 8         # max subset size for combinatorial search

    def infer(
        self,
        devices_with_readings: List[Dict[str, Any]],
        snapshots: int = 1,
    ) -> TopologyGraph:
        """Main inference entry point.

        Parameters
        ----------
        devices_with_readings
            List of dicts: ``{device_id, device_name, gateway_id, readings: {param: value}}``.
        snapshots
            Number of reading snapshots used (for confidence weighting).

        Returns
        -------
        TopologyGraph with hierarchy assignments.
        """
        if not devices_with_readings:
            return TopologyGraph(gateway_id="", inferred_at=_now())

        gateway_id = devices_with_readings[0].get("gateway_id", "")

        # Step 1: extract power values and build nodes
        nodes: Dict[str, DeviceNode] = {}
        for d in devices_with_readings:
            dev_id = d.get("device_id", "")
            readings = d.get("readings") or {}
            p, s, pf = self._extract_power(readings)
            if p < self.MIN_POWER_W:
                continue  # skip negligible devices
            nodes[dev_id] = DeviceNode(
                device_id=dev_id,
                device_name=d.get("device_name", dev_id),
                gateway_id=d.get("gateway_id", gateway_id),
                active_power=p,
                apparent_power=s,
                power_factor=pf,
            )

        if not nodes:
            return TopologyGraph(gateway_id=gateway_id, inferred_at=_now())

        # Step 2: sort by active power descending
        sorted_ids = sorted(nodes, key=lambda x: nodes[x].active_power, reverse=True)

        # Step 3: greedy parent–child assignment
        assigned: set[str] = set()
        for dev_id in sorted_ids:
            if dev_id in assigned:
                continue
            node = nodes[dev_id]
            # Candidates = unassigned devices with LESS power
            candidates = [
                cid for cid in sorted_ids
                if cid != dev_id and cid not in assigned
                and nodes[cid].active_power < node.active_power
            ]
            children, balance = self._find_children(
                node.active_power, candidates, nodes,
            )
            if children:
                node.children_ids = children
                for cid in children:
                    nodes[cid].parent_id = dev_id
                    assigned.add(cid)
                node.confidence = self._score_confidence(balance, snapshots)

        # Step 4: assign hierarchy levels + detect parallel incomers
        incomer_candidates = []
        for dev_id, node in nodes.items():
            if node.parent_id is None and node.children_ids:
                node.level = HierarchyLevel.INCOMER
                node.confidence = max(node.confidence, 0.7)
                incomer_candidates.append((dev_id, node.avg_power))
            elif node.parent_id is None and not node.children_ids:
                # Standalone — single device or unresolved
                node.level = HierarchyLevel.LOAD
                node.confidence = 0.3
            elif node.children_ids:
                node.level = HierarchyLevel.FEEDER
            else:
                # Leaf
                grandchildren = any(
                    nodes[c].children_ids for c in node.children_ids
                ) if node.children_ids else False
                node.level = HierarchyLevel.LOAD

        # Detect parallel incomers (N+1 redundancy)
        if len(incomer_candidates) >= 2:
            incomer_candidates.sort(key=lambda x: x[1], reverse=True)
            top_power = incomer_candidates[0][1]
            for dev_id, power in incomer_candidates[1:]:
                if top_power > 0 and power / top_power > 0.8:
                    # Parallel incomer detected — flag with reduced confidence
                    nodes[dev_id].confidence = min(nodes[dev_id].confidence, 0.5)
                    logger.warning(
                        "parallel_incomer_detected device=%s power=%.1f "
                        "vs primary=%.1f (ratio=%.0f%%). Requires engineer confirmation.",
                        dev_id, power, top_power, power / top_power * 100,
                    )

        # Step 5: classify load patterns
        for node in nodes.values():
            if node.level in (HierarchyLevel.LOAD, HierarchyLevel.SUB_FEEDER):
                node.load_pattern = self._classify_load_pattern(node)

        # Step 6: compute overall power balance score
        balance_scores = []
        for node in nodes.values():
            if node.children_ids:
                child_sum = sum(nodes[c].active_power for c in node.children_ids)
                if node.active_power > 0:
                    ratio = child_sum / node.active_power
                    balance_scores.append(1.0 - abs(1.0 - ratio))
        overall_balance = (
            sum(balance_scores) / len(balance_scores)
            if balance_scores else 0.0
        )

        return TopologyGraph(
            gateway_id=gateway_id,
            nodes=nodes,
            inferred_at=_now(),
            snapshot_count=snapshots,
            power_balance_score=max(0.0, overall_balance),
        )

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    def _extract_power(
        self, readings: Dict[str, Any],
    ) -> tuple[float, float, float]:
        """Extract (active_power_W, apparent_power_VA, power_factor) from readings."""
        p = self._first_numeric(readings, _POWER_KEYS, 0.0)
        s = self._first_numeric(readings, _APPARENT_KEYS, 0.0)
        pf = self._first_numeric(readings, _PF_KEYS, 0.0)

        # Heuristic: if power values are in kW/kVA (< 1000) scale up
        if 0 < p < 1000 and s == 0:
            p *= 1000  # assume kW
        if 0 < s < 1000 and p > 1000:
            s *= 1000  # assume kVA

        # Derive missing values
        if s == 0 and p > 0 and pf > 0:
            s = p / pf
        if pf == 0 and p > 0 and s > 0:
            pf = min(p / s, 1.0)

        return abs(p), abs(s), min(abs(pf), 1.0)

    @staticmethod
    def _first_numeric(
        readings: Dict[str, Any], keys: set[str], default: float,
    ) -> float:
        """Return the first matching numeric value from readings."""
        lower = {k.lower(): v for k, v in readings.items()}
        for k in keys:
            v = lower.get(k)
            if isinstance(v, (int, float)) and not math.isnan(v):
                return float(v)
        return default

    def _find_children(
        self,
        parent_power: float,
        candidate_ids: List[str],
        nodes: Dict[str, DeviceNode],
    ) -> tuple[list[str], float]:
        """Greedy subset-sum: find candidates whose total ~ parent_power.

        Returns (child_ids, balance_ratio) or ([], 0.0).
        """
        if not candidate_ids or parent_power <= 0:
            return [], 0.0

        # Try subsets from largest down (greedy)
        best_subset: list[str] = []
        best_ratio = 0.0

        # Limit combinatorial explosion
        search = candidate_ids[: self.MAX_CHILDREN_SEARCH]

        for size in range(len(search), 0, -1):
            for combo in combinations(search, size):
                total = sum(nodes[c].active_power for c in combo)
                ratio = total / parent_power
                deviation = abs(1.0 - ratio)
                if deviation <= self.POWER_BALANCE_TOLERANCE:
                    if ratio > best_ratio or not best_subset:
                        best_subset = list(combo)
                        best_ratio = ratio
            if best_subset:
                break  # found at this size, no need for smaller

        # Also try greedy accumulation as fallback
        if not best_subset:
            greedy = []
            running = 0.0
            for cid in candidate_ids:
                cp = nodes[cid].active_power
                if running + cp <= parent_power * (1 + self.POWER_BALANCE_TOLERANCE):
                    greedy.append(cid)
                    running += cp
            ratio = running / parent_power if parent_power > 0 else 0
            if abs(1.0 - ratio) <= self.POWER_BALANCE_TOLERANCE and greedy:
                best_subset = greedy
                best_ratio = ratio

        return best_subset, best_ratio

    @staticmethod
    def _score_confidence(balance_ratio: float, snapshots: int) -> float:
        """Confidence from power balance closeness and snapshot count."""
        if balance_ratio <= 0:
            return 0.0
        balance_score = max(0.0, 1.0 - abs(1.0 - balance_ratio) * 5)
        snapshot_factor = min(1.0, snapshots / 5)  # 5 snapshots = full confidence
        return round(balance_score * 0.7 + snapshot_factor * 0.3, 3)

    @staticmethod
    def _classify_load_pattern(node: DeviceNode) -> LoadPattern:
        """Classify using temporal model data first, PF heuristic as fallback."""
        # Try Phase 3B temporal classification (more accurate — uses historical data)
        try:
            from ..prediction.temporal_monitor import TemporalManager
            tm = TemporalManager.instance()
            status = tm.get_status(node.device_id)
            if status and hasattr(status, "load_pattern"):
                lp = getattr(status, "load_pattern", "unknown")
                if lp and lp != "unknown":
                    return LoadPattern(lp)
        except Exception:
            pass

        # Fallback: instantaneous PF-based heuristic
        pf = node.power_factor
        if pf == 0:
            return LoadPattern.UNKNOWN
        if pf < 0.75:
            return LoadPattern.MOTOR  # inductive, low PF
        if pf >= 0.93:
            return LoadPattern.LIGHTING  # near-unity PF
        if 0.85 <= pf <= 0.95:
            return LoadPattern.UPS  # moderate PF, constant
        return LoadPattern.MIXED


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()
