"""
Hiring Watchdog — Salary Reference Table.

Dữ liệu benchmark lương IT thị trường Việt Nam, cập nhật thủ công 1 lần/năm
từ các báo cáo lương (ITViec, Navigos, TopCV, Adecco, Robert Walters).

Nguồn: ITViec IT Salary Report 2025-2026, Navigos Salary Survey 2025

Đơn vị: USD/tháng (gross)
Cập nhật: Tháng 1-2 mỗi năm
"""

# ─── SALARY BENCHMARK ───────────────────────────────────
#
# Format: role_level → {p50, p75, p90}
#   - p50: median — "bình thường"
#   - p75: 75th percentile — "cao"
#   - p90: 90th percentile — "rất cao / exception"
#
# Salary anomaly = job salary > p90 của role_level tương ứng
# → Flag nếu ≥30% above p90

SALARY_BENCHMARK = {
    # ── Software Development ──
    "backend_junior":    {"p50": 800,   "p75": 1200,  "p90": 1500},
    "backend_mid":       {"p50": 1500,  "p75": 2200,  "p90": 2800},
    "backend_senior":    {"p50": 2500,  "p75": 3500,  "p90": 4500},
    "backend_lead":      {"p50": 3500,  "p75": 5000,  "p90": 6500},

    "frontend_junior":   {"p50": 700,   "p75": 1100,  "p90": 1400},
    "frontend_mid":      {"p50": 1300,  "p75": 2000,  "p90": 2600},
    "frontend_senior":   {"p50": 2200,  "p75": 3200,  "p90": 4200},
    "frontend_lead":     {"p50": 3200,  "p75": 4600,  "p90": 6000},

    "fullstack_junior":  {"p50": 800,   "p75": 1300,  "p90": 1600},
    "fullstack_mid":     {"p50": 1600,  "p75": 2400,  "p90": 3000},
    "fullstack_senior":  {"p50": 2800,  "p75": 4000,  "p90": 5200},
    "fullstack_lead":    {"p50": 4000,  "p75": 5500,  "p90": 7000},

    "mobile_junior":     {"p50": 800,   "p75": 1200,  "p90": 1500},
    "mobile_mid":        {"p50": 1500,  "p75": 2300,  "p90": 2900},
    "mobile_senior":     {"p50": 2600,  "p75": 3800,  "p90": 5000},
    "mobile_lead":       {"p50": 3800,  "p75": 5200,  "p90": 6800},

    # ── DevOps / Cloud / SRE ──
    "devops_mid":        {"p50": 1500,  "p75": 2300,  "p90": 3000},
    "devops_senior":     {"p50": 2800,  "p75": 4000,  "p90": 5200},
    "devops_lead":       {"p50": 4000,  "p75": 5500,  "p90": 7000},

    "cloud_mid":         {"p50": 1400,  "p75": 2200,  "p90": 2800},
    "cloud_senior":      {"p50": 2600,  "p75": 3800,  "p90": 5000},
    "cloud_lead":        {"p50": 3800,  "p75": 5200,  "p90": 6800},

    # ── Data / AI / ML ──
    "data_engineer_mid":     {"p50": 1400,  "p75": 2100,  "p90": 2700},
    "data_engineer_senior":  {"p50": 2500,  "p75": 3700,  "p90": 4800},
    "data_scientist_mid":    {"p50": 1500,  "p75": 2300,  "p90": 3000},
    "data_scientist_senior": {"p50": 2800,  "p75": 4200,  "p90": 5500},
    "ml_engineer_mid":       {"p50": 1600,  "p75": 2500,  "p90": 3200},
    "ml_engineer_senior":    {"p50": 3000,  "p75": 4500,  "p90": 6000},

    "data_analyst_junior":   {"p50": 700,   "p75": 1000,  "p90": 1300},
    "data_analyst_mid":      {"p50": 1200,  "p75": 1800,  "p90": 2400},
    "data_analyst_senior":   {"p50": 2200,  "p75": 3200,  "p90": 4200},

    # ── QA / Testing ──
    "qa_mid":            {"p50": 1000,  "p75": 1600,  "p90": 2100},
    "qa_senior":         {"p50": 1800,  "p75": 2600,  "p90": 3500},
    "qa_lead":           {"p50": 2500,  "p75": 3500,  "p90": 4500},
    "qa_automation_mid":     {"p50": 1200,  "p75": 1800,  "p90": 2400},
    "qa_automation_senior":  {"p50": 2000,  "p75": 3000,  "p90": 4000},

    # ── Security ──
    "security_mid":      {"p50": 1400,  "p75": 2100,  "p90": 2800},
    "security_senior":   {"p50": 2500,  "p75": 3800,  "p90": 5000},
    "security_lead":     {"p50": 3800,  "p75": 5200,  "p90": 6800},

    # ── Network / System Admin ──
    "network_mid":       {"p50": 1000,  "p75": 1500,  "p90": 2000},
    "network_senior":    {"p50": 1800,  "p75": 2500,  "p90": 3200},
    "sysadmin_mid":      {"p50": 1000,  "p75": 1500,  "p90": 2000},
    "sysadmin_senior":   {"p50": 1800,  "p75": 2500,  "p90": 3200},

    # ── Management ──
    "engineering_manager":  {"p50": 4000,  "p75": 6000,  "p90": 8000},
    "cto":                  {"p50": 5000,  "p75": 8000,  "p90": 12000},
    "tech_lead":            {"p50": 3000,  "p75": 4500,  "p90": 6000},

    # ── UX/UI Design ──
    "designer_mid":      {"p50": 1000,  "p75": 1600,  "p90": 2100},
    "designer_senior":   {"p50": 1800,  "p75": 2600,  "p90": 3500},
    "designer_lead":     {"p50": 2500,  "p75": 3500,  "p90": 4500},

    # ── Business Analyst / Product ──
    "ba_mid":            {"p50": 1000,  "p75": 1600,  "p90": 2100},
    "ba_senior":         {"p50": 1800,  "p75": 2600,  "p90": 3500},
    "product_manager_mid":    {"p50": 1500,  "p75": 2200,  "p90": 2800},
    "product_manager_senior": {"p50": 2500,  "p75": 3800,  "p90": 5000},

    # ── Embedded / IoT ──
    "embedded_mid":      {"p50": 1200,  "p75": 1800,  "p90": 2400},
    "embedded_senior":   {"p50": 2000,  "p75": 3000,  "p90": 4000},

    # ── IT Support / Helpdesk ──
    "it_support_junior":  {"p50": 500,   "p75": 800,   "p90": 1000},
    "it_support_mid":     {"p50": 800,   "p75": 1200,  "p90": 1600},
    "it_support_senior":  {"p50": 1200,  "p75": 1800,  "p90": 2500},

    # ── General / Unknown ──
    "general_junior":    {"p50": 600,   "p75": 900,   "p90": 1200},
    "general_mid":       {"p50": 1200,  "p75": 1800,  "p90": 2400},
    "general_senior":    {"p50": 2000,  "p75": 3000,  "p90": 4000},
}


# ─── ROLE CLASSIFICATION ────────────────────────────────
#
# Map job title keywords → (role_category, level)

def get_default_benchmark():
    """Trả về benchmark mặc định cho role không xác định được."""
    return {"p50": 1200, "p75": 1800, "p90": 2400}  # general_mid
