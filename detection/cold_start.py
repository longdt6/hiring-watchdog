#!/usr/bin/env python3
"""
Detection — Cold Start Score.

Đánh giá công ty MỚI (chưa có history ≥ 14 ngày) dựa trên rule-based scoring:
  1. Absolute volume — số lượng job hôm nay
  2. Role diversity — số loại role khác nhau
  3. Seniority ratio — % Senior+
  4. Salary premium — % above market P90
  5. IT check — % job là IT

Usage:
    from detection.cold_start import cold_start_score
"""

import sys
from pathlib import Path

_SCRIPT_DIR = Path(__file__).resolve().parent
_PROJECT_ROOT = _SCRIPT_DIR.parent
if str(_PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(_PROJECT_ROOT))

from config.settings import (
    COLD_START_THRESHOLD,
    COLD_START_VOLUME,
    COLD_START_DIVERSITY,
    COLD_START_SENIORITY,
    COLD_START_SALARY_PREMIUM,
    COLD_START_IT_CHECK,
    IT_RATIO_THRESHOLD,
)
from config.salary_reference import SALARY_BENCHMARK, get_default_benchmark
from pipeline.storage import _extract_role_category, _classify_seniority


def _compute_volume_score(job_count: int) -> float:
    """Score từ số lượng job tuyệt đối."""
    for threshold, score in sorted(COLD_START_VOLUME.items(), reverse=True):
        if job_count >= threshold:
            return score
    return 0.0


def _compute_diversity_score(role_categories: dict) -> float:
    """Score từ số role categories unique."""
    unique_roles = len(role_categories)
    for threshold, score in sorted(COLD_START_DIVERSITY.items(), reverse=True):
        if unique_roles >= threshold:
            return score
    return 0.0


def _compute_seniority_score(job_titles: list[str]) -> float:
    """Score từ % Senior+ jobs. Với ít job, seniority ratio kém tin cậy hơn."""
    if not job_titles:
        return 0.0

    senior_count = sum(
        1 for t in job_titles if _classify_seniority(t) == "senior"
    )
    senior_ratio = senior_count / len(job_titles)

    # Small sample penalty: nếu < 3 jobs, scale score down
    sample_factor = min(1.0, len(job_titles) / 3.0)

    for threshold, score in sorted(COLD_START_SENIORITY.items(), reverse=True):
        if senior_ratio >= threshold:
            return score * sample_factor
    return 0.0


def _compute_salary_score(salaries_usd: list[float], job_titles: list[str]) -> float:
    """
    Score từ salary premium: so sánh salary với market P90.

    Args:
        salaries_usd: List salary values converted to USD
        job_titles: List job titles tương ứng để xác định role

    Returns:
        Score dựa trên % jobs có salary > market P90.
    """
    if not salaries_usd or not job_titles:
        return 0.0

    premium_count = 0
    valid_count = 0

    for sal, title in zip(salaries_usd, job_titles):
        if sal is None or sal <= 0:
            continue
        valid_count += 1

        role = _extract_role_category(title)
        level = _classify_seniority(title)

        # Get market P90 for this role+level
        benchmark_key = f"{role}_{level}"
        benchmark = SALARY_BENCHMARK.get(benchmark_key, get_default_benchmark())
        p90 = benchmark["p90"]

        if sal >= p90 * 1.3:  # 30% above P90
            premium_count += 1

    if valid_count == 0:
        return 0.0

    premium_ratio = premium_count / valid_count

    for threshold, score in sorted(COLD_START_SALARY_PREMIUM.items(), reverse=True):
        if premium_ratio >= threshold:
            return score
    return 0.0


def _compute_it_score(it_ratio: float) -> float:
    """Score từ IT ratio."""
    if it_ratio >= IT_RATIO_THRESHOLD:
        return COLD_START_IT_CHECK
    return 0.0


def cold_start_score(
    job_count: int,
    role_categories: dict[str, int],
    job_titles: list[str],
    salaries_usd: list[float],
    it_ratio: float,
) -> dict:
    """
    Tính Cold Start Score cho 1 công ty.

    Args:
        job_count: Số job hôm nay
        role_categories: {role_category: count} từ job titles hôm nay
        job_titles: Danh sách titles
        salaries_usd: Danh sách salary values (đã convert sang USD)
        it_ratio: % job là IT

    Returns:
        {
            "total_score": float,        # 0.0 → 1.0
            "is_anomaly": bool,          # total_score >= COLD_START_THRESHOLD
            "components": {
                "volume_score": float,
                "diversity_score": float,
                "seniority_score": float,
                "salary_score": float,
                "it_score": float,
            },
            "details": {
                "job_count": int,
                "unique_roles": int,
                "senior_ratio": float,
                "salary_premium_ratio": float,
                "it_ratio": float,
            },
        }
    """
    volume_score = _compute_volume_score(job_count)
    diversity_score = _compute_diversity_score(role_categories)
    seniority_score = _compute_seniority_score(job_titles)

    # Salary premium
    salary_score = _compute_salary_score(salaries_usd, job_titles)

    # IT check
    it_score = _compute_it_score(it_ratio)

    # Calculate seniority ratio for details
    if job_titles:
        senior_count = sum(1 for t in job_titles if _classify_seniority(t) == "senior")
        senior_ratio = senior_count / len(job_titles)
    else:
        senior_ratio = 0.0

    # Calculate salary premium ratio for details
    if salaries_usd and job_titles:
        premium_count = 0
        valid_count = 0
        for sal, title in zip(salaries_usd, job_titles):
            if sal is None or sal <= 0:
                continue
            valid_count += 1
            role = _extract_role_category(title)
            level = _classify_seniority(title)
            benchmark_key = f"{role}_{level}"
            benchmark = SALARY_BENCHMARK.get(benchmark_key, get_default_benchmark())
            if sal >= benchmark["p90"] * 1.3:
                premium_count += 1
        salary_premium_ratio = premium_count / valid_count if valid_count > 0 else 0.0
    else:
        salary_premium_ratio = 0.0

    total_score = (
        volume_score
        + diversity_score
        + seniority_score
        + salary_score
        + it_score
    )

    # Clamp to [0, 1]
    total_score = min(1.0, max(0.0, total_score))

    # Suppress alerts for very small companies unless they have salary premium
    # A single senior job isn't unusual; only flag if ≥ 3 jobs or salary premium
    effective_anomaly = total_score >= COLD_START_THRESHOLD
    if effective_anomaly and job_count < 3 and salary_score == 0:
        effective_anomaly = False

    return {
        "total_score": total_score,
        "is_anomaly": effective_anomaly,
        "threshold": COLD_START_THRESHOLD,
        "detection_type": "cold_start",
        "components": {
            "volume_score": volume_score,
            "diversity_score": diversity_score,
            "seniority_score": seniority_score,
            "salary_score": salary_score,
            "it_score": it_score,
        },
        "details": {
            "job_count": job_count,
            "unique_roles": len(role_categories),
            "senior_ratio": round(senior_ratio, 2),
            "salary_premium_ratio": round(salary_premium_ratio, 2),
            "it_ratio": round(it_ratio, 2),
        },
    }


# ─── CLI Test ───────────────────────────────────────────

def main():
    """Test Cold Start scoring on today's data."""
    from pipeline.storage import load_history, get_company_history, is_new_company

    print("Loading data...")
    df = load_history()
    companies = get_company_history(df)

    print(f"\n{'=' * 60}")
    print("🆕 COLD START SCORE — Companies with < 14 days history")
    print(f"{'=' * 60}\n")

    new_companies = [
        (name, info) for name, info in companies.items()
        if is_new_company(info) and info["total_jobs_today"] > 0
    ]

    for name, info in sorted(new_companies, key=lambda x: -x[1]["total_jobs_today"]):
        # Extract salaries from today's jobs
        today_jobs = df[
            (df["company"] == name)
            & (df["date"] == df["date"].max())
        ]

        salaries = []
        for _, row in today_jobs.iterrows():
            sal = row.get("salary", {})
            if isinstance(sal, dict) and sal.get("type") in ("range", "single", "up_to"):
                val = sal.get("max") or sal.get("min")
                if val:
                    currency = sal.get("currency", "USD")
                    if currency == "VND":
                        val = val / 25000
                    salaries.append(val)

        score = cold_start_score(
            job_count=info["total_jobs_today"],
            role_categories=info.get("role_categories", {}),
            job_titles=info.get("job_titles", []),
            salaries_usd=salaries,
            it_ratio=info.get("it_ratio", 0),
        )

        flag = "🔴" if score["is_anomaly"] else "  "
        print(f"  {flag} {name}: score={score['total_score']:.2f} "
              f"(vol={score['components']['volume_score']:.2f} "
              f"div={score['components']['diversity_score']:.2f} "
              f"sen={score['components']['seniority_score']:.2f} "
              f"sal={score['components']['salary_score']:.2f})")
        print(f"     {info['total_jobs_today']} jobs, "
              f"{score['details']['unique_roles']} roles, "
              f"{score['details']['senior_ratio']:.0%} senior, "
              f"IT ratio: {score['details']['it_ratio']:.0%}")


if __name__ == "__main__":
    main()
