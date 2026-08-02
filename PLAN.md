# Hiring Watchdog — Kế Hoạch Triển Khai

> **Mục tiêu**: Hệ thống tự động quét toàn bộ thị trường tuyển dụng IT, phát hiện công ty đang tuyển ồ ạt hoặc trả lương cao bất thường, gửi cảnh báo qua Telegram.

---

## Tổng Quan Kiến Trúc

```
ITViec ──┐
TopCV ───┤  Crawl tất cả
          ├──→ [Crawler] ──→ [Raw JSON] ──→ [Merge + Dedup] ──→ [Processed JSON]
VNW ─────┘                                                       │
                                                                 ▼
                                                    ┌─────────────────────┐
                                                    │ Detection Engine    │
                                                    │ (pandas + numpy)    │
                                                    │ ├── Z-Score         │
                                                    │ ├── CUSUM           │
                                                    │ ├── Cold Start      │
                                                    │ └── Salary Ref      │
                                                    └────────┬────────────┘
                                                             │
                                                             ▼
                                                    [Telegram Bot]
```

---

## Lộ Trình

### Phase 1: Crawler — Thu Thập Dữ Liệu (2-3 ngày)

**Mục tiêu**: Mỗi ngày có 1 file JSON chứa toàn bộ job mới, group theo công ty. Chưa có detection, chưa có alert.

**Nguyên tắc**: **CRAWL TẤT CẢ, KHÔNG FILTER NGÀNH NGHỀ.** Lý do:
- ITViec: 100% IT jobs → khỏi cần lọc
- TopCV, VietnamWorks: đa ngành → **crawl hết**, để Phase 2 viết classifier lọc IT sau
- Nếu lọc sai ở khâu crawl → mất data vĩnh viễn. Lọc sau → sửa classifier, chạy lại trên data cũ, không mất gì
- Có data toàn thị trường → biết market share của IT, có thể mở rộng sang ngành khác sau này

#### Day 1: Crawler ITViec ✅ (COMPLETED 2026-08-02)
- [x] Viết script crawl toàn bộ job listing trên ITViec (phân trang)
  - Phát hiện ITViec dùng Rails + Turbo, có API JSON trả về `jobs_html`
  - Không cần Playwright, dùng `requests` + `BeautifulSoup` parse HTML trong JSON response
- [x] Parse mỗi job: `title`, `company`, `salary`, `location`, `city`, `posted_date`, `skills`, `hot_label`, `category`, `benefits`, `link`
- [x] Filter: chỉ lấy job đăng trong 24h qua
- [x] Output: `data/raw/YYYY-MM-DD/itviec.json`
- [x] Test: 60 jobs từ 3 trang, 36 công ty, parse chính xác company names

#### Day 2: Thêm VietnamWorks + Dedup ✅ (COMPLETED 2026-08-02)
- [x] TopCV: **BLOCKED** — Cloudflare Turnstile CAPTCHA, không thể crawl kể cả với Playwright stealth
- [x] Viết crawler cho VietnamWorks (REST API `ms.vietnamworks.com/job-search/v1.0/search`)
  - Filter IT: `industryV3Ids: [25]` (IT Software/SaaS)
  - API không hỗ trợ sort theo ngày đăng → dùng multi-keyword search (20 keywords IT)
  - pageSize bị hard-cap ở 10, không thể tăng
  - Kết quả: 3 IT jobs mới hôm nay (Chủ nhật) — ngày thường sẽ nhiều hơn
  - Salary visibility: ~33% job có salary public (tốt hơn ITViec 0%)
- [x] Merge data từ các nguồn (`pipeline/merge.py`)
  - Normalize schema: cities, company names, unified job_id format
  - Dedup cơ bản: cùng `company_normalized` + `title` (token overlap ≥ 0.6) → merge, giữ source nhiều info nhất
  - Salary parsing: tự động parse từ text → structured `{type, min, max, currency}`
  - Output: `data/processed/YYYY-MM-DD.json`
- [x] Output: 59 unique jobs từ 2 nguồn (56 ITViec + 3 VNW, 2 duplicates removed)

#### Day 3: Tự Động Hóa ✅ (COMPLETED 2026-08-02)
- [x] Viết `run_daily.sh`: crawl → merge → save (đã update thêm VNW + merge)
- [ ] Cron job: chạy 8h sáng mỗi ngày (cần setup trên máy/VPS)
- [x] Logging: ghi log mỗi lần chạy vào `logs/daily-YYYY-MM-DD.log`
- [x] Health check: cảnh báo nếu < 20 raw jobs
- [ ] Backup: git push data (JSON text → git xử lý tốt)

**Kết thúc Phase 1**: Có data tích lũy mỗi ngày từ ITViec + VietnamWorks. TopCV bị Cloudflare block nên bỏ qua.
Pipeline: crawl → normalize → dedup → save processed JSON. Sẵn sàng cho Phase 2 (Detection Engine).

---

### Phase 2: Detection Engine ✅ (COMPLETED 2026-08-02)

**Mục tiêu**: Hệ thống tự chấm điểm từng công ty mỗi ngày, phân biệt được "bình thường" và "bất thường".

**Cấu trúc code:**
```
config/
├── settings.py             ← Thresholds, paths, keywords
└── salary_reference.py     ← SALARY_BENCHMARK (50+ role_level entries)
pipeline/
├── merge.py                ← Merge + dedup sources
└── storage.py              ← Load JSON → pandas, company history, IT classifier
detection/
├── cold_start.py           ← Cold Start Score (new companies)
├── zscore.py               ← Rolling Z-Score + CUSUM
├── salary.py               ← Salary anomaly check
└── fusion.py               ← Combine all signals → daily report
```

#### Week 1: Historical Baseline + Cold Start

**Day 1: Storage Design — JSON Files + pandas**

Dùng JSON files + pandas thay vì database:
- **150K rows/năm (~22MB)** — quá nhỏ, không cần database engine
- **Detection chỉ cần 4-8 tuần gần nhất** → load vài MB
- **Backup = git push** — JSON text, git nén tốt
- **Không server process, không migration, không schema**

Cấu trúc:
```
data/
├── raw/2026-08-02/           ← Raw crawl output
│   ├── itviec.json
│   └── vietnamworks.json
├── processed/2026-08-02.json ← Merged + dedup (toàn bộ job hôm nay)
├── reports/2026-08-02.json   ← Daily anomaly report
└── summary/                  ← Pre-aggregate để dashboard không load raw
    └── 2026-08-02.json       ← {company: {job_count, avg_salary, ...}}
```

- [x] Implement `storage.py`: save/load recent jobs, company history, aggregate summary
- [x] Implement incremental summary: mỗi ngày generate 1 file summary ~10KB
- [x] Dashboard dùng summary files, detection dùng processed files 4-8 tuần gần nhất

**Day 2: Cold Start Score (cho công ty mới, chưa có history)** ✅
- [x] Implement `cold_start_score()` — chấm điểm công ty KHÔNG có trong database:
  - Absolute volume (≥20 jobs → 0.35, ≥10 → 0.25, ≥5 → 0.15)
  - Role diversity (≥7 roles → 0.20, ≥4 → 0.12)
  - Seniority ratio (≥50% Senior+ → 0.20, ≥30% → 0.10)
  - Salary premium (≥30% above market P90 → 0.15)
  - IT company check (≥80% role là IT → 0.10)
- [x] Test với data thực tế: NAB Innovation Centre Vietnam = 0.57 🟠

**Day 3-4: Rolling Z-Score (cho công ty có history ≥ 14 ngày)** ✅
- [x] Implement rolling Z-Score:
  - Baseline = EMA của 4-8 tuần gần nhất
  - Z = (hôm nay - baseline) / rolling_std
  - Z > 2.5 → Orange, Z > 3.0 → Red
- [x] Implement CUSUM:
  - Tích lũy sai lệch nhỏ → phát hiện level shift sớm hơn Z-Score
  - S_t = max(0, S_{t-1} + (x_t - μ₀) - K), alert khi S_t > H

**Day 5: Salary Reference (30 phút/năm)** ✅
- [x] Tải 2-3 salary reports (ITViec, Navigos) mỗi năm 1 lần
- [x] Gõ tay `SALARY_BENCHMARK` dictionary (~50 role_level entries)
- [x] Implement `classify_role_level(job_title)` → (role, level, benchmark_key)
- [x] Implement `check_salary_anomaly(job_title, salary)` — so sánh với P90 market
- [x] Không cần automation phần này, manual 30 phút/năm là đủ

#### Week 2: Fusion + Tuning ✅ (COMPLETED 2026-08-02)

**Day 6: Fusion Engine** ✅
- [x] `fusion.py`: Gộp tất cả tín hiệu → 1 anomaly score duy nhất mỗi công ty
- [x] Weighted voting: Cold Start Score (new) hoặc Z-Score+CUSUM+Salary (historical)
- [x] Threshold: Red ≥ 0.70, Orange ≥ 0.50, Yellow ≥ 0.30
- [x] Output: `data/reports/YYYY-MM-DD.json` — sorted by anomaly score

**Day 7: IT Classifier + Phân Loại Alert** ✅
- [x] Keyword-based IT job detector (tích hợp trong `storage.py`, 100+ keywords EN+VI)
- [x] Gán tag `is_it` → `true`/`false` cho từng job
- [x] Company IT ratio = % job có tag `it` — phân tích công ty có IT ratio ≥ 60%
- [x] Phân loại alert: `cold_start` (công ty mới) vs `statistical` (Z-Score/CUSUM)
- [x] Recommendation text tự động: "Công ty mới (7 jobs, 4 roles); Nhiều Senior (100%)"

---

### Phase 3: Alert + Dashboard (2-4 tuần)

**Mục tiêu**: Không cần mở file JSON. Nhận thông báo qua Telegram khi có việc đáng quan tâm.

#### Week 3: Telegram Bot
- [ ] Daily digest (8h30 sáng): "Hôm nay top 5 công ty đáng chú ý"
- [ ] Real-time spike alert: "FPT vừa đăng 30 job mới"
- [ ] New company alert: "⭐ Phát hiện công ty mới: VinSmart Future, 18 IT jobs"
- [ ] Commands:
  - `/stats [company]` — xem lịch sử công ty
  - `/list` — top anomalies hôm nay
  - `/watch [company]` — theo dõi thêm công ty

#### Week 4: Streamlit Dashboard
- [ ] **Trang Home**: Top anomalies hôm nay + 7 ngày qua
- [ ] **Trang Company Detail**: chart historical job count, salary trend, seniority distribution
- [ ] **Trang Market Overview**: tổng job/ngày toàn thị trường, top hiring companies, hot roles
- [ ] **Trang Watchlist**: công ty đang quan tâm

---

## Cấu Trúc Thư Mục

```
hiring-watchdog/
├── PLAN.md                    # File này
├── THEORY.md                  # Lý thuyết nền tảng
├── crawlers/
│   ├── __init__.py
│   ├── itviec.py              # Crawler ITViec
│   ├── topcv.py               # Crawler TopCV
│   └── vietnamworks.py        # Crawler VietnamWorks
├── pipeline/
│   ├── __init__.py
│   ├── merge.py               # Gộp nhiều nguồn
│   ├── dedup.py               # Loại trùng lặp
│   ├── classify.py            # Phân loại role, level
│   └── storage.py             # Load/save JSON, aggregate summary
├── detection/
│   ├── __init__.py
│   ├── cold_start.py          # Cold Start Score
│   ├── zscore.py              # Rolling Z-Score
│   ├── cusum.py               # CUSUM
│   ├── salary.py              # Salary anomaly (lookup table)
│   └── fusion.py              # Gộp tín hiệu → score cuối
├── alert/
│   ├── __init__.py
│   └── telegram_bot.py        # Telegram Bot
├── dashboard/
│   └── app.py                 # Streamlit dashboard
├── config/
│   ├── settings.py            # API keys, thresholds
│   └── salary_reference.py    # SALARY_BENCHMARK dict (update 1 lần/năm)
├── data/                      # Git-ignored (hoặc git LFS)
│   ├── raw/                   # JSON thô mỗi ngày mỗi nguồn
│   └── processed/             # Đã merge + dedup
├── tests/
│   └── ...
├── run_daily.sh               # Entry point cho cron
├── requirements.txt
└── README.md
```

---

## Tech Stack

| Thành phần | Công nghệ | Lý do |
|-----------|-----------|-------|
| Crawler | Python + `requests` + `BeautifulSoup` | Đơn giản, đủ dùng cho job board VN |
| Storage | JSON files + `pandas` | 22MB/năm — quá nhỏ, không cần DB engine. git push là backup |
| Detection | Python + `numpy` + `scipy` | Tính toán thống kê |
| Alert | Telegram Bot API | Miễn phí, real-time, mobile-friendly |
| Dashboard | Streamlit | Code ít, giao diện đẹp, Python-native |
| Scheduler | Cron (macOS/Linux) | Đơn giản, không cần Airflow |
| Deployment | Local machine / VPS $6-10/tháng | Ổ cứng thật, không cần serverless |

---

## Quy Trình Chạy Hàng Ngày

```
8:00  — Cron trigger run_daily.sh
8:05  — Crawl xong ITViec + VietnamWorks
8:06  — Merge + dedup + parse salary
8:07  — Lưu JSON vào data/processed/
8:08  — Chạy Detection Engine (load 8 tuần gần nhất từ processed/):
        ├── Với công ty mới (< 14 ngày history) → Cold Start Score
        ├── Với công ty có history → Z-Score + CUSUM
        └── Với công ty có salary → Salary Anomaly
8:09  — Fusion: gộp tín hiệu, rank theo score → lưu reports/
8:10  — Done. Bạn nhận Telegram, vừa uống cà phê vừa đọc.
```

---

## Bảo Trì Hàng Năm

| Khi nào | Làm gì | Mất bao lâu |
|---------|--------|-------------|
| Tháng 1-2 | Cập nhật `salary_reference.py` từ report mới | 30 phút |
| Khi crawler chết | Sửa CSS selector (job board đổi giao diện) | 1-2 giờ |
| Thêm nguồn mới | Viết crawler mới theo template | 2-3 giờ |
| Điều chỉnh threshold | Xem false positive rate, tune ngưỡng | 1 giờ |
