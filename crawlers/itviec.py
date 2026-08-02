#!/usr/bin/env python3
"""
ITViec Crawler — Thu thập toàn bộ job posting mới từ ITviec.com.

ITViec là site 100% IT jobs. Trang web sử dụng Rails + Turbo, có API trả về
HTML đã render (JSON với key `jobs_html`). Không cần dùng Playwright.

Usage:
    python crawlers/itviec.py                         # crawl jobs 24h qua
    python crawlers/itviec.py --days 3                # crawl 3 ngày qua
    python crawlers/itviec.py --max-pages 5           # giới hạn 5 trang
    python crawlers/itviec.py --dry-run               # test, không lưu
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
from bs4 import BeautifulSoup

# ─── CONFIG ─────────────────────────────────────────────

BASE_URL = "https://itviec.com"
LISTING_URL = f"{BASE_URL}/it-jobs"
OUTPUT_DIR = Path(__file__).resolve().parent.parent / "data" / "raw"

REQUEST_TIMEOUT = 15  # seconds
PAGE_DELAY = 0.5      # seconds — delay giữa các trang (rate limiting)


# ─── SESSION SETUP ──────────────────────────────────────

def make_session() -> requests.Session:
    """Tạo requests session với headers giả lập browser."""
    s = requests.Session()
    s.headers.update({
        "User-Agent": (
            "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
            "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36"
        ),
    })
    return s


# ─── HELPERS ────────────────────────────────────────────

def parse_posted_time(text: str) -> Optional[datetime]:
    """
    Parse thời gian đăng bài.

    Input:  "Posted 21 minutes ago" / "Posted 3 hours ago" /
            "Posted 1 day ago" / "Posted 2 weeks ago"
    Output: datetime object, hoặc None.
    """
    if not text:
        return None

    text = text.strip()

    # Strip "Posted" prefix
    text_clean = re.sub(r'^Posted\s*', '', text, flags=re.IGNORECASE).strip()

    match = re.search(r'(\d+)\s+(minute|hour|day|week|month)s?\s+ago', text_clean, re.IGNORECASE)
    if not match:
        return None

    amount = int(match.group(1))
    unit = match.group(2).lower()
    now = datetime.now()

    if unit == "minute":
        return now - timedelta(minutes=amount)
    elif unit == "hour":
        return now - timedelta(hours=amount)
    elif unit == "day":
        return now - timedelta(days=amount)
    elif unit == "week":
        return now - timedelta(weeks=amount)
    elif unit == "month":
        return now - timedelta(days=amount * 30)

    return None


def parse_salary(text: str) -> dict:
    """
    Parse salary text thành structured dict.

    Input:  "Sign in to view salary" / "$2000 - $4000" /
            "Negotiable" / "Up to $3000" / "You'll love it"
    """
    if not text:
        return {"type": "unknown", "text": ""}

    text = text.strip()

    # Hidden salary
    if "sign in" in text.lower():
        return {"type": "hidden", "text": text}

    # Negotiable
    if any(kw in text.lower() for kw in [
        "negotiable", "thỏa thuận", "thoa thuan",
        "competitive", "you'll love", "thuong luong", "thương lượng",
    ]):
        return {"type": "negotiable", "text": text}

    # Range: "$2000 - $4000" hoặc "$2,000 - $4,000 USD"
    range_match = re.search(
        r'\$?\s*([\d,]+)\s*(?:USD|VND)?\s*[-–—to]+\s*\$?\s*([\d,]+)\s*(USD|VND)?',
        text, re.IGNORECASE,
    )
    if range_match:
        return {
            "type": "range",
            "min": float(range_match.group(1).replace(",", "")),
            "max": float(range_match.group(2).replace(",", "")),
            "currency": (range_match.group(3) or "USD").upper(),
            "text": text,
        }

    # "Up to $3000" / "Tối đa $3000"
    up_to = re.search(r'(?:up\s*to|tối đa|toi da)\s*\$?\s*([\d,]+)', text, re.IGNORECASE)
    if up_to:
        return {
            "type": "up_to",
            "max": float(up_to.group(1).replace(",", "")),
            "currency": "USD",
            "text": text,
        }

    # Single: "$3000" / "3000 USD"
    single = re.search(r'\$?\s*([\d,]+)\s*(USD|VND)?', text, re.IGNORECASE)
    if single:
        val = float(single.group(1).replace(",", ""))
        currency = "VND" if (single.group(2) or "").upper() == "VND" else "USD"
        return {"type": "single", "min": val, "max": val, "currency": currency, "text": text}

    return {"type": "unknown", "text": text}


# ─── CRAWLER ────────────────────────────────────────────

def fetch_page(page_num: int, session: requests.Session) -> Optional[dict]:
    """
    Gọi API ITViec để lấy 1 trang kết quả.

    Returns:
        dict với các key: jobs_html, pagination_html, headline_result_html, ...
        None nếu thất bại.
    """
    url = f"{LISTING_URL}?page={page_num}&query=&source=search_job"
    headers = {
        "Accept": "text/vnd.turbo-stream.html, text/html, application/xhtml+xml",
        "X-Requested-With": "XMLHttpRequest",
        "Referer": LISTING_URL,
    }

    try:
        resp = session.get(url, headers=headers, timeout=REQUEST_TIMEOUT)
        resp.raise_for_status()
        return resp.json()
    except requests.RequestException as e:
        print(f"  ⚠️  Lỗi khi fetch trang {page_num}: {e}")
        return None


def parse_job_card(card: BeautifulSoup) -> Optional[dict]:
    """
    Parse 1 job card HTML thành structured dict.

    Cấu trúc job card (div.job-card):
      - span.small-text.text-dark-grey          → Posted time
      - h3 > a[href*="/it-jobs/"]              → Job title + URL
      - a[href*="/companies/"]                 → Company (logo link)
      - text "Sign in to view salary" hoặc $X  → Salary
      - a[href*="click_source=Skill+tag"]     → Skills
      - .ilabel / .ilabel-danger               → Hot label
      - text "At office" / "Remote" / ...      → Location
    """
    try:
        # ── Posted Time ──
        posted_el = card.select_one("span.small-text.text-dark-grey")
        posted_text = posted_el.get_text(strip=True) if posted_el else ""
        posted_date = parse_posted_time(posted_text)

        # ── Job Title + URL ──
        title_el = card.select_one("h3 a") or card.select_one("a[class*='text-it-black']")
        title = title_el.get_text(strip=True) if title_el else ""
        job_url = ""
        if title_el:
            href = title_el.get("href", "")
            job_url = href if href.startswith("http") else BASE_URL + href
            # Strip tracking params
            job_url = job_url.split("?")[0] if "?" in job_url else job_url
            # Normalize: remove /content suffix
            job_url = re.sub(r'/content$', '', job_url)

        # ── Job Slug/ID ──
        slug_match = re.search(r'/it-jobs/([^/?]+)', job_url)
        job_slug = slug_match.group(1) if slug_match else None
        # ID is typically the last part of the slug: "it-infrastructure-expert-one-mount-group-0157"
        id_match = re.search(r'-(\d+)$', job_slug) if job_slug else None
        job_id = id_match.group(1) if id_match else None

        # ── Company ──
        # Cấu trúc DOM:
        #   <div class="imy-3 d-flex align-items-center">    ← container
        #     <a class="logo-employer-card" title="SLOGAN">  ← logo ảnh (không text)
        #       <picture><img></picture>
        #     </a>
        #     [TEXT NODE: tên công ty thật]                    ← KHÔNG nằm trong thẻ <a>
        #   </div>
        company = ""
        company_container = card.select_one("div.imy-3.d-flex.align-items-center")
        if company_container:
            company = company_container.get_text(strip=True)

        # Nếu container trả về rỗng hoặc toàn slogan, fallback dùng logo title
        if not company or len(company) > 100:
            logo_els = card.select("a.logo-employer-card, a[href*='/companies/']")
            for logo in logo_els:
                title = logo.get("title", "").strip()
                if title:
                    # Cắt phần slogan sau dấu |
                    if "|" in title:
                        title = title.split("|")[0].strip()
                    if len(title) < 80:
                        company = title
                        break

        # Fallback cuối: tìm text giữa title và salary
        if not company:
            all_texts = [t.strip() for t in card.get_text(separator="\n").split("\n") if t.strip()]
            title_idx = next((i for i, t in enumerate(all_texts) if title[:20] in t), -1)
            if title_idx >= 0:
                for j in range(title_idx + 1, min(title_idx + 5, len(all_texts))):
                    c = all_texts[j]
                    if c and c != title and len(c) < 80:
                        if not any(s in c.lower() for s in [
                            "sign in", "posted", "$", "ago", "at office",
                            "remote", "hybrid", "ho chi minh", "ha noi", "da nang",
                            "super hot", "hot",
                        ]):
                            company = c
                            break

        # ── Salary ──
        salary_text = ""
        # Cách 1: text "Sign in to view salary" nằm trong thẻ có class salary
        salary_el = card.select_one(".salary, [class*='salary']")
        if salary_el:
            salary_text = salary_el.get_text(strip=True)
        # Cách 2: tìm trong toàn bộ text
        if not salary_text:
            for pattern in ["Sign in to view salary", "$"]:
                el = card.find(string=re.compile(re.escape(pattern)))
                if el:
                    salary_text = el.strip()
                    break
        salary = parse_salary(salary_text)

        # ── Location ──
        location = ""
        # Tìm text "At office" / "Remote" / "Hybrid"
        for work_type in ["At office", "Remote", "Hybrid"]:
            if work_type in card.get_text():
                location = work_type

        # ── City ──
        city = ""
        all_text = card.get_text()
        for c in ["Ho Chi Minh", "Ha Noi", "Da Nang"]:
            if re.search(rf'\b{re.escape(c)}\b', all_text):
                city = c
                break

        # ── Category ──
        category = ""
        cat_els = card.select("a[href*='/it-jobs/'][href*='click_source']")
        for cat_el in cat_els:
            href = cat_el.get("href", "")
            if "Skill+tag" not in href and "source=" not in href:
                cat_text = cat_el.get_text(strip=True)
                if cat_text and len(cat_text) < 60:
                    category = cat_text
                    break

        # ── Skills / Tags ──
        skills = []
        skill_els = card.select("a[href*='click_source=Skill+tag']")
        for s in skill_els:
            skill_text = s.get_text(strip=True)
            if skill_text and len(skill_text) < 40:
                skills.append(skill_text)

        # ── Hot Label ──
        hot_label = ""
        hot_el = card.select_one(".ilabel, [class*='hot'], [class*='super']")
        if hot_el:
            hot_text = hot_el.get_text(strip=True)
            if hot_text.upper() in ("SUPER HOT", "HOT", "NEW", "URGENT"):
                hot_label = hot_text.upper()

        # ── Benefits (3 short descriptions ở cuối card) ──
        benefits = []
        benefit_els = card.select(".box-shadow-normal .text-nowrap, .border-top-dashed .text-nowrap")
        for b in benefit_els:
            b_text = b.get_text(strip=True)
            if b_text and b_text not in benefits:
                benefits.append(b_text)

        return {
            "job_id": job_id,
            "job_slug": job_slug,
            "title": title,
            "company": company.strip(),
            "salary": salary,
            "salary_raw": salary_text,
            "city": city,
            "location": location,
            "category": category,
            "skills": skills,
            "hot_label": hot_label,
            "benefits": benefits,
            "posted_text": posted_text,
            "posted_date": posted_date.isoformat() if posted_date else None,
            "url": job_url,
            "source": "itviec",
            "crawled_at": datetime.now().isoformat(),
        }

    except Exception as e:
        print(f"  ⚠️  Lỗi parse job card: {e}")
        return None


def crawl_itviec(max_days: int = 1, max_pages: int = 0) -> list[dict]:
    """
    Crawl toàn bộ ITViec job listings.

    Args:
        max_days: Chỉ lấy job đăng trong max_days ngày qua.
        max_pages: Số trang tối đa (0 = không giới hạn, dừng khi hết job mới).

    Returns:
        List of parsed job dicts.
    """
    all_jobs = []
    seen_urls = set()
    cutoff_date = datetime.now() - timedelta(days=max_days)
    session = make_session()

    print(f"\n{'=' * 60}")
    print(f"🔍 ITViec Crawler — {datetime.now().strftime('%Y-%m-%d %H:%M')}")
    print(f"   Filter: job đăng trong {max_days} ngày qua")
    print(f"   Cutoff: {cutoff_date.strftime('%Y-%m-%d %H:%M')}")
    if max_pages:
        print(f"   Giới hạn: {max_pages} trang")
    print(f"{'=' * 60}\n")

    page_num = 1
    total_pages_estimate = None

    while True:
        if max_pages and page_num > max_pages:
            print(f"   ⏹  Đạt giới hạn {max_pages} trang\n")
            break

        data = fetch_page(page_num, session)
        if not data:
            break

        jobs_html = data.get("jobs_html", "")
        if not jobs_html:
            print(f"   ⏹  Trang {page_num} không có jobs_html, dừng\n")
            break

        # Parse headline để biết tổng số jobs
        if total_pages_estimate is None:
            headline = data.get("headline_result_html", "")
            total_match = re.search(r'(\d+)', headline)
            if total_match:
                total_jobs = int(total_match.group(1))
                total_pages_estimate = (total_jobs + 19) // 20  # 20 jobs/page
                print(f"   📊 Tổng ~{total_jobs} jobs, ~{total_pages_estimate} trang\n")

        soup = BeautifulSoup(jobs_html, "html.parser")
        job_cards = soup.select(".job-card")

        if not job_cards:
            print(f"   ⏹  Trang {page_num} không có job cards, dừng\n")
            break

        new_on_page = 0
        skipped_old = 0
        page_oldest = None

        for card in job_cards:
            job = parse_job_card(card)
            if not job or not job["title"]:
                continue

            if job["url"] in seen_urls:
                continue
            seen_urls.add(job["url"])

            # Filter theo thời gian
            if job["posted_date"]:
                posted = datetime.fromisoformat(job["posted_date"])
                if page_oldest is None or posted < page_oldest:
                    page_oldest = posted
                if posted < cutoff_date:
                    skipped_old += 1
                    continue

            all_jobs.append(job)
            new_on_page += 1

        # In tóm tắt trang
        shown = min(new_on_page, 3)
        for j in all_jobs[-shown:]:
            print(f"   📌 [{j['company'] or '?'}] {j['title'][:70]}")
            salary_info = j.get("salary_raw") or j.get("salary", {}).get("text", "")
            if salary_info:
                print(f"      💰 {salary_info[:60]}")
            if j.get("city") or j.get("location"):
                print(f"      📍 {j.get('city', '')} {j.get('location', '')}".strip())
            print(f"      ⏰ {j.get('posted_text', '')}")

        print(f"   ✅ Trang {page_num}: {new_on_page} new, {skipped_old} cũ (tổng: {len(all_jobs)})\n")

        # Điều kiện dừng
        # 1. Job cũ nhất trên trang đã vượt cutoff
        if page_oldest and page_oldest < cutoff_date:
            print(f"   ⏹  Job cũ nhất ({page_oldest.strftime('%Y-%m-%d')}) ngoài khoảng filter, dừng\n")
            break

        # 2. Hết trang (không có next page)
        pagination_html = data.get("pagination_html", "")
        if 'rel="next"' not in pagination_html and not re.search(
            rf'href="[^"]*\?page={page_num + 1}', pagination_html
        ):
            print(f"   ⏹  Hết phân trang\n")
            break

        # 3. Số trang vượt estimate
        if total_pages_estimate and page_num >= total_pages_estimate:
            print(f"   ⏹  Đã crawl hết {total_pages_estimate} trang\n")
            break

        page_num += 1
        time.sleep(PAGE_DELAY)

    session.close()
    return all_jobs


# ─── OUTPUT ─────────────────────────────────────────────

def save_results(jobs: list[dict]):
    """Lưu kết quả vào file JSON theo ngày."""
    today = datetime.now().strftime("%Y-%m-%d")
    output_path = OUTPUT_DIR / today / "itviec.json"
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

    # Highlight công ty mới nổi (đăng nhiều nhất / ít thấy)
    print(f"\n  🆕 Đáng chú ý (công ty có ≥5 jobs hôm nay):")
    high_volume = [(c, n) for c, n in company_counts.items() if n >= 5]
    for c, n in sorted(high_volume, key=lambda x: -x[1]):
        print(f"     · {c}: {n} jobs")

    print(f"{'=' * 60}\n")


# ─── CLI ────────────────────────────────────────────────

def main():
    parser = argparse.ArgumentParser(
        description="ITViec Job Crawler — Hiring Watchdog",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Ví dụ:
  python crawlers/itviec.py                        # Crawl 24h qua
  python crawlers/itviec.py --days 3               # Crawl 3 ngày qua
  python crawlers/itviec.py --max-pages 5          # Chỉ 5 trang đầu
  python crawlers/itviec.py --dry-run              # Test, không lưu
        """,
    )
    parser.add_argument("--days", type=int, default=1, help="Số ngày để filter (default: 1)")
    parser.add_argument("--max-pages", type=int, default=0, help="Giới hạn số trang (0 = không giới hạn)")
    parser.add_argument("--dry-run", action="store_true", help="Chạy thử, không lưu file")

    args = parser.parse_args()

    start = time.time()
    jobs = crawl_itviec(max_days=args.days, max_pages=args.max_pages)
    elapsed = time.time() - start

    print_summary(jobs)
    print(f"⏱️  Hoàn thành trong {elapsed:.1f}s")

    if not args.dry_run:
        save_results(jobs)


if __name__ == "__main__":
    main()
