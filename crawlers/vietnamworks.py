#!/usr/bin/env python3
"""
VietnamWorks Crawler — Thu thập toàn bộ IT job posting mới từ VietnamWorks.

VietnamWorks là site đa ngành, có REST API trả về JSON. Dùng industryV3Ids=[25]
để filter ngành IT Software/SaaS. API không hỗ trợ sort theo ngày đăng mới nhất
nên crawl N trang đầu và filter by approvedOn client-side.

Usage:
    python crawlers/vietnamworks.py                    # crawl jobs 24h qua
    python crawlers/vietnamworks.py --days 3            # crawl 3 ngày qua
    python crawlers/vietnamworks.py --max-pages 30      # giới hạn 30 trang
    python crawlers/vietnamworks.py --dry-run            # test, không lưu
"""

import argparse
import json
import os
import re
import time
from datetime import datetime, timedelta
from pathlib import Path
from typing import Optional

import requests

# ─── CONFIG ─────────────────────────────────────────────

API_URL = "https://ms.vietnamworks.com/job-search/v1.0/search"
SITE_URL = "https://www.vietnamworks.com"
OUTPUT_DIR = Path(__file__).resolve().parent.parent / "data" / "raw"

REQUEST_TIMEOUT = 15  # seconds
PAGE_DELAY = 0.5       # seconds — delay giữa các trang (rate limiting)

# Industry IDs from VietnamWorks
IT_INDUSTRY_IDS = [25]  # 25 = IT Software/SaaS

# Keywords để search IT jobs — mỗi keyword cho 1 result set nhỏ hơn, dễ crawl hết
IT_KEYWORDS = [
    "software", "developer", "engineer", "IT", "data",
    "devops", "cloud", "mobile", "web", "frontend",
    "backend", "fullstack", "QA", "tester", "AI",
    "network", "security", "system", "lập trình", "kiểm thử",
]


# ─── SESSION SETUP ──────────────────────────────────────

def make_session() -> requests.Session:
    """Tạo requests session với headers giả lập browser."""
    s = requests.Session()
    s.headers.update({
        "User-Agent": (
            "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
            "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36"
        ),
        "Content-Type": "application/json",
        "Origin": SITE_URL,
        "Referer": f"{SITE_URL}/viec-lam",
    })
    return s


# ─── HELPERS ────────────────────────────────────────────

def parse_approved_date(approved_on: str) -> Optional[datetime]:
    """
    Parse ISO 8601 date từ API VietnamWorks.

    Input:  "2026-07-30T13:59:34+07:00"
    Output: datetime object, hoặc None.
    """
    if not approved_on:
        return None
    try:
        # Python 3.7+ can parse ISO 8601 with timezone
        return datetime.fromisoformat(approved_on)
    except (ValueError, TypeError):
        return None


def parse_salary_vnw(job: dict) -> dict:
    """
    Parse salary từ VietnamWorks job object.

    VietnamWorks có các field:
      - salaryMin, salaryMax: số
      - salaryCurrency: "VND" | "USD"
      - prettySalary: text hiển thị ("15tr-28tr ₫/tháng", "Thương lượng")
      - isSalaryVisible: boolean

    Returns:
        dict: {"type", "min", "max", "currency", "text"}
    """
    if not job.get("isSalaryVisible") or not job.get("prettySalary"):
        return {
            "type": "hidden" if not job.get("isSalaryVisible") else "unknown",
            "text": job.get("prettySalary", ""),
        }

    text = job.get("prettySalary", "").strip()

    # Negotiable
    if any(kw in text.lower() for kw in [
        "thương lượng", "thuong luong", "negotiable", "competitive",
        "thỏa thuận", "thoa thuan",
    ]):
        return {"type": "negotiable", "text": text}

    # Có salaryMin/salaryMax
    smin = job.get("salaryMin")
    smax = job.get("salaryMax")
    currency = (job.get("salaryCurrency") or "VND").upper()

    if smin is not None and smax is not None:
        return {
            "type": "range",
            "min": float(smin),
            "max": float(smax),
            "currency": currency,
            "text": text,
        }

    # Up to: "Up to 30tr"
    up_to = re.search(r'(?:up\s*to|tối đa|toi da)\s*\$?\s*([\d,]+)', text, re.IGNORECASE)
    if up_to:
        return {
            "type": "up_to",
            "max": float(up_to.group(1).replace(",", "")),
            "currency": currency,
            "text": text,
        }

    # Try regex parse: "15tr-28tr ₫/tháng" hoặc "$2000 - $4000"
    range_match = re.search(
        r'([\d,]+)\s*(?:tr|triệu|million)?\s*[-–—to]+\s*([\d,]+)\s*(?:tr|triệu|million)?',
        text, re.IGNORECASE,
    )
    if range_match:
        v1 = float(range_match.group(1).replace(",", ""))
        v2 = float(range_match.group(2).replace(",", ""))
        # VND salaries are often in "triệu" — multiply by 1e6
        if "tr" in text.lower() or "triệu" in text.lower() or currency == "VND":
            v1 *= 1_000_000
            v2 *= 1_000_000
        return {"type": "range", "min": v1, "max": v2, "currency": currency, "text": text}

    # Single value
    single = re.search(r'\$?\s*([\d,]+)', text)
    if single:
        val = float(single.group(1).replace(",", ""))
        return {"type": "single", "min": val, "max": val, "currency": currency, "text": text}

    return {"type": "unknown", "text": text}


def extract_cities(locations: list[dict]) -> list[str]:
    """
    Trích xuất danh sách thành phố từ workingLocations.

    Input:  [{"cityName": "Ha Noi", "cityNameVI": "Hà Nội"}, ...]
    Output: ["Ha Noi", "Ho Chi Minh"]
    """
    cities = []
    seen = set()
    for loc in (locations or []):
        name = loc.get("cityName", "")
        if name and name not in seen:
            cities.append(name)
            seen.add(name)
    return cities


def extract_skill_names(skills: list[dict]) -> list[str]:
    """
    Trích xuất tên skills từ array.

    Input:  [{"skillId": 1, "skillName": "Python"}, ...]
    Output: ["Python", "React"]
    """
    return [s.get("skillName", "") for s in (skills or []) if s.get("skillName")]


def extract_industry_names(industries: list[dict]) -> list[str]:
    """Trích xuất tên ngành từ industriesV3."""
    return [i.get("industryV3Name", "") for i in (industries or []) if i.get("industryV3Name")]


# ─── CRAWLER ────────────────────────────────────────────

def parse_job(job: dict) -> Optional[dict]:
    """
    Parse 1 job từ VietnamWorks API thành structured dict chuẩn.

    Args:
        job: Raw job dict từ API response.

    Returns:
        Parsed job dict với schema thống nhất (dùng chung cho cả pipeline).
    """
    try:
        job_id = str(job.get("jobId", ""))
        title = job.get("jobTitle", "").strip()
        company = job.get("companyName", "").strip()
        company_id = job.get("companyId")

        # Date
        approved_on = job.get("approvedOn", "")
        posted_date = parse_approved_date(approved_on)
        approved_on_text = job.get("approvedOnText", "")

        # Salary
        salary = parse_salary_vnw(job)

        # Location
        locations = job.get("workingLocations", [])
        cities = extract_cities(locations)

        # Skills (có thể là array of objects hoặc array of strings)
        skills_raw = job.get("skills", [])
        if skills_raw and isinstance(skills_raw[0], dict):
            skills = extract_skill_names(skills_raw)
        else:
            skills = [s for s in skills_raw if isinstance(s, str)]

        # Industries
        industries = extract_industry_names(job.get("industriesV3", []))

        # Benefits
        benefits = job.get("benefits", [])
        if isinstance(benefits, str):
            benefits = [b.strip() for b in benefits.split("\n") if b.strip()]
        elif not isinstance(benefits, list):
            benefits = []

        # Job level
        job_level = job.get("jobLevel", "") or job.get("jobLevelVI", "")

        # Company info
        company_size = job.get("companySize", "") or job.get("companySizeVI", "")

        # Job URL
        job_url = job.get("jobUrl", "")
        if job_url and not job_url.startswith("http"):
            job_url = SITE_URL + job_url

        # Number of recruits
        num_recruits = job.get("numberOfRecruits")

        return {
            "job_id": job_id,
            "title": title,
            "company": company,
            "company_id": company_id,
            "company_size": company_size,
            "salary": salary,
            "salary_raw": job.get("prettySalary", ""),
            "cities": cities,
            "skills": skills,
            "industries": industries,
            "job_level": job_level,
            "benefits": benefits,
            "num_recruits": num_recruits,
            "posted_text": approved_on_text,
            "posted_date": posted_date.isoformat() if posted_date else None,
            "url": job_url,
            "source": "vietnamworks",
            "crawled_at": datetime.now().isoformat(),
        }

    except Exception as e:
        print(f"  ⚠️  Lỗi parse job {job.get('jobId', '?')}: {e}")
        return None


def crawl_vietnamworks(
    max_days: int = 1,
    max_pages_per_query: int = 5,
) -> list[dict]:
    """
    Crawl VietnamWorks IT jobs sử dụng multi-keyword search.

    Vì API không hỗ trợ sort theo ngày đăng, ta dùng nhiều keyword
    để thu hẹp result set và crawl toàn bộ (hoặc max_pages_per_query trang)
    cho mỗi keyword. Filter client-side theo approvedOn.

    Args:
        max_days: Chỉ lấy job đăng trong max_days ngày qua.
        max_pages_per_query: Số trang tối đa cho mỗi keyword query.

    Returns:
        List of parsed job dicts.
    """
    all_jobs = []
    seen_ids = set()
    cutoff_date = datetime.now().astimezone() - timedelta(days=max_days)
    session = make_session()
    total_pages_limit = max_pages_per_query * len(IT_KEYWORDS)

    print(f"\n{'=' * 60}")
    print(f"🔍 VietnamWorks Crawler — {datetime.now().strftime('%Y-%m-%d %H:%M')}")
    print(f"   Filter: IT jobs, đăng trong {max_days} ngày qua")
    print(f"   Cutoff: {cutoff_date.strftime('%Y-%m-%d %H:%M')}")
    print(f"   Keywords: {len(IT_KEYWORDS)} từ khóa × {max_pages_per_query} trang = tối đa {total_pages_limit} trang")
    print(f"{'=' * 60}\n")

    skipped_old_total = 0

    for kw_idx, keyword in enumerate(IT_KEYWORDS, 1):
        page_num = 1
        old_job_streak = 0
        kw_jobs = 0

        while page_num <= max_pages_per_query:
            payload = {
                "query": keyword,
                "page": page_num,
                "pageSize": 10,
                "functions": [],
            }

            try:
                resp = session.post(API_URL, json=payload, timeout=REQUEST_TIMEOUT)
                resp.raise_for_status()
                data = resp.json()
            except requests.RequestException as e:
                print(f"  ⚠️  Lỗi [{keyword}] trang {page_num}: {e}")
                break

            if data.get("meta", {}).get("code") != 200:
                break

            jobs_data = data.get("data", [])
            if not jobs_data:
                break

            new_on_page = 0
            skipped_old = 0

            for job in jobs_data:
                job_id = str(job.get("jobId", ""))
                if not job_id or job_id in seen_ids:
                    continue
                seen_ids.add(job_id)

                # Filter theo thời gian
                approved_on = job.get("approvedOn", "")
                if approved_on:
                    posted = parse_approved_date(approved_on)
                    if posted and posted < cutoff_date:
                        skipped_old += 1
                        continue

                parsed = parse_job(job)
                if parsed and parsed["title"]:
                    all_jobs.append(parsed)
                    new_on_page += 1
                    kw_jobs += 1

            skipped_old_total += skipped_old

            # In chi tiết cho keyword đầu tiên hoặc khi tìm thấy job mới
            if kw_idx == 1 or new_on_page > 0:
                for j in all_jobs[-min(new_on_page, 2):]:
                    print(f"   📌 [{j['company'] or '?'}] {j['title'][:70]}")
                    salary_info = j.get("salary_raw") or j.get("salary", {}).get("text", "")
                    if salary_info:
                        print(f"      💰 {salary_info[:60]}")
                    if j.get("cities"):
                        print(f"      📍 {', '.join(j['cities'])}")
                    print(f"      ⏰ {j.get('posted_text', '')}")
                    print(f"      🔍 keyword: '{keyword}'")

            # Dừng sớm nếu liên tiếp không có job mới
            if new_on_page == 0 and skipped_old > 0:
                old_job_streak += 1
                if old_job_streak >= 3:
                    break
            else:
                old_job_streak = 0

            page_num += 1
            time.sleep(PAGE_DELAY)

        if kw_jobs > 0:
            print(f"   [{kw_idx}/{len(IT_KEYWORDS)}] '{keyword}': {kw_jobs} new jobs (tổng: {len(all_jobs)})")

    session.close()
    print(f"\n   📊 Tổng: {len(all_jobs)} jobs mới, bỏ qua {skipped_old_total} job cũ")
    return all_jobs


# ─── OUTPUT ─────────────────────────────────────────────

def save_results(jobs: list[dict]):
    """Lưu kết quả vào file JSON theo ngày."""
    today = datetime.now().strftime("%Y-%m-%d")
    output_path = OUTPUT_DIR / today / "vietnamworks.json"
    output_path.parent.mkdir(parents=True, exist_ok=True)

    with open(output_path, "w", encoding="utf-8") as f:
        json.dump(jobs, f, indent=2, ensure_ascii=False)

    print(f"💾 Đã lưu {len(jobs)} jobs → {output_path}")


def print_summary(jobs: list[dict]):
    """In tóm tắt kết quả."""
    if not jobs:
        print("\n❌ Không tìm thấy job nào.")
        return

    from collections import Counter
    company_counts = Counter(j["company"] for j in jobs if j["company"])

    print(f"\n{'=' * 60}")
    print(f"📊 TỔNG KẾT")
    print(f"{'=' * 60}")
    print(f"  Tổng jobs:           {len(jobs)}")
    print(f"  Số công ty:          {len(company_counts)}")
    print(f"  Job có salary public:{sum(1 for j in jobs if j['salary']['type'] in ('range', 'single', 'up_to'))}")

    print(f"\n  Top 10 công ty:")
    for i, (company, count) in enumerate(company_counts.most_common(10), 1):
        print(f"  {i:2}. {company:<40} {count:3} jobs")

    print(f"\n  🆕 Đáng chú ý (công ty có ≥5 jobs hôm nay):")
    high_volume = [(c, n) for c, n in company_counts.items() if n >= 5]
    for c, n in sorted(high_volume, key=lambda x: -x[1]):
        print(f"     · {c}: {n} jobs")

    print(f"{'=' * 60}\n")


# ─── CLI ────────────────────────────────────────────────

def main():
    parser = argparse.ArgumentParser(
        description="VietnamWorks IT Job Crawler — Hiring Watchdog",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Ví dụ:
  python crawlers/vietnamworks.py                  # Crawl 24h qua
  python crawlers/vietnamworks.py --days 3          # Crawl 3 ngày qua
  python crawlers/vietnamworks.py --max-pages 30    # Chỉ 30 trang đầu
  python crawlers/vietnamworks.py --dry-run          # Test, không lưu
        """,
    )
    parser.add_argument("--days", type=int, default=1, help="Số ngày để filter (default: 1)")
    parser.add_argument("--max-pages", type=int, default=5, help="Số trang tối đa mỗi keyword (default: 5)")
    parser.add_argument("--dry-run", action="store_true", help="Chạy thử, không lưu file")

    args = parser.parse_args()

    start = time.time()
    jobs = crawl_vietnamworks(max_days=args.days, max_pages_per_query=args.max_pages)
    elapsed = time.time() - start

    print_summary(jobs)
    print(f"⏱️  Hoàn thành trong {elapsed:.1f}s")

    if not args.dry_run:
        save_results(jobs)


if __name__ == "__main__":
    main()
