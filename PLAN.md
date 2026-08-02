# Hiring Watchdog — Kế Hoạch Triển Khai

> **Mục tiêu**: Hệ thống tự động quét toàn bộ thị trường tuyển dụng IT, phát hiện công ty đang tuyển ồ ạt hoặc trả lương cao bất thường, gửi cảnh báo qua Discord.

---

## Tổng Quan Kiến Trúc

```
┌───────────────────────────────── GitHub Actions (miễn phí 2000 phút/tháng) ───────────────┐
│                                                                                          │
│  8:00  — Cron trigger                                                                   │
│                                                                                          │
│  ITViec ──┐                                                                             │
│            ├──→ [Crawler] ──→ [Raw JSON] ──→ [Merge + Dedup] ──→ [Processed JSON]       │
│  VNW ────┘                                                      │                        │
│                                                                  ▼                        │
│                                                     ┌─────────────────────┐              │
│                                                     │ Detection Engine    │              │
│                                                     │ (pandas + numpy)    │              │
│                                                     │ ├── Z-Score         │              │
│                                                     │ ├── CUSUM           │              │
│                                                     │ ├── Cold Start      │              │
│                                                     │ └── Salary Ref      │              │
│                                                     └────────┬────────────┘              │
│                                                              │                           │
│                                                              ▼                           │
│                                                     [Discord Webhook]                    │
│                                                              │                           │
│                                                              ▼                           │
│                                                     git add data/ && git push           │
│                                                                                          │
└──────────────────────────────────────────────────────────────────────────────────────────┘
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
- [x] Viết `run_daily.sh`: crawl → merge → detect → alert → push
- [x] Logging: ghi log mỗi lần chạy vào `logs/daily-YYYY-MM-DD.log`
- [x] Health check: cảnh báo nếu < 20 raw jobs
- [ ] GitHub Actions: `.github/workflows/daily.yml` — cron 8h sáng mỗi ngày
- [ ] Auto push: git commit + push data/JSON files sau mỗi lần chạy

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

### Phase 3: Discord Alert ✅ (COMPLETED 2026-08-02)

**Mục tiêu**: Không cần mở file JSON. Nhận thông báo qua Discord Webhook khi có việc đáng quan tâm.

**Tại sao chỉ Webhook, không làm Bot:**
- Webhook: cron job chạy xong → POST JSON → tắt. Runtime 2 phút/ngày, không cần server 24/7.
- Bot: cần process chạy liên tục để listen slash commands — không phù hợp với mô hình cron job.
- Webhook làm được 90% nhu cầu: daily digest, spike alert, new company alert.

**Tại sao chưa làm Web UI:**
- Web UI cần server serve 24/7 — không deploy chung với cron job được.
- Nếu làm thì là **project riêng**, đọc chung `data/` folder, serve bằng VPS hoặc free-tier hosting.
- Hiện tại Discord notification là đủ để phát hiện cơ hội. Web UI để sau khi thực sự cần phân tích sâu.

#### Discord Webhook ✅
- [x] Setup: tạo Discord server → tạo webhook URL → lưu vào .env
- [x] `alert/discord_webhook.py`: module gửi message qua webhook
  - Hàm `send_daily_digest(report)`: gửi top alerts + summary
  - Hàm `format_embed(alert)`: tạo Discord Embed từ 1 alert
  - Embed color theo alert level: 🔴 Red = 0xFF0000, 🟠 Orange = 0xFFA500, 🟡 Yellow = 0xFFD700
  - Mỗi alert là 1 embed với: company name, score, job count, detection type, recommendation
  - Summary field: tổng số công ty, breakdown red/orange/yellow
  - Đọc webhook URL từ `.env` qua `load_dotenv()` — không cần export, cron cũng đọc được
- [x] Tích hợp vào `run_daily.sh`: sau `detection/fusion.py` → gửi webhook
- [x] Test gửi alert với data thực tế — gửi thành công 4 embeds

#### Web UI (Project Riêng — Tương Lai)
- [ ] Project riêng biệt, đọc `data/` folder (hoặc shared volume nếu dùng VPS)
- [ ] **Trang Home**: Top anomalies hôm nay + 7 ngày qua
- [ ] **Trang Company Detail**: chart historical job count, salary trend, seniority distribution
- [ ] **Trang Market Overview**: tổng job/ngày toàn thị trường, top hiring companies, hot roles
- [ ] Deploy: VPS $6-10/tháng hoặc free-tier (Render, Fly.io) nếu traffic thấp

---

### Phase 4: GitHub Actions Deployment

**Mục tiêu**: Chạy pipeline tự động trên GitHub Actions, không cần máy riêng/VPS.

**Tại sao GitHub Actions:**
- **Miễn phí**: 2000 phút/tháng — pipeline chỉ tốn ~30 phút/tháng
- **Public repo**: không giới hạn phút chạy
- **Private repo**: vẫn 2000 phút/tháng (free), 3000 (Pro)
- **Không cần VPS**: không cần server 24/7. Trigger cron → chạy 2 phút → tắt
- **Data persistence**: git push JSON files về repo sau mỗi lần chạy

**Tại sao git push thay vì Artifacts:**
- JSON files (22MB/năm) — quá nhỏ, github repo chịu được ~45 năm mới bị warning
- Git push → data nằm ngay trong repo, clone về là có lịch sử đầy đủ
- Artifacts chỉ giữ 90 ngày, không phù hợp cho historical data

#### Setup
- [ ] Bỏ `data/` khỏi `.gitignore` — cần git push data mỗi ngày để tích lũy history
- [ ] Tạo `.github/workflows/daily.yml`:
  ```yaml
  name: Daily Scan
  on:
    schedule:
      - cron: '0 1 * * *'   # 8:00 AM VN (UTC+7 → 1h UTC)
    workflow_dispatch:       # Manual trigger để test
  jobs:
    scan:
      runs-on: ubuntu-latest
      steps:
        - uses: actions/checkout@v4
        - uses: actions/setup-python@v5
          with: { python-version: '3.11' }
        - run: pip install -r requirements.txt
        - run: bash run_daily.sh
          env:
            DISCORD_WEBHOOK_URL: ${{ secrets.DISCORD_WEBHOOK_URL }}
        - run: |
            git config user.name "github-actions[bot]"
            git config user.email "github-actions[bot]@users.noreply.github.com"
            git add data/
            git diff --staged --quiet || (git commit -m "$(date +%Y-%m-%d) Daily data" && git push)
  ```
- [ ] Set GitHub Secret: `DISCORD_WEBHOOK_URL` (Settings → Secrets → Actions)

---

## Cấu Trúc Thư Mục

```
hiring-watchdog/
├── .github/
│   └── workflows/
│       └── daily.yml            # GitHub Actions — cron trigger hàng ngày
├── PLAN.md                    # File này
├── THEORY.md                  # Lý thuyết nền tảng
├── crawlers/
│   ├── __init__.py
│   ├── itviec.py              # Crawler ITViec
│   ├── topcv.py               # Crawler TopCV (BLOCKED)
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
│   └── discord_webhook.py     # Discord Webhook alert
├── config/
│   ├── settings.py            # API keys, thresholds
│   └── salary_reference.py    # SALARY_BENCHMARK dict (update 1 lần/năm)
├── data/                      # Được git push — JSON files tích lũy history
│   ├── raw/                   # JSON thô mỗi ngày mỗi nguồn
│   └── processed/             # Đã merge + dedup
├── tests/
│   └── ...
├── .env.example               # Template env vars
├── run_daily.sh               # Entry point cho GitHub Actions
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
| Alert | Discord Webhook API | Miễn phí, embed đẹp, mobile-friendly, hoạt động ở VN |
| Scheduler | GitHub Actions | Cron trigger miễn phí (2000 phút/tháng), không cần VPS |
| Data Backup | Git push | JSON text — git nén tốt, 22MB/năm (~45 năm mới bị warning) |
| Deployment | GitHub Actions runner | ubuntu-latest, Python 3.11, chạy 2 phút/ngày rồi tắt |

---

## Quy Trình Chạy Hàng Ngày

```
01:00 — GitHub Actions cron trigger (8:00 AM VN, UTC+7)
01:01 — Checkout repo + pip install dependencies
01:02 — Crawl xong ITViec + VietnamWorks
01:03 — Merge + dedup + parse salary
01:04 — Lưu JSON vào data/processed/
01:05 — Chạy Detection Engine (load 8 tuần gần nhất từ processed/):
        ├── Với công ty mới (< 14 ngày history) → Cold Start Score
        ├── Với công ty có history → Z-Score + CUSUM
        └── Với công ty có salary → Salary Anomaly
01:06 — Fusion: gộp tín hiệu, rank theo score → lưu reports/
01:07 — Discord Webhook: gửi daily digest (top alerts + summary)
01:08 — git add data/ && git commit && git push (backup + tích lũy history)
01:08 — Done. Bạn nhận Discord notification ~8h sáng, vừa uống cà phê vừa đọc.
```

**Tổng runtime**: ~2 phút/ngày → **30 phút/tháng** (dưới giới hạn free 2000 phút)

---

## Bảo Trì Hàng Năm

| Khi nào | Làm gì | Mất bao lâu |
|---------|--------|-------------|
| Tháng 1-2 | Cập nhật `salary_reference.py` từ report mới | 30 phút |
| Khi crawler chết | Sửa CSS selector (job board đổi giao diện) | 1-2 giờ |
| Thêm nguồn mới | Viết crawler mới theo template | 2-3 giờ |
| Điều chỉnh threshold | Xem false positive rate, tune ngưỡng | 1 giờ |
