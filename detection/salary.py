#!/usr/bin/env python3
"""
Detection — Salary Anomaly.

So sánh salary của từng job với market benchmark P90.
Flag nếu salary ≥ 30% above P90 của role+level tương ứng.

Usage:
    from detection.salary import salary_anomaly_score
"""

import sys
from pathlib import Path

_SCRIPT_DIR = Path(__file__).resolve().parent
_PROJECT_ROOT = _SCRIPT_DIR.parent
if str(_PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(_PROJECT_ROOT))

from config.salary_reference import SALARY_BENCHMARK, get_default_benchmark
from pipeline.storage import _extract_role_category, _classify_seniority


def classify_role_level(title: str) -> tuple[str, str, str]:
    """
    Phân loại role + level từ job title.

    Returns:
        (role_key, level, benchmark_key)
        Ví dụ: ("backend", "senior", "backend_senior")
    """
    role = _extract_role_category(title)
    level = _classify_seniority(title)

    if level == "unknown":
        level = "mid"  # Default to mid

    benchmark_key = f"{role}_{level}"
    return role, level, benchmark_key


def get_salary_benchmark(title: str) -> dict:
    """
    Lấy salary benchmark cho 1 job title.

    Returns:
        {"p50": ..., "p75": ..., "p90": ...}
    """
    _, _, benchmark_key = classify_role_level(title)
    return SALARY_BENCHMARK.get(benchmark_key, get_default_benchmark())


def check_salary_anomaly(title: str, salary_usd: float) -> dict:
    """
    Kiểm tra 1 job có salary bất thường không.

    Args:
        title: Job title
        salary_usd: Salary in USD

    Returns:
        {
            "is_anomaly": bool,       # Salary ≥ 30% above P90
            "salary_usd": float,
            "benchmark_p90": float,
            "premium_pct": float,     # % above P90
            "role_level": str,        # e.g. "backend_senior"
            "role": str,
            "level": str,
        }
    """
    role, level, benchmark_key = classify_role_level(title)
    benchmark = SALARY_BENCHMARK.get(benchmark_key, get_default_benchmark())

    p90 = benchmark["p90"]
    p50 = benchmark["p50"]
    p75 = benchmark["p75"]

    premium_pct = (salary_usd - p90) / p90 if p90 > 0 else 0

    # Anomaly if ≥ 30% above P90
    is_anomaly = premium_pct >= 0.30

    # Also check absolute threshold: at least $500 above P90
    if salary_usd - p90 < 500 and is_anomaly:
        is_anomaly = False  # Too small absolute difference

    return {
        "is_anomaly": is_anomaly,
        "salary_usd": round(salary_usd),
        "benchmark_p90": p90,
        "benchmark_p75": p75,
        "benchmark_p50": p50,
        "premium_pct": round(premium_pct, 2),
        "role_level": benchmark_key,
        "role": role,
        "level": level,
    }


def salary_anomaly_score(jobs: list[dict]) -> dict:
    """
    Tính salary anomaly score cho 1 công ty dựa trên tất cả jobs.

    Args:
        jobs: List job dicts với 'salary' và 'title'

    Returns:
        {
            "score": float,           # 0→1
            "anomaly_count": int,     # Số job có salary anomaly
            "total_visible": int,     # Số job có salary visible
            "anomalies": [dict],      # Chi tiết từng anomaly
            "avg_premium_pct": float,
        }
    """
    anomalies = []
    total_visible = 0

    for job in jobs:
        sal = job.get("salary", {})
        if not isinstance(sal, dict):
            continue
        if sal.get("type") not in ("range", "single", "up_to"):
            continue

        # Get salary value in USD
        val = sal.get("max") or sal.get("min")
        if not val:
            continue

        currency = sal.get("currency", "USD")
        if currency == "VND":
            val = val / 25000

        total_visible += 1
        result = check_salary_anomaly(job.get("title", ""), val)

        if result["is_anomaly"]:
            anomalies.append({
                "title": job.get("title", ""),
                "company": job.get("company", ""),
                "salary_usd": result["salary_usd"],
                "benchmark_p90": result["benchmark_p90"],
                "premium_pct": result["premium_pct"],
                "role_level": result["role_level"],
                "salary_text": sal.get("text", ""),
            })

    # Score: anomaly ratio + premium intensity
    if total_visible == 0 or not anomalies:
        return {
            "score": 0.0,
            "anomaly_count": 0,
            "total_visible": total_visible,
            "anomalies": [],
            "avg_premium_pct": 0.0,
        }

    anomaly_ratio = len(anomalies) / total_visible
    avg_premium = sum(a["premium_pct"] for a in anomalies) / len(anomalies)

    # Score = anomaly ratio * intensity
    # anomaly_ratio up to 1.0, avg_premium capped at 1.0
    score = anomaly_ratio * min(1.0, avg_premium)

    return {
        "score": round(min(1.0, score), 2),
        "anomaly_count": len(anomalies),
        "total_visible": total_visible,
        "anomalies": anomalies,
        "avg_premium_pct": round(avg_premium, 2),
    }


# ─── CLI Test ───────────────────────────────────────────

def main():
    """Test salary anomaly detection."""
    from pipeline.storage import load_history, get_company_history

    print("Loading data...")
    df = load_history()
    companies = get_company_history(df)

    print(f"\n{'=' * 60}")
    print("💰 SALARY ANOMALY CHECK")
    print(f"{'=' * 60}\n")

    for name, info in sorted(companies.items(), key=lambda x: -x[1]["total_jobs_today"]):
        if info["total_jobs_today"] == 0:
            continue

        today = df["date"].max()
        company_jobs = df[
            (df["company"] == name)
            & (df["date"] == today)
        ].to_dict("records")

        result = salary_anomaly_score(company_jobs)

        if result["total_visible"] > 0:
            print(f"  {name}: {result['total_visible']}/{info['total_jobs_today']} visible, "
                  f"{result['anomaly_count']} anomalies, score={result['score']:.2f}")
            for a in result["anomalies"]:
                print(f"    🔴 {a['title'][:60]}: ${a['salary_usd']:,.0f} "
                      f"(P90: ${a['benchmark_p90']:,.0f}, +{a['premium_pct']:.0%})")

    if not any(
        salary_anomaly_score(
            df[(df["company"] == n) & (df["date"] == df["date"].max())].to_dict("records")
        )["total_visible"] > 0
        for n in companies
    ):
        print("  (no visible salary data in today's jobs)")


if __name__ == "__main__":
    main()
