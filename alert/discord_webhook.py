#!/usr/bin/env python3
"""
Discord Webhook Alert — Gửi daily digest qua Discord.

Discord Webhook API:
    POST https://discord.com/api/webhooks/{webhook_id}/{webhook_token}
    Body: {"embeds": [{...}]}

Limits:
    - Max 10 embeds per message
    - Embed title: 256 chars, description: 4096 chars
    - Fields: max 25 per embed, name: 256 chars, value: 1024 chars
    - Color: decimal integer (not hex)

Setup:
    1. Tạo Discord server (hoặc dùng server có sẵn)
    2. Server Settings → Integrations → Webhooks → New Webhook
    3. Copy Webhook URL
    4. Tạo file .env trong project root:
       DISCORD_WEBHOOK_URL="https://discord.com/api/webhooks/..."

Usage:
    python alert/discord_webhook.py                            # Gửi report hôm nay
    python alert/discord_webhook.py --date 2026-08-02
    python alert/discord_webhook.py --dry-run                  # Chỉ in, không gửi
"""

import argparse
import json
import os
import sys
from datetime import datetime
from pathlib import Path
from typing import Optional

import requests
from dotenv import load_dotenv

_SCRIPT_DIR = Path(__file__).resolve().parent
_PROJECT_ROOT = _SCRIPT_DIR.parent
if str(_PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(_PROJECT_ROOT))

from config.settings import REPORTS_DIR

# Load .env from project root (chứa DISCORD_WEBHOOK_URL)
load_dotenv(_PROJECT_ROOT / ".env")

# ─── Discord Embed Colors ───────────────────────────────────

ALERT_COLORS = {
    "red":    0xFF0000,   # 🔴
    "orange": 0xFFA500,   # 🟠
    "yellow": 0xFFD700,   # 🟡
    "none":   0x808080,   # ⚪
}

ALERT_EMOJI = {
    "red":    "🔴",
    "orange": "🟠",
    "yellow": "🟡",
    "none":   "  ",
}

SUMMARY_COLOR = 0x3498DB    # Blue
SUMMARY_EMOJI = "📊"
FOOTER_TEXT = "Hiring Watchdog · Automated Daily Scan"
FOOTER_ICON = "https://cdn-icons-png.flaticon.com/512/900/900618.png"


def _get_webhook_url() -> Optional[str]:
    """Lấy webhook URL từ environment variable."""
    return os.environ.get("DISCORD_WEBHOOK_URL")


def format_alert_embed(alert: dict) -> dict:
    """
    Format 1 alert thành Discord Embed.

    Args:
        alert: 1 phần tử trong report["alerts"] list

    Returns:
        Discord Embed object dict
    """
    level = alert.get("alert_level", "none")
    color = ALERT_COLORS.get(level, 0x808080)
    emoji = ALERT_EMOJI.get(level, "⚪")
    context = alert.get("context", {})
    is_new = alert.get("is_new_company", False)
    detection_type = alert.get("detection_type", "unknown")
    signals = alert.get("signals", {})

    # ── Title ──
    title = f"{emoji} {alert['company']}"
    if is_new:
        title += "  🆕 NEW"
    title = title[:256]

    # ── Description: summary line ──
    desc_parts = [
        f"**Score: {alert['final_score']:.2f}**",
        f"{context.get('job_count_today', 0)} jobs today",
        f"{len(context.get('role_categories', {}))} role types",
    ]
    it_ratio = context.get("it_ratio", 0)
    if it_ratio > 0:
        desc_parts.append(f"IT ratio: {it_ratio:.0%}")

    description = " · ".join(desc_parts)[:4096]

    # ── Fields ──
    fields = []

    # Detection method
    if detection_type == "cold_start":
        fields.append({
            "name": "🔍 Method",
            "value": f"**Cold Start** — new company ({context.get('days_active', 0)} days)",
            "inline": True,
        })
    else:
        fields.append({
            "name": "🔍 Method",
            "value": "**Statistical** — Z-Score + CUSUM",
            "inline": True,
        })

    # Score with alert level
    fields.append({
        "name": "📊 Alert Level",
        "value": f"**{level.upper()}** ({alert['final_score']:.2f})",
        "inline": True,
    })

    # Roles
    role_categories = context.get("role_categories", {})
    if role_categories:
        top_roles = sorted(role_categories.items(), key=lambda x: -x[1])[:5]
        fields.append({
            "name": "🎯 Top Roles",
            "value": "\n".join(f"• {r}: {c} jobs" for r, c in top_roles)[:1024],
            "inline": False,
        })

    # Recommendation / Analysis
    recommendation = alert.get("recommendation", "")
    if recommendation:
        fields.append({
            "name": "💬 Analysis",
            "value": recommendation[:1024],
            "inline": False,
        })

    # Z-Score details (if available)
    if signals.get("zscore"):
        zs = signals["zscore"]
        z_val = zs.get("z_score", 0)
        if z_val >= 2.0:
            fields.append({
                "name": "📈 Z-Score Detail",
                "value": (
                    f"Z = **{z_val:.1f}σ**\n"
                    f"Today: {zs.get('today_count', 0)} jobs\n"
                    f"Baseline (EMA): {zs.get('baseline', 0):.1f}\n"
                    f"Rolling Std: {zs.get('rolling_std', 0):.1f}"
                )[:1024],
                "inline": False,
            })

    # CUSUM details (if triggered)
    if signals.get("cusum") and signals["cusum"].get("is_triggered"):
        cs = signals["cusum"]
        fields.append({
            "name": "⚡ CUSUM Triggered",
            "value": (
                f"CUSUM S = **{cs.get('cusum_value', 0):.1f}** > H = {cs.get('threshold', 5.0):.1f}\n"
                f"Sustained hiring increase detected"
            )[:1024],
            "inline": False,
        })

    # Salary anomaly
    if signals.get("salary") and signals["salary"].get("anomaly_count", 0) > 0:
        sal = signals["salary"]
        salary_lines = []
        for a in sal.get("anomalies", [])[:3]:
            salary_lines.append(
                f"• {a.get('title', '?')[:35]}: "
                f"**${a.get('salary_usd', 0):,.0f}** "
                f"(P90: ${a.get('benchmark_p90', 0):,.0f}, "
                f"+{a.get('premium_pct', 0):.0f}%)"
            )
        fields.append({
            "name": f"💰 Salary Above Market ({sal['anomaly_count']} jobs)",
            "value": "\n".join(salary_lines)[:1024],
            "inline": False,
        })

    # Cold Start component breakdown
    if signals.get("cold_start"):
        cs = signals["cold_start"]
        comp = cs.get("components", {})
        det = cs.get("details", {})
        if comp:
            comp_lines = [
                f"Volume: {comp.get('volume_score', 0):.2f} ({det.get('job_count', 0)} jobs)",
                f"Diversity: {comp.get('diversity_score', 0):.2f} ({det.get('unique_roles', 0)} roles)",
                f"Seniority: {comp.get('seniority_score', 0):.2f} ({det.get('senior_ratio', 0):.0%})",
            ]
            if comp.get("salary_score", 0) > 0:
                comp_lines.append(
                    f"Salary: {comp.get('salary_score', 0):.2f} "
                    f"({det.get('salary_premium_ratio', 0):.0%} above P90)"
                )
            if comp.get("it_score", 0) > 0:
                comp_lines.append(f"IT Check: {comp.get('it_score', 0):.2f}")
            fields.append({
                "name": "🧩 Component Scores",
                "value": "\n".join(comp_lines)[:1024],
                "inline": False,
            })

    # Job titles sample
    job_titles = context.get("job_titles", [])
    if job_titles:
        sample = job_titles[:6]
        fields.append({
            "name": f"📋 Sample Jobs ({len(job_titles)} total)",
            "value": "\n".join(f"• {t}" for t in sample)[:1024],
            "inline": False,
        })

    return {
        "title": title,
        "description": description,
        "color": color,
        "fields": fields[:25],
        "footer": {"text": FOOTER_TEXT, "icon_url": FOOTER_ICON},
    }


def send_daily_digest(
    report: dict,
    webhook_url: str,
    dry_run: bool = False,
) -> bool:
    """
    Gửi daily digest report qua Discord Webhook.

    Gửi summary embed + top 10 alert embeds (Discord giới hạn 10 embed/webhook).

    Args:
        report: Kết quả từ detection/fusion.py generate_report()
        webhook_url: Discord webhook URL
        dry_run: Nếu True, chỉ in JSON không gửi thật

    Returns:
        True nếu gửi thành công
    """
    summary = report.get("summary", {})
    alerts = report.get("alerts", [])
    report_date = report.get("report_date", "unknown")

    # ── Build embeds ──
    embeds = []

    # Summary embed
    red_n = summary.get("red_alerts", 0)
    orange_n = summary.get("orange_alerts", 0)
    yellow_n = summary.get("yellow_alerts", 0)
    normal_n = summary.get("normal", 0)
    total = summary.get("total_companies_analyzed", 0)
    new_n = summary.get("new_companies", 0)

    alert_line = (
        f"🔴 **{red_n}** Red  ·  "
        f"🟠 **{orange_n}** Orange  ·  "
        f"🟡 **{yellow_n}** Yellow  ·  "
        f"✅ **{normal_n}** Normal"
    )

    summary_embed = {
        "title": f"{SUMMARY_EMOJI} Hiring Watchdog — {report_date}",
        "description": alert_line,
        "color": SUMMARY_COLOR,
        "fields": [
            {
                "name": "Companies",
                "value": f"**{total}** analyzed ({new_n} new)",
                "inline": True,
            },
            {
                "name": "Jobs",
                "value": f"**{sum(a.get('context', {}).get('job_count_today', 0) for a in alerts)}** in alerts",
                "inline": True,
            },
        ],
        "timestamp": report.get("generated_at", datetime.now().isoformat()),
        "footer": {"text": FOOTER_TEXT, "icon_url": FOOTER_ICON},
    }

    # If very few alerts, inline them into summary
    if len(alerts) <= 3 and len(alerts) > 0:
        inline_lines = []
        for a in alerts:
            emoji = ALERT_EMOJI.get(a.get("alert_level", "none"), "")
            new_tag = " 🆕" if a.get("is_new_company") else ""
            inline_lines.append(
                f"{emoji} **{a['company']}**{new_tag}: "
                f"{a['final_score']:.2f} ({a.get('context', {}).get('job_count_today', 0)} jobs)"
            )
        summary_embed["fields"].append({
            "name": "🚨 Alerts",
            "value": "\n".join(inline_lines)[:1024],
            "inline": False,
        })

    embeds.append(summary_embed)

    # Individual alert embeds (max 9 more, so summary + 9 alerts = 10 total)
    for alert in alerts[:9]:
        embeds.append(format_alert_embed(alert))

    # ── Dry run ──
    if dry_run:
        print(json.dumps({"embeds": embeds}, indent=2, ensure_ascii=False, default=str))
        print(f"\n💡 Would send {len(embeds)} embeds to Discord")
        return True

    # ── Send ──
    # Discord allows max 10 embeds per webhook message
    for i in range(0, len(embeds), 10):
        batch = embeds[i:i + 10]
        payload = {"embeds": batch}

        try:
            resp = requests.post(webhook_url, json=payload, timeout=15)
            if resp.status_code == 204:
                print(f"  ✅ Discord webhook sent ({len(batch)} embeds)")
            elif resp.status_code == 429:
                # Rate limited — Discord returns retry_after in seconds
                retry_after = resp.json().get("retry_after", 5)
                print(f"  ⚠️  Discord rate limited, retry after {retry_after}s")
                return False
            else:
                print(f"  ❌ Discord webhook failed: {resp.status_code}")
                try:
                    print(f"     {resp.text[:500]}")
                except Exception:
                    pass
                return False
        except requests.RequestException as e:
            print(f"  ❌ Discord webhook error: {e}")
            return False

    return True


# ─── CLI ────────────────────────────────────────────────────

def main():
    parser = argparse.ArgumentParser(
        description="Discord Webhook — Hiring Watchdog Daily Alert",
    )
    parser.add_argument(
        "--date", type=str, default=None,
        help="Ngày report (YYYY-MM-DD, default: hôm nay)",
    )
    parser.add_argument(
        "--dry-run", action="store_true",
        help="Chỉ in JSON preview, không gửi thật",
    )
    parser.add_argument(
        "--webhook-url", type=str, default=None,
        help="Discord webhook URL (override env var)",
    )

    args = parser.parse_args()
    date_str = args.date or datetime.now().strftime("%Y-%m-%d")

    webhook_url = args.webhook_url or _get_webhook_url()
    if not webhook_url:
        print("❌ No Discord webhook URL configured.")
        print("   Set environment variable: export DISCORD_WEBHOOK_URL=\"https://discord.com/api/webhooks/...\"")
        print("   Or pass --webhook-url argument")
        sys.exit(1)

    # Load report
    report_path = REPORTS_DIR / f"{date_str}.json"
    if not report_path.exists():
        print(f"❌ Report not found: {report_path}")
        print("   Run detection/fusion.py first")
        sys.exit(1)

    with open(report_path, "r", encoding="utf-8") as f:
        report = json.load(f)

    if not report.get("all_scores"):
        print("⚠️  Report is empty — no companies analyzed today")
        sys.exit(0)

    print(f"\n{'=' * 50}")
    print(f"📤 Sending Discord Alert — {date_str}")
    print(f"{'=' * 50}")

    success = send_daily_digest(report, webhook_url, dry_run=args.dry_run)

    if success:
        print(f"{'=' * 50}\n")
    else:
        sys.exit(1)


if __name__ == "__main__":
    main()
