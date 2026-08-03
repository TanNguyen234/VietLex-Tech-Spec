from __future__ import annotations

import math
from typing import Any, Dict, List


def calculate_percentile(data: List[float], percentile: float) -> float:
    if not data:
        return 0.0
    sorted_data = sorted(data)
    k = (len(sorted_data) - 1) * (percentile / 100.0)
    f = math.floor(k)
    c = math.ceil(k)
    if f == c:
        return sorted_data[int(k)]
    d0 = sorted_data[int(f)] * (c - k)
    d1 = sorted_data[int(c)] * (k - f)
    return d0 + d1


def calculate_stage_latency_summary(latencies_list: List[Dict[str, float]]) -> Dict[str, Dict[str, float]]:
    """Calculates P50, P95, Mean, Min, Max for all latency keys across cases."""
    if not latencies_list:
        return {}

    # Extract all distinct latency keys
    keys = set()
    for lat in latencies_list:
        keys.update(lat.keys())

    summary: Dict[str, Dict[str, float]] = {}
    for key in sorted(keys):
        vals = [lat[key] for lat in latencies_list if key in lat and isinstance(lat[key], (int, float))]
        if not vals:
            continue
        total = sum(vals)
        count = len(vals)
        mean_val = total / count
        p50 = calculate_percentile(vals, 50.0)
        p95 = calculate_percentile(vals, 95.0)
        min_val = min(vals)
        max_val = max(vals)

        summary[key] = {
            "mean": round(mean_val, 4),
            "p50": round(p50, 4),
            "p95": round(p95, 4),
            "min": round(min_val, 4),
            "max": round(max_val, 4),
            "count": count
        }
    return summary
