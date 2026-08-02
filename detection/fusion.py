#!/usr/bin/env python3
"""
Detection — Fusion Engine.

Gộp tất cả tín hiệu (Cold Start / Z-Score + CUSUM + Salary) → 1 anomaly score
duy nhất mỗi công ty. Output daily JSON report.

Công thức:
  - Công ty mới (< 14 ngày history): Cold Start Score (100%)
  - Công ty có history (≥ 14 ngày): Weighted sum:
      WEIGHT_ZSCORE * zscore_score
    + WEIGHT_CUSUM * cusum_score
    + WEIGHT_SALARY * salary_score

Usage:
    python detection/fusion.py                  # Generate today's report
    python detection/fusion.py --date 2026-08-02
    python detection/fusion.py --dry-run
"""

import argparse
import json
import sys
from datetime import datetime
from pathlib import Path
from collections import Counter

_SCRIPT_DIR = Path(__file__).resolve().parent
_PROJECT_ROOT = _SCRIPT_DIR.parent
if str(_PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(_PROJECT_ROOT))

from config.settings import (
    REPORTS_DIR,
    WEIGHT_ZSCORE,
    WEIGHT_CUSUM,
    WEIGHT_COLD_START,
    WEIGHT_SALARY,
    ALERT_RED,
    ALERT_ORANGE,
    ALERT_YELLOW,
)

from pipeline.storage import load_history, get_company_history, is_new_company
from detection.cold_start import cold_start_score
from detection.zscore import compute_zscore, compute_cusum, zscore_score, cusum_score
from detection.salary import salary_anomaly_score


def compute_fusion_score(
    company_name: str,
    company_history: dict,
    todays_jobs: list[dict],
) -> dict:
    """
    Tính anomaly score tổng hợp cho 1 công ty.

    Args:
        company_name: Tên công ty
        company_history: dict từ get_company_history()
        todays_jobs: List job dicts của công ty hôm nay

    Returns:
        {
            "company": str,
            "final_score": float,       # 0→1
            "alert_level": "red" | "orange" | "yellow" | "none",
            "detection_type": "cold_start" | "statistical",
            "signals": {                # Từng tín hiệu riêng
                "cold_start": {...} | None,
                "zscore": {...} | None,
                "cusum": {...} | None,
                "salary": {...} | None,
            },
            "context": {                # Context info
                "job_count_today": int,
                "job_titles": [str],
                "is_new_company": bool,
                "days_active": int,
                "it_ratio": float,
            },
            "recommendation": str,      # Text mô tả
        }
    """
    is_new = is_new_company(company_history)

    # Extract salaries from today's jobs
    salaries_usd = []
    for job in todays_jobs:
        sal = job.get("salary", {})
        if isinstance(sal, dict) and sal.get("type") in ("range", "single", "up_to"):
            val = sal.get("max") or sal.get("min")
            if val:
                currency = sal.get("currency", "USD")
                if currency == "VND":
                    val = val / 25000
                salaries_usd.append(val)

    job_titles = [j.get("title", "") for j in todays_jobs]

    signals = {}
    recommendations = []

    if is_new:
        # ── Cold Start ──
        cs_result = cold_start_score(
            job_count=company_history.get("total_jobs_today", 0),
            role_categories=company_history.get("role_categories", {}),
            job_titles=job_titles,
            salaries_usd=salaries_usd,
            it_ratio=company_history.get("it_ratio", 0),
        )
        signals["cold_start"] = cs_result
        signals["zscore"] = None
        signals["cusum"] = None

        final_score = cs_result["total_score"]

        if cs_result["is_anomaly"]:
            recommendations.append(
                f"Công ty mới ({company_history.get('total_jobs_today', 0)} jobs, "
                f"{len(company_history.get('role_categories', {}))} roles)"
            )
            if cs_result["components"].get("volume_score", 0) > 0.15:
                recommendations.append("Số lượng tuyển dụng cao")
            if cs_result["components"].get("seniority_score", 0) > 0.10:
                recommendations.append(f"Nhiều Senior ({cs_result['details']['senior_ratio']:.0%})")
            if cs_result["components"].get("salary_score", 0) > 0:
                recommendations.append("Lương cao hơn market")
    else:
        # ── Statistical ──
        z_result = compute_zscore(company_history.get("daily_counts", {}))
        c_result = compute_cusum(company_history.get("daily_counts", {}))

        z_score_val = zscore_score(z_result)
        c_score_val = cusum_score(c_result)

        signals["cold_start"] = None
        signals["zscore"] = {
            **z_result,
            "signal_score": z_score_val,
        }
        signals["cusum"] = {
            **c_result,
            "signal_score": c_score_val,
        }

        # Salary check
        sal_result = salary_anomaly_score(todays_jobs)
        signals["salary"] = sal_result

        # Weighted fusion
        final_score = (
            WEIGHT_ZSCORE * z_score_val
            + WEIGHT_CUSUM * c_score_val
            + WEIGHT_SALARY * sal_result["score"]
        )

        # Build recommendations
        if z_result.get("alert_level") != "none":
            recommendations.append(
                f"Z-Score spike: {z_result.get('z_score', 0):.1f}σ "
                f"(baseline: {z_result.get('baseline', 0):.1f}, today: {z_result.get('today_count', 0)})"
            )
        if c_result.get("is_triggered"):
            recommendations.append("CUSUM triggered — sustained hiring increase")
        if sal_result["anomaly_count"] > 0:
            for a in sal_result["anomalies"][:2]:
                recommendations.append(
                    f"Salary anomaly: {a['title'][:40]} ${a['salary_usd']:,.0f} "
                    f"(P90: ${a['benchmark_p90']:,.0f})"
                )

    # ── Alert Level ──
    if final_score >= ALERT_RED:
        alert_level = "red"
    elif final_score >= ALERT_ORANGE:
        alert_level = "orange"
    elif final_score >= ALERT_YELLOW:
        alert_level = "yellow"
    else:
        alert_level = "none"

    # Final recommendation text
    if not recommendations:
        if is_new:
            recommendations.append(f"Công ty mới, {company_history.get('total_jobs_today', 0)} jobs IT")
        else:
            recommendations.append(f"Hoạt động bình thường ({company_history.get('total_jobs_today', 0)} jobs hôm nay)")

    return {
        "company": company_name,
        "final_score": round(final_score, 3),
        "alert_level": alert_level,
        "detection_type": "cold_start" if is_new else "statistical",
        "is_new_company": is_new,
        "signals": signals,
        "context": {
            "job_count_today": company_history.get("total_jobs_today", 0),
            "job_titles": job_titles,
            "days_active": company_history.get("days_active", 0),
            "it_ratio": round(company_history.get("it_ratio", 0), 2),
            "role_categories": company_history.get("role_categories", {}),
        },
        "recommendation": "; ".join(recommendations),
    }


from typing import Optional


def generate_report(date_str: Optional[str] = None) -> dict:
    """
    Generate daily anomaly report cho tất cả công ty IT.

    Args:
        date_str: Ngày cần analyze (default: hôm nay)

    Returns:
        {
            "report_date": str,
            "generated_at": str,
            "summary": {
                "total_companies_analyzed": int,
                "red_alerts": int,
                "orange_alerts": int,
                "yellow_alerts": int,
                ...
            },
            "alerts": [dict],     # Sorted by final_score desc
            "all_scores": [dict], # All companies for dashboard
        }
    """
    if date_str is None:
        date_str = datetime.now().strftime("%Y-%m-%d")

    print(f"\n{'=' * 60}")
    print(f"🧬 FUSION ENGINE — {date_str}")
    print(f"{'=' * 60}\n")

    # Load data
    df = load_history(date_str)
    if df.empty:
        print("  ⚠️  No data in window")
        return {
            "report_date": date_str,
            "generated_at": datetime.now().isoformat(),
            "summary": {"total_companies_analyzed": 0},
            "alerts": [],
            "all_scores": [],
        }

    companies = get_company_history(df)
    print(f"  📊 Analyzing {len(companies)} companies with IT jobs...")

    all_results = []

    for company_name, company_history in companies.items():
        # Bỏ qua company không đủ IT ratio
        if not company_history.get("it_worthy", True):
            continue

        # Bỏ qua company không có job hôm nay
        if company_history.get("total_jobs_today", 0) == 0:
            continue

        # Get today's jobs
        today = df["date"].max()
        todays_jobs = df[
            (df["company"] == company_name)
            & (df["date"] == today)
        ].to_dict("records")

        result = compute_fusion_score(company_name, company_history, todays_jobs)
        all_results.append(result)

    # Sort by score desc
    all_results.sort(key=lambda x: (-x["final_score"], x["company"]))

    # Separate alerts from normal
    alerts = [r for r in all_results if r["alert_level"] != "none"]
    normal = [r for r in all_results if r["alert_level"] == "none"]

    # Summary
    red_count = sum(1 for r in all_results if r["alert_level"] == "red")
    orange_count = sum(1 for r in all_results if r["alert_level"] == "orange")
    yellow_count = sum(1 for r in all_results if r["alert_level"] == "yellow")
    cold_start_count = sum(1 for r in all_results if r["detection_type"] == "cold_start")

    # Print report
    if alerts:
        print(f"\n  🚨 ALERTS ({len(alerts)} companies):")
        for r in alerts:
            emoji = {"red": "🔴", "orange": "🟠", "yellow": "🟡"}.get(r["alert_level"], "⚪")
            new_tag = " 🆕NEW" if r["is_new_company"] else ""
            print(f"  {emoji} {r['company']}{new_tag}: score={r['final_score']:.2f} "
                  f"({r['context']['job_count_today']} jobs, {r['detection_type']})")
            print(f"     💬 {r['recommendation']}")

    if normal:
        print(f"\n  ✅ NORMAL ({len(normal)} companies)")

    print(f"\n  📊 Summary:")
    print(f"     Total analyzed:  {len(all_results)}")
    print(f"     New companies:   {cold_start_count}")
    print(f"     🔴 Red:          {red_count}")
    print(f"     🟠 Orange:       {orange_count}")
    print(f"     🟡 Yellow:        {yellow_count}")
    print(f"     ✅ Normal:       {len(normal)}")
    print(f"{'=' * 60}\n")

    return {
        "report_date": date_str,
        "generated_at": datetime.now().isoformat(),
        "summary": {
            "total_companies_analyzed": len(all_results),
            "new_companies": cold_start_count,
            "red_alerts": red_count,
            "orange_alerts": orange_count,
            "yellow_alerts": yellow_count,
            "normal": len(normal),
            "companies_with_salary": sum(
                1 for r in all_results
                if r["signals"].get("salary") and r["signals"]["salary"]["total_visible"] > 0
            ),
        },
        "alerts": alerts,
        "all_scores": all_results,
    }


def save_report(report: dict, date_str: str):
    """Lưu daily report ra JSON."""
    output_path = REPORTS_DIR / f"{date_str}.json"
    output_path.parent.mkdir(parents=True, exist_ok=True)

    # Convert non-serializable types
    with open(output_path, "w", encoding="utf-8") as f:
        json.dump(report, f, indent=2, ensure_ascii=False, default=str)

    print(f"💾 Report saved → {output_path}")


# ─── CLI ────────────────────────────────────────────────

def main():
    parser = argparse.ArgumentParser(
        description="Fusion Engine — Hiring Watchdog Daily Report",
    )
    parser.add_argument("--date", type=str, default=None,
                        help="Ngày analyze (YYYY-MM-DD, default: hôm nay)")
    parser.add_argument("--dry-run", action="store_true",
                        help="Không lưu report")

    args = parser.parse_args()
    date_str = args.date or datetime.now().strftime("%Y-%m-%d")

    report = generate_report(date_str)

    if not args.dry_run and report["all_scores"]:
        save_report(report, date_str)


if __name__ == "__main__":
    main()
