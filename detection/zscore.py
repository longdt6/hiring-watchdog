#!/usr/bin/env python3
"""
Detection — Rolling Z-Score + CUSUM.

Cho các công ty có history ≥ 14 ngày.
- Z-Score: phát hiện spike đơn lẻ (point anomaly)
- CUSUM: phát hiện level shift kéo dài

Usage:
    from detection.zscore import compute_zscore, compute_cusum
"""

import sys
from pathlib import Path

_SCRIPT_DIR = Path(__file__).resolve().parent
_PROJECT_ROOT = _SCRIPT_DIR.parent
if str(_PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(_PROJECT_ROOT))

import numpy as np

from config.settings import (
    ZSCORE_ORANGE,
    ZSCORE_RED,
    EMA_ALPHA,
    CUSUM_K,
    CUSUM_H,
)


def _compute_ema(values: np.ndarray, alpha: float) -> np.ndarray:
    """
    Tính Exponential Moving Average.

    EMA_t = alpha * X_t + (1 - alpha) * EMA_{t-1}
    """
    ema = np.zeros_like(values)
    ema[0] = values[0]
    for t in range(1, len(values)):
        ema[t] = alpha * values[t] + (1 - alpha) * ema[t - 1]
    return ema


def compute_zscore(daily_counts: dict[str, int]) -> dict:
    """
    Tính Rolling Z-Score cho 1 công ty.

    Z = (today - baseline) / rolling_std

    Baseline = EMA của 4 tuần gần nhất.
    rolling_std = std của 4 tuần gần nhất.

    Args:
        daily_counts: {date_str: job_count} — toàn bộ lịch sử đã biết

    Returns:
        {
            "z_score": float | None,
            "baseline": float,           # EMA baseline
            "rolling_std": float,        # Rolling standard deviation
            "today_count": int,          # Job count hôm nay
            "alert_level": "red" | "orange" | "none",
            "days_of_history": int,
        }
    """
    if not daily_counts:
        return {
            "z_score": None,
            "baseline": 0,
            "rolling_std": 0,
            "today_count": 0,
            "alert_level": "none",
            "days_of_history": 0,
            "error": "No data",
        }

    # Sort dates
    sorted_dates = sorted(daily_counts.keys())
    values = np.array([daily_counts[d] for d in sorted_dates], dtype=float)

    if len(values) < 3:
        return {
            "z_score": None,
            "baseline": float(np.mean(values)),
            "rolling_std": float(np.std(values)) if len(values) > 1 else 0,
            "today_count": int(values[-1]),
            "alert_level": "none",
            "days_of_history": len(values),
            "error": "Insufficient data (< 3 days)",
        }

    # Today = last value
    today_count = values[-1]

    # Baseline = EMA of all but today
    if len(values) > 1:
        historical = values[:-1]
        ema = _compute_ema(historical, EMA_ALPHA)
        baseline = float(ema[-1])
        rolling_std = float(np.std(historical))
    else:
        baseline = float(values[0])
        rolling_std = 0.0

    # Z-Score
    if rolling_std > 0:
        z_score = (today_count - baseline) / rolling_std
        z_score = float(z_score)
    elif today_count > baseline:
        z_score = float("inf")  # Spike but no variation
    else:
        z_score = 0.0

    # Alert level
    if z_score is None or z_score == float("inf"):
        pass  # handled below

    if z_score is not None and z_score != float("inf"):
        if z_score >= ZSCORE_RED:
            alert_level = "red"
        elif z_score >= ZSCORE_ORANGE:
            alert_level = "orange"
        else:
            alert_level = "none"
    elif z_score == float("inf"):
        alert_level = "red" if today_count >= 3 else "orange"
    else:
        alert_level = "none"

    return {
        "z_score": z_score if z_score != float("inf") else 999.0,  # cap for display
        "baseline": baseline,
        "rolling_std": rolling_std,
        "today_count": int(today_count),
        "alert_level": alert_level,
        "days_of_history": len(values),
        "detection_type": "zscore",
    }


def compute_cusum(daily_counts: dict[str, int]) -> dict:
    """
    Tính CUSUM cho 1 công ty.

    S_t = max(0, S_{t-1} + (x_t - μ₀) / σ - K)
    Alert khi S_t > H

    Args:
        daily_counts: {date_str: job_count}

    Returns:
        {
            "cusum_value": float,       # CUSUM hiện tại
            "is_triggered": bool,       # CUSUM > H?
            "alert_level": "orange" | "none",
            "details": {...},
        }
    """
    if not daily_counts or len(daily_counts) < 3:
        return {
            "cusum_value": 0,
            "is_triggered": False,
            "alert_level": "none",
            "days_of_history": len(daily_counts) if daily_counts else 0,
            "detection_type": "cusum",
            "error": "Insufficient data",
        }

    sorted_dates = sorted(daily_counts.keys())
    values = np.array([daily_counts[d] for d in sorted_dates], dtype=float)

    # μ₀ = mean of historical values (not including today if possible)
    if len(values) > 1:
        mu_0 = float(np.mean(values[:-1]))
        sigma = float(np.std(values[:-1]))
    else:
        mu_0 = float(values[0])
        sigma = 0.0

    if sigma <= 0:
        sigma = max(mu_0 * 0.3, 0.5)  # Minimum std to avoid division by zero

    # Normalized deviation
    x_today = values[-1]
    deviation = (x_today - mu_0) / sigma

    # CUSUM: we need the full sequence to compute properly
    # For daily script, we approximate: CUSUM builds from last CUSUM value
    # For full computation, iterate through all values
    cusum = 0.0
    cusum_history = []
    triggered = False
    trigger_day = None

    for x in values:
        dev = (x - mu_0) / sigma
        cusum = max(0.0, cusum + dev - CUSUM_K)
        cusum_history.append(float(cusum))
        if cusum > CUSUM_H:
            triggered = True
            if trigger_day is None:
                trigger_day = sorted_dates[len(cusum_history) - 1]

    cusum_value = float(cusum)

    return {
        "cusum_value": cusum_value,
        "is_triggered": triggered,
        "alert_level": "orange" if triggered else "none",
        "days_of_history": len(values),
        "detection_type": "cusum",
        "details": {
            "mu_0": mu_0,
            "sigma": sigma,
            "today_deviation": float(deviation),
            "trigger_day": trigger_day,
            "cusum_history": cusum_history[-7:],  # Last 7 days
            "threshold_h": CUSUM_H,
            "slack_k": CUSUM_K,
        },
    }


def zscore_score(zscore_result: dict) -> float:
    """
    Chuyển Z-Score result thành anomaly score 0→1.

    Scale:
      Z = 1.0 → score 0.10
      Z = 2.0 → score 0.30
      Z = 2.5 → score 0.50
      Z = 3.0 → score 0.70
      Z = 4.0 → score 0.90
      Z = 5.0+→ score 1.00
    """
    z = zscore_result.get("z_score")
    if z is None:
        return 0.0

    # Sigmoid-like scaling
    if z >= 5.0:
        return 1.0
    elif z >= 3.0:
        return 0.70 + 0.30 * (z - 3.0) / 2.0  # 0.70 → 1.0
    elif z >= 2.0:
        return 0.30 + 0.40 * (z - 2.0) / 1.0  # 0.30 → 0.70
    elif z >= 1.0:
        return 0.10 + 0.20 * (z - 1.0) / 1.0  # 0.10 → 0.30
    elif z > 0:
        return 0.10 * z  # 0 → 0.10
    else:
        return 0.0


def cusum_score(cusum_result: dict) -> float:
    """
    Chuyển CUSUM result thành anomaly score 0→1.

    Scale:
      CUSUM / H ratio:
        < 0.5 → 0.0
        0.5-1.0 → 0.1-0.4
        1.0-1.5 → 0.4-0.7
        1.5+ → 0.7-1.0
    """
    if cusum_result.get("is_triggered", False):
        # Map trigger intensity
        cusum_val = cusum_result.get("cusum_value", 0)
        ratio = cusum_val / CUSUM_H if CUSUM_H > 0 else 0
        return min(1.0, 0.40 + 0.60 * (ratio - 1.0) / 1.0)  # 0.40 → 1.0
    else:
        cusum_val = cusum_result.get("cusum_value", 0)
        ratio = cusum_val / CUSUM_H if CUSUM_H > 0 else 0
        return min(0.40, 0.40 * ratio / 0.5)  # 0 → 0.40 as it approaches H


# ─── CLI Test ───────────────────────────────────────────

def main():
    """Test Z-Score + CUSUM on current data."""
    from pipeline.storage import load_history, get_company_history, is_new_company

    print("Loading data...")
    df = load_history()
    companies = get_company_history(df)

    print(f"\n{'=' * 60}")
    print("📊 Z-SCORE + CUSUM — Companies with ≥ 14 days history")
    print(f"{'=' * 60}\n")

    old_companies = [
        (name, info) for name, info in companies.items()
        if not is_new_company(info) and info["total_jobs_today"] > 0
    ]

    if not old_companies:
        print("  (none — all companies are new, need more data)")
        return

    for name, info in sorted(old_companies, key=lambda x: -x[1]["total_jobs_today"]):
        z = compute_zscore(info["daily_counts"])
        c = compute_cusum(info["daily_counts"])

        z_flag = "🔴" if z["alert_level"] == "red" else ("🟠" if z["alert_level"] == "orange" else "  ")
        c_flag = "🔴" if c["is_triggered"] else "  "

        print(f"  {z_flag} {c_flag} {name}: {info['total_jobs_today']} today")
        print(f"     Z-Score: {z['z_score']:.2f} | baseline={z['baseline']:.1f} "
              f"σ={z['rolling_std']:.1f} | score={zscore_score(z):.2f}")
        if c.get("details"):
            print(f"     CUSUM: {c['cusum_value']:.2f} | μ₀={c['details']['mu_0']:.1f} "
                  f"H={c['details']['threshold_h']} | score={cusum_score(c):.2f}")


if __name__ == "__main__":
    main()
