#!/usr/bin/env python3
"""
Pipeline — Gộp dữ liệu từ nhiều nguồn crawl, normalize schema, lưu output.

Usage:
    python pipeline/merge.py                           # merge today's data
    python pipeline/merge.py --date 2026-08-02          # merge specific date
    python pipeline/merge.py --dry-run                  # test, không lưu
"""

import argparse
import json
import os
import sys
from datetime import datetime
from pathlib import Path
from typing import Optional

# ─── CONFIG ─────────────────────────────────────────────

ROOT_DIR = Path(__file__).resolve().parent.parent
RAW_DIR = ROOT_DIR / "data" / "raw"
PROCESSED_DIR = ROOT_DIR / "data" / "processed"

# ─── SCHEMA NORMALIZATION ───────────────────────────────

# Chuẩn hóa tên thành phố
CITY_ALIASES = {
    "ho chi minh": "Ho Chi Minh",
    "hồ chí minh": "Ho Chi Minh",
    "hcm": "Ho Chi Minh",
    "saigon": "Ho Chi Minh",
    "sài gòn": "Ho Chi Minh",
    "ha noi": "Ha Noi",
    "hà nội": "Ha Noi",
    "hanoi": "Ha Noi",
    "da nang": "Da Nang",
    "đà nẵng": "Da Nang",
    "danang": "Da Nang",
}


def normalize_city(city: str) -> str:
    """Chuẩn hóa tên thành phố."""
    return CITY_ALIASES.get(city.strip().lower(), city.strip())


def normalize_company(name: str) -> str:
    """
    Chuẩn hóa tên công ty để dedup chính xác hơn.

    - Bỏ khoảng trắng thừa
    - Viết hoa chữ cái đầu
    - Bỏ các suffix phổ biến: "Co., Ltd", "JSC", v.v.
    """
    if not name:
        return ""
    name = name.strip()
    # Remove common legal suffixes for better matching
    for suffix in [
        "Company Limited", "Co., Ltd", "Co. Ltd", "Co.,Ltd", "Co,.Ltd",
        "Corporation", "Corp.", "Corp", "Incorporated", "Inc.", "Inc",
        "Joint Stock Company", "JSC", "J.S.C",
        "Limited Liability Company", "LLC", "L.L.C",
        "Công ty TNHH", "Công Ty TNHH", "Cty TNHH",
        "Công ty Cổ phần", "Công Ty Cổ Phần", "Cty CP",
        "Công ty CP", "CTCP",
        "Tập đoàn", "Group",
    ]:
        # Only remove if it's the last part of the name
        if name.lower().endswith(suffix.lower()):
            name = name[: -len(suffix)].strip()
            # Remove trailing comma
            if name.endswith(","):
                name = name[:-1].strip()
    return name


def normalize_job(job: dict, source: str) -> dict:
    """
    Chuẩn hóa 1 job từ bất kỳ nguồn nào về schema thống nhất.

    Schema output:
      {
        "job_id": str,           # "itviec:12345" hoặc "vietnamworks:2073757"
        "title": str,
        "company": str,
        "company_normalized": str,  # Dùng cho dedup
        "salary": dict,          # {type, min, max, currency, text}
        "cities": [str],         # Danh sách thành phố đã normalize
        "skills": [str],
        "posted_date": str,      # ISO datetime
        "url": str,
        "source": str,           # "itviec" | "vietnamworks"
        ... các field optional khác
      }
    """
    # Normalize cities
    raw_cities = []
    city_field = job.get("city") or job.get("cities") or []
    if isinstance(city_field, str):
        raw_cities = [city_field] if city_field else []
    else:
        raw_cities = city_field
    cities = [normalize_city(c) for c in raw_cities if c]

    # Normalize company
    company = job.get("company", "").strip()
    company_normalized = normalize_company(company)

    # Build unified job
    unified = {
        "job_id": f"{source}:{job.get('job_id', '')}",
        "title": job.get("title", "").strip(),
        "company": company,
        "company_normalized": company_normalized,
        "salary": job.get("salary", {}),
        "cities": cities,
        "skills": job.get("skills", []),
        "posted_date": job.get("posted_date"),
        "url": job.get("url", ""),
        "source": source,
        "crawled_at": job.get("crawled_at", datetime.now().isoformat()),
    }

    # Optional fields — chỉ thêm nếu có giá trị
    optional_fields = [
        "company_id", "company_size", "job_level",
        "benefits", "industries", "hot_label", "num_recruits",
        "location", "category", "salary_raw", "posted_text",
    ]
    for field in optional_fields:
        val = job.get(field)
        if val:
            unified[field] = val

    return unified


# ─── MERGE ──────────────────────────────────────────────

def load_raw_jobs(date_str: str) -> list[dict]:
    """
    Load tất cả raw jobs từ các nguồn cho 1 ngày.

    Args:
        date_str: "YYYY-MM-DD"

    Returns:
        List of normalized job dicts.
    """
    date_dir = RAW_DIR / date_str
    if not date_dir.exists():
        print(f"❌ Không tìm thấy thư mục {date_dir}")
        return []

    all_jobs = []

    # ITViec
    itviec_file = date_dir / "itviec.json"
    if itviec_file.exists():
        with open(itviec_file, "r", encoding="utf-8") as f:
            itviec_jobs = json.load(f)
        for job in itviec_jobs:
            normalized = normalize_job(job, "itviec")
            all_jobs.append(normalized)
        print(f"   📥 ITViec: {len(itviec_jobs)} jobs")

    # VietnamWorks
    vnw_file = date_dir / "vietnamworks.json"
    if vnw_file.exists():
        with open(vnw_file, "r", encoding="utf-8") as f:
            vnw_jobs = json.load(f)
        for job in vnw_jobs:
            normalized = normalize_job(job, "vietnamworks")
            all_jobs.append(normalized)
        print(f"   📥 VietnamWorks: {len(vnw_jobs)} jobs")

    return all_jobs


def merge_sources(date_str: str) -> list[dict]:
    """
    Entry point: load + normalize + dedup tất cả sources cho 1 ngày.

    Returns:
        List of unique, normalized job dicts.
    """
    print(f"\n{'=' * 60}")
    print(f"🔀 Merge Pipeline — {date_str}")
    print(f"{'=' * 60}\n")

    jobs = load_raw_jobs(date_str)
    if not jobs:
        print("   ⚠️  Không có data từ nguồn nào.")
        return []

    print(f"   📊 Tổng raw jobs: {len(jobs)}")

    # Dedup
    jobs = deduplicate(jobs)
    print(f"   📊 Sau dedup: {len(jobs)} jobs")

    return jobs


# ─── DEDUP ──────────────────────────────────────────────

def _title_similarity(t1: str, t2: str) -> float:
    """
    Tính similarity giữa 2 job title.

    Dùng token overlap ratio (đơn giản, nhanh).
    """
    if t1 == t2:
        return 1.0

    # Tokenize: lowercase, split by non-word
    import re
    tokens1 = set(re.findall(r'\w+', t1.lower()))
    tokens2 = set(re.findall(r'\w+', t2.lower()))

    if not tokens1 or not tokens2:
        return 0.0

    intersection = tokens1 & tokens2
    union = tokens1 | tokens2
    return len(intersection) / len(union)


def deduplicate(jobs: list[dict]) -> list[dict]:
    """
    Loại bỏ job trùng lặp (cùng company + similar title).

    So sánh tất cả các cặp job, merge nếu:
    - Cùng company_normalized (exact match) HOẶC company gốc fuzzy match cao
    - Title similarity >= 0.6

    Khi merge: giữ job có nhiều thông tin hơn (nhiều field không rỗng).
    """
    if len(jobs) <= 1:
        return jobs

    # Ưu tiên merge các job có source khác nhau
    duplicates = {}  # canonical_idx -> [duplicate_indices]
    processed = set()

    for i in range(len(jobs)):
        if i in processed:
            continue

        for j in range(i + 1, len(jobs)):
            if j in processed:
                continue

            job_i = jobs[i]
            job_j = jobs[j]

            # Check company match
            company_match = (
                job_i.get("company_normalized", "").lower()
                == job_j.get("company_normalized", "").lower()
            )
            if not company_match:
                # Thử exact match trên company gốc
                company_match = (
                    job_i.get("company", "").strip().lower()
                    == job_j.get("company", "").strip().lower()
                )

            if not company_match:
                continue

            # Check title similarity
            t1 = job_i.get("title", "")
            t2 = job_j.get("title", "")
            sim = _title_similarity(t1, t2)

            if sim >= 0.6:
                # Same job — mark as duplicate
                # Giữ job có nhiều field populated hơn
                if _job_richness(job_j) > _job_richness(job_i):
                    # job_j better — keep j, mark i as duplicate
                    group_key = j
                    if i not in duplicates.get(group_key, []):
                        duplicates.setdefault(group_key, []).append(i)
                        processed.add(i)
                else:
                    # job_i better — keep i, mark j as duplicate
                    group_key = i
                    if j not in duplicates.get(group_key, []):
                        duplicates.setdefault(group_key, []).append(j)
                        processed.add(j)

    # Build result: all non-duplicate jobs
    duplicate_indices = set()
    for indices in duplicates.values():
        duplicate_indices.update(indices)

    result = [job for idx, job in enumerate(jobs) if idx not in duplicate_indices]

    duplicate_count = len(jobs) - len(result)
    if duplicate_count > 0:
        print(f"   🔄 Dedup: loại {duplicate_count} job trùng")

    return result


def _job_richness(job: dict) -> int:
    """Đếm số field có thông tin (không rỗng) để so sánh chất lượng."""
    score = 0
    for key, val in job.items():
        if val:
            if isinstance(val, list):
                score += len(val)
            elif isinstance(val, dict):
                # Salary dict
                if val.get("type") not in ("unknown", "hidden", None):
                    score += 3
                if val.get("min"):
                    score += 1
                if val.get("max"):
                    score += 1
            else:
                score += 1
    return score


# ─── SAVE ───────────────────────────────────────────────

def save_processed(jobs: list[dict], date_str: str):
    """Lưu kết quả merge + dedup."""
    output_path = PROCESSED_DIR / f"{date_str}.json"
    output_path.parent.mkdir(parents=True, exist_ok=True)

    with open(output_path, "w", encoding="utf-8") as f:
        json.dump(jobs, f, indent=2, ensure_ascii=False)

    print(f"\n💾 Đã lưu {len(jobs)} jobs → {output_path}")


# ─── CLI ────────────────────────────────────────────────

def main():
    parser = argparse.ArgumentParser(
        description="Merge + Dedup Pipeline — Hiring Watchdog",
    )
    parser.add_argument("--date", type=str, default=None,
                        help="Ngày cần merge (YYYY-MM-DD, default: hôm nay)")
    parser.add_argument("--dry-run", action="store_true",
                        help="Chạy thử, không lưu file")

    args = parser.parse_args()

    date_str = args.date or datetime.now().strftime("%Y-%m-%d")

    jobs = merge_sources(date_str)

    if not jobs:
        print("\n❌ Không có job nào để merge.")
        sys.exit(1)

    # Summary
    from collections import Counter
    source_counts = Counter(j["source"] for j in jobs)
    company_counts = Counter(j["company"] for j in jobs if j["company"])

    print(f"\n{'=' * 60}")
    print(f"📊 KẾT QUẢ MERGE")
    print(f"{'=' * 60}")
    print(f"  Tổng jobs unique:   {len(jobs)}")
    print(f"  Nguồn: {dict(source_counts)}")
    print(f"  Số công ty:         {len(company_counts)}")
    print(f"  Có salary:          {sum(1 for j in jobs if j['salary'].get('type') in ('range', 'single', 'up_to'))}")

    if company_counts:
        print(f"\n  Top 5 công ty:")
        for company, count in company_counts.most_common(5):
            print(f"    {company:<45} {count} jobs")

    print(f"{'=' * 60}\n")

    if not args.dry_run:
        save_processed(jobs, date_str)


if __name__ == "__main__":
    main()
