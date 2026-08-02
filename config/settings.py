"""
Hiring Watchdog — Centralized Settings.

Tất cả thresholds, paths, và config parameter cho detection engine.
Điều chỉnh thresholds ở đây, không cần sửa code.
"""

from pathlib import Path

# ─── PATHS ──────────────────────────────────────────────

ROOT_DIR = Path(__file__).resolve().parent.parent
DATA_DIR = ROOT_DIR / "data"
PROCESSED_DIR = DATA_DIR / "processed"
REPORTS_DIR = DATA_DIR / "reports"
RAW_DIR = DATA_DIR / "raw"

# ─── DATA WINDOW ────────────────────────────────────────

# Detection chỉ cần 4-8 tuần gần nhất
HISTORY_WINDOW_DAYS = 56  # 8 tuần
MIN_HISTORY_DAYS = 14     # Cần ít nhất 14 ngày mới dùng Z-Score

# ─── Z-SCORE THRESHOLDS ─────────────────────────────────

ZSCORE_ORANGE = 2.5   # Z > 2.5 → Orange alert
ZSCORE_RED = 3.0      # Z > 3.0 → Red alert
EMA_WINDOW_WEEKS = 4  # Baseline = EMA của 4 tuần gần nhất
EMA_ALPHA = 2.0 / (EMA_WINDOW_WEEKS * 7 + 1)  # EMA alpha

# ─── CUSUM THRESHOLDS ───────────────────────────────────

CUSUM_K = 0.5         # Allowable slack (đơn vị: std deviations)
CUSUM_H = 5.0         # Decision threshold (đơn vị: std deviations)

# ─── COLD START SCORING ────────────────────────────────

COLD_START_THRESHOLD = 0.40  # Score > 0.40 → flag as potential anomaly

# Component scores
COLD_START_VOLUME = {
    20: 0.35,  # ≥20 jobs
    10: 0.25,  # ≥10 jobs
    5:  0.15,  # ≥5 jobs
}

COLD_START_DIVERSITY = {
    7: 0.20,   # ≥7 unique roles
    4: 0.12,   # ≥4 unique roles
}

COLD_START_SENIORITY = {
    0.50: 0.20,  # ≥50% Senior+
    0.30: 0.10,  # ≥30% Senior+
}

COLD_START_SALARY_PREMIUM = {
    0.30: 0.15,  # ≥30% above market P90
    0.15: 0.10,  # ≥15% above market P90
}

COLD_START_IT_CHECK = 0.10  # ≥80% jobs are IT → bonus for focus

# ─── IT CLASSIFIER ──────────────────────────────────────

# Công ty cần ≥ IT_RATIO_THRESHOLD % job là IT mới được analyze
IT_RATIO_THRESHOLD = 0.60

IT_KEYWORDS = [
    # English
    "developer", "engineer", "programmer", "software", "web", "mobile",
    "frontend", "front-end", "backend", "back-end", "fullstack", "full-stack",
    "devops", "sre", "cloud", "infrastructure", "platform",
    "data engineer", "data scientist", "data analyst", "machine learning",
    "ai engineer", "ml engineer", "artificial intelligence",
    "qa", "tester", "quality assurance", "quality engineer", "test automation",
    "security engineer", "security analyst", "pentester",
    "network engineer", "network administrator", "system administrator",
    "database administrator", "dba", "data architect",
    "solution architect", "software architect", "technical architect",
    "cto", "chief technology officer", "vp of engineering",
    "scrum master", "agile coach", "product owner", "technical product",
    "ux designer", "ui designer", "ux/ui", "product designer",
    "embedded", "firmware", "iot",
    "blockchain", "game developer", "ar/vr",
    # Vietnamese
    "lập trình viên", "lập trình", "phát triển phần mềm",
    "kỹ sư phần mềm", "kỹ sư cầu nối", "kỹ sư hệ thống",
    "kiểm thử", "tester", "qa",
    "quản trị mạng", "quản trị hệ thống",
    "phân tích nghiệp vụ", "business analyst", "ba",
    "thiết kế", "designer",
    "dữ liệu", "data",
    "an ninh mạng", "an toàn thông tin",
    "trưởng nhóm", "tech lead", "team lead",
    "giảng viên công nghệ", "nghiên cứu viên công nghệ",
]

# Job levels for seniority classification
SENIOR_KEYWORDS = {
    "senior": [
        "senior", "sr.", "sr ", "lead", "principal", "staff",
        "architect", "manager", "head", "director", "vp",
        "cấp cao", "trưởng", "giám đốc", "quản lý", "trưởng nhóm",
        "chuyên gia", "chuyên viên chính", "chuyên viên cao cấp",
    ],
    "mid": [
        "mid", "middle", "intermediate",
        "chuyên viên",
    ],
    "junior": [
        "junior", "jr.", "jr ", "fresher", "intern", "thực tập",
        "mới tốt nghiệp", "mới ra trường",
    ],
}

# ─── ANOMALY TYPE WEIGHTS (Fusion) ──────────────────────

# Trọng số cho từng tín hiệu khi fusion
WEIGHT_ZSCORE = 0.35
WEIGHT_CUSUM = 0.25
WEIGHT_COLD_START = 0.25
WEIGHT_SALARY = 0.15

# ─── ALERT LEVELS ───────────────────────────────────────

ALERT_RED = 0.70     # Score ≥ 0.70 → Red alert
ALERT_ORANGE = 0.50  # Score ≥ 0.50 → Orange alert
ALERT_YELLOW = 0.30  # Score ≥ 0.30 → Yellow (low priority)

# ─── DISCORD WEBHOOK ────────────────────────────────────

# Webhook URL được set qua environment variable DISCORD_WEBHOOK_URL
# hoặc file .env trong project root.
# Cách tạo webhook:
#   1. Discord Server Settings → Integrations → Webhooks → New Webhook
#   2. Copy Webhook URL: https://discord.com/api/webhooks/{id}/{token}

# Số alert tối đa hiển thị trong 1 daily digest
DISCORD_MAX_ALERTS = 10

# Có gửi embed chi tiết cho từng alert hay không
DISCORD_DETAILED_EMBEDS = True
