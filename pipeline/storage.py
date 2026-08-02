#!/usr/bin/env python3
"""
Storage — Load processed JSON files, compute per-company history.

Loads last N days of processed/*.json files into a pandas DataFrame,
computes per-company metrics: daily job count, avg salary, role distribution,
seniority ratio, IT ratio.

Usage:
    from pipeline.storage import load_history, get_company_history
"""

import json
import sys
from collections import defaultdict
from datetime import datetime, timedelta
from pathlib import Path
from typing import Optional

import numpy as np
import pandas as pd

# Ensure project root is on path
_SCRIPT_DIR = Path(__file__).resolve().parent
_PROJECT_ROOT = _SCRIPT_DIR.parent
if str(_PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(_PROJECT_ROOT))

from config.settings import (
    PROCESSED_DIR,
    HISTORY_WINDOW_DAYS,
    MIN_HISTORY_DAYS,
    IT_KEYWORDS,
    SENIOR_KEYWORDS,
    IT_RATIO_THRESHOLD,
)


def _is_it_job(title: str, skills: list[str]) -> bool:
    """Kiểm tra 1 job có phải IT job không (keyword-based)."""
    text = (title + " " + " ".join(skills or [])).lower()
    for kw in IT_KEYWORDS:
        if kw.lower() in text:
            return True
    return False


def _classify_seniority(title: str) -> str:
    """Phân loại seniority từ job title."""
    title_lower = title.lower()

    # Check senior first (more specific)
    for kw in SENIOR_KEYWORDS["senior"]:
        if kw in title_lower:
            return "senior"

    # Check junior
    for kw in SENIOR_KEYWORDS["junior"]:
        if kw in title_lower:
            return "junior"

    # Check mid
    for kw in SENIOR_KEYWORDS["mid"]:
        if kw in title_lower:
            return "mid"

    return "unknown"


def _extract_role_category(title: str) -> str:
    """Trích xuất role category từ title: backend, frontend, devops, ..."""
    title_lower = title.lower()

    mapping = [
        (["backend", "back-end", "back end"], "backend"),
        (["frontend", "front-end", "front end", "react", "angular", "vue", "vuejs"], "frontend"),
        (["fullstack", "full-stack", "full stack"], "fullstack"),
        (["mobile", "ios", "android", "flutter", "react native", "reactnative"], "mobile"),
        (["devops", "sre", "site reliability"], "devops"),
        (["cloud", "aws", "azure", "gcp"], "cloud"),
        (["data engineer", "data scientist", "machine learning", "ml engineer",
          "ai engineer", "nlp", "computer vision"], "data"),
        (["data analyst", "business intelligence", "bi "], "data_analyst"),
        (["qa", "tester", "test automation", "quality assurance", "quality engineer",
          "kiểm thử"], "qa"),
        (["security", "bảo mật", "an ninh mạng", "pentest", "an toàn thông tin"], "security"),
        (["network", "mạng", "system admin", "quản trị hệ thống", "quản trị mạng"], "network"),
        (["embedded", "firmware", "iot", "nhúng"], "embedded"),
        (["ux", "ui", "designer", "thiết kế", "product designer"], "designer"),
        (["business analyst", "ba ", "phân tích nghiệp vụ"], "ba"),
        (["product manager", "product owner"], "product_manager"),
        (["engineering manager", "cto", "vp of engineering", "technical director",
          "giám đốc công nghệ", "giám đốc kỹ thuật"], "engineering_manager"),
        (["tech lead", "team lead", "technical lead", "trưởng nhóm"], "tech_lead"),
    ]

    for keywords, category in mapping:
        for kw in keywords:
            if kw in title_lower:
                return category

    # Check IT keywords generally
    if _is_it_job(title, []):
        return "general"

    return "non_it"


def load_history(date_str: Optional[str] = None) -> pd.DataFrame:
    """
    Load tất cả processed jobs trong HISTORY_WINDOW_DAYS ngày qua.

    Args:
        date_str: Ngày reference (YYYY-MM-DD). Default: hôm nay.

    Returns:
        pd.DataFrame với tất cả jobs + computed columns:
          - is_it: bool
          - seniority: "senior" | "mid" | "junior" | "unknown"
          - role_category: "backend" | "frontend" | ...
          - date: date của job
    """
    if date_str is None:
        ref_date = datetime.now()
    else:
        ref_date = datetime.fromisoformat(date_str)

    all_jobs = []
    for i in range(HISTORY_WINDOW_DAYS):
        day = ref_date - timedelta(days=i)
        file_path = PROCESSED_DIR / f"{day.strftime('%Y-%m-%d')}.json"
        if not file_path.exists():
            continue

        with open(file_path, "r", encoding="utf-8") as f:
            jobs = json.load(f)

        for job in jobs:
            job["date"] = day.strftime("%Y-%m-%d")
            job["is_it"] = _is_it_job(job.get("title", ""), job.get("skills", []))
            job["seniority"] = _classify_seniority(job.get("title", ""))
            job["role_category"] = _extract_role_category(job.get("title", ""))
            all_jobs.append(job)

    if not all_jobs:
        return pd.DataFrame()

    df = pd.DataFrame(all_jobs)
    return df


def get_company_history(df: pd.DataFrame) -> dict:
    """
    Từ DataFrame jobs, aggregate theo company.

    Returns:
        dict: {
            company_name: {
                "daily_counts": {date_str: count},      # Job count mỗi ngày
                "total_jobs_today": int,
                "total_jobs_window": int,
                "avg_daily": float,
                "std_daily": float,
                "days_active": int,
                "it_ratio": float,
                "seniority_ratio": float,               # % Senior+
                "role_diversity": int,                  # Số role categories unique
                "avg_salary": float | None,             # USD (chỉ tính job có salary)
                "max_salary": float | None,
                "job_titles": [str],
                "role_categories": {category: count},
            }
        }
    """
    if df.empty:
        return {}

    # Chỉ lấy IT jobs để phân tích
    it_df = df[df["is_it"]].copy() if "is_it" in df.columns else df.copy()

    if it_df.empty:
        return {}

    companies = {}

    for company, group in it_df.groupby("company"):
        if not company or company.strip() == "":
            continue

        # Daily counts
        daily_counts = group.groupby("date").size().to_dict()

        # Today's jobs
        today = datetime.now().strftime("%Y-%m-%d")
        today_jobs = daily_counts.get(today, 0)

        # Window stats
        total_jobs = len(group)
        days_active = len(daily_counts)

        # Get all dates in window for proper stats
        all_dates = sorted(daily_counts.keys())
        if len(all_dates) >= 2:
            date_range = pd.date_range(start=all_dates[0], end=all_dates[-1], freq="D")
            full_series = pd.Series(
                [daily_counts.get(d.strftime("%Y-%m-%d"), 0) for d in date_range],
                index=date_range,
            )
            avg_daily = float(full_series.mean())
            std_daily = float(full_series.std()) if len(full_series) > 1 else 0.0
        else:
            avg_daily = float(total_jobs)
            std_daily = 0.0

        # IT ratio
        all_company_jobs = df[df["company"] == company]
        it_count = len(group)
        total_count = len(all_company_jobs)
        it_ratio = it_count / total_count if total_count > 0 else 0

        # Seniority ratio
        seniority_counts = group["seniority"].value_counts().to_dict()
        senior_count = seniority_counts.get("senior", 0)
        total_classified = sum(seniority_counts.values())
        seniority_ratio = senior_count / total_classified if total_classified > 0 else 0

        # Role diversity
        role_diversity = group["role_category"].nunique()

        # Role categories detail
        role_categories = group["role_category"].value_counts().to_dict()

        # Salary stats (only visible salary, convert to USD)
        salaries = []
        for _, row in group.iterrows():
            sal = row.get("salary", {})
            if isinstance(sal, dict) and sal.get("type") in ("range", "single", "up_to"):
                val = sal.get("max") or sal.get("min")
                currency = sal.get("currency", "USD")
                if val and currency == "VND":
                    val = val / 25000  # ~exchange rate
                if val:
                    salaries.append(val)

        avg_salary = float(np.mean(salaries)) if salaries else None
        max_salary = float(max(salaries)) if salaries else None

        # Job titles
        job_titles = group["title"].tolist()

        companies[company] = {
            "company": company,
            "daily_counts": daily_counts,
            "total_jobs_today": today_jobs,
            "total_jobs_window": total_jobs,
            "avg_daily": avg_daily,
            "std_daily": std_daily,
            "days_active": days_active,
            "it_ratio": it_ratio,
            "seniority_ratio": seniority_ratio,
            "role_diversity": role_diversity,
            "role_categories": role_categories,
            "avg_salary": avg_salary,
            "max_salary": max_salary,
            "job_titles": job_titles,
            "it_worthy": it_ratio >= IT_RATIO_THRESHOLD,
        }

    return companies


def get_todays_company_jobs(df: pd.DataFrame, company: str) -> list[dict]:
    """Lấy danh sách jobs hôm nay của 1 công ty."""
    today = datetime.now().strftime("%Y-%m-%d")
    mask = (df["company"] == company) & (df["date"] == today)
    return df[mask].to_dict("records")


def is_new_company(company_history: dict, min_days: int = MIN_HISTORY_DAYS) -> bool:
    """
    Kiểm tra công ty có phải "mới" không (chưa đủ history để dùng Z-Score).

    Args:
        company_history: dict từ get_company_history()
        min_days: Số ngày active tối thiểu để không tính là "mới"

    Returns:
        True nếu công ty có < min_days ngày active.
    """
    return company_history.get("days_active", 0) < min_days


# ─── CLI Test ───────────────────────────────────────────

def main():
    """Test storage module."""
    print("Loading history...")
    df = load_history()
    print(f"  Total jobs in window: {len(df)}")
    print(f"  IT jobs: {df['is_it'].sum() if 'is_it' in df.columns else 'N/A'}")
    print(f"  Date range: {df['date'].min() if not df.empty else 'N/A'} → {df['date'].max() if not df.empty else 'N/A'}")

    companies = get_company_history(df)
    print(f"\n  Companies with IT jobs: {len(companies)}")

    # Show top 5 by today's jobs
    sorted_companies = sorted(
        companies.items(),
        key=lambda x: (x[1]["total_jobs_today"], x[1]["total_jobs_window"]),
        reverse=True,
    )
    print("\n  Top 5 companies (by today's jobs):")
    for name, info in sorted_companies[:5]:
        is_new = is_new_company(info)
        new_tag = " 🆕 NEW" if is_new else ""
        print(f"    {name}: {info['total_jobs_today']} today, "
              f"{info['total_jobs_window']} total in {info['days_active']} days, "
              f"IT ratio: {info['it_ratio']:.0%}{new_tag}")
        if info.get("role_categories"):
            roles = ", ".join(f"{k}({v})" for k, v in sorted(info["role_categories"].items(), key=lambda x: -x[1])[:5])
            print(f"      Roles: {roles}")
        if info.get("avg_salary"):
            print(f"      Avg salary: ${info['avg_salary']:,.0f}")


if __name__ == "__main__":
    main()
