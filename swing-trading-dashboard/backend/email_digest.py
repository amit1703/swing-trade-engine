"""
email_digest.py — Daily Swing Trading Email Digest
====================================================
Builds a dark-themed HTML email summarising today's scan results and sends
it via Gmail SMTP (port 587, STARTTLS).

Usage
-----
Called by the APScheduler job wired in main.py:
    from email_digest import send_digest
    send_digest(scan_results)

Env vars required in .env
--------------------------
    EMAIL_FROM      Gmail address to send from       (e.g. you@gmail.com)
    EMAIL_PASSWORD  Gmail App Password (16 chars)
    EMAIL_TO        Recipient address (default: amit.izhari@gmail.com)

scan_results dict shape (matches _digest_cache populated by run_morning_scan)
---------------------------------------------------------------------------
    {
        "regime": {
            "regime":       "AGGRESSIVE" | "SELECTIVE" | "DEFENSIVE",
            "regime_score": float 0-100,
            "spy_close":    float,
            "spy_sma50":    float,
            "is_bullish":   bool,
        },
        "vcp":              [ {ticker, entry, stop_loss, rr, rs_score, setup_score, sector, ...} ],
        "vcp_dry":          [ ... ],
        "res_breakout":     [ ... ],   # top 5 shown
        "pullback":         [ ... ],   # top 5 shown
        "htf":              [ ... ],
        "lce":              [ ... ],
        "options_catalyst": [ ... ],
    }
"""

import logging
import os
import smtplib
import ssl
from datetime import datetime
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from typing import Dict, List, Optional
from zoneinfo import ZoneInfo

log = logging.getLogger("swing.email")

# ── Constants ─────────────────────────────────────────────────────────────────

SMTP_HOST = "smtp.gmail.com"
SMTP_PORT = 587
DEFAULT_RECIPIENT = "amit.izhari@gmail.com"

# Palette
C_BG      = "#141414"
C_SURFACE = "#1e1e1e"
C_CARD    = "#242424"
C_BORDER  = "#2e2e2e"
C_TEXT    = "#e2e2e2"
C_MUTED   = "#6b6b6b"
C_GREEN   = "#00c87a"
C_RED     = "#ff3b3b"
C_AMBER   = "#f5a623"
C_BLUE    = "#4da6ff"
C_PURPLE  = "#9b6eff"
C_PINK    = "#ff6ec7"


# ── Helpers ───────────────────────────────────────────────────────────────────

def _fmt(val, prefix="$", decimals=2) -> str:
    if val is None or val == 0:
        return "—"
    return f"{prefix}{val:.{decimals}f}" if prefix else f"{val:.{decimals}f}"

def _rs_color(rs) -> str:
    if rs is None: return C_MUTED
    if rs >= 80:   return C_GREEN
    if rs >= 50:   return C_AMBER
    return C_MUTED

def _rr_color(rr) -> str:
    if rr is None: return C_MUTED
    if rr >= 3.0:  return C_GREEN
    if rr >= 2.0:  return C_AMBER
    return C_MUTED

def _score_color(s) -> str:
    if s is None: return C_MUTED
    if s >= 80:   return C_GREEN
    if s >= 65:   return C_AMBER
    return C_MUTED

def _sector_short(sector: Optional[str]) -> str:
    if not sector: return "—"
    MAP = {
        "Technology": "Tech", "Healthcare": "Health", "Financials": "Fin",
        "Consumer Discretionary": "Cons Disc", "Consumer Staples": "Cons Stap",
        "Industrials": "Indust", "Energy": "Energy", "Materials": "Matrl",
        "Real Estate": "RE", "Utilities": "Util", "Communication Services": "Comm",
    }
    return MAP.get(sector, sector[:10])


# ── Table builder ─────────────────────────────────────────────────────────────

def _table(setups: List[Dict], limit: Optional[int] = None) -> str:
    rows = setups[:limit] if limit else setups
    if not rows:
        return ""

    th = lambda t, align="right": f'<th style="text-align:{align};padding:6px 10px;border-bottom:1px solid {C_BORDER};color:{C_MUTED};font-size:10px;font-weight:600;text-transform:uppercase;letter-spacing:0.8px;white-space:nowrap;">{t}</th>'
    td = lambda val, color=C_TEXT, bold=False, align="right": (
        f'<td style="text-align:{align};padding:7px 10px;border-bottom:1px solid {C_BORDER};'
        f'color:{color};{"font-weight:700;" if bold else ""}font-size:12px;white-space:nowrap;">{val}</td>'
    )

    header = f"""<tr>
        {th("Ticker", "left")}{th("Score")}{th("Entry")}{th("Stop")}{th("R:R")}{th("RS")}{th("Sector", "left")}
    </tr>"""

    body = ""
    for i, s in enumerate(rows):
        ticker = s.get("ticker", "—")
        score  = s.get("setup_score")
        entry  = s.get("entry")
        stop   = s.get("stop_loss")
        rr     = s.get("rr")
        rs     = s.get("rs_score")
        sector = _sector_short(s.get("sector"))
        vol_surge = s.get("is_vol_surge", False)

        score_str = str(int(score)) if score is not None else "—"
        rr_str    = f"{float(rr):.1f}×" if rr is not None else "—"
        rs_str    = str(int(rs)) if rs is not None else "—"

        # Zebra stripe
        row_bg = C_SURFACE if i % 2 == 0 else C_CARD
        vol_indicator = " 🔥" if vol_surge else ""

        body += f"""<tr style="background:{row_bg};">
            {td(f"{ticker}{vol_indicator}", color=C_GREEN, bold=True, align="left")}
            {td(score_str, color=_score_color(score))}
            {td(_fmt(entry), color=C_TEXT)}
            {td(_fmt(stop), color=C_RED)}
            {td(rr_str, color=_rr_color(rr))}
            {td(rs_str, color=_rs_color(rs))}
            {td(sector, color=C_MUTED, align="left")}
        </tr>"""

    return f"""<table style="width:100%;border-collapse:collapse;font-family:'Courier New',monospace;">
        <thead>{header}</thead>
        <tbody>{body}</tbody>
    </table>"""


# ── Section builder ───────────────────────────────────────────────────────────

def _section(title: str, color: str, setups: List[Dict],
             limit: Optional[int] = None, note: str = "") -> str:
    """Returns empty string if setups is empty (section is hidden)."""
    if not setups:
        return ""

    shown = setups[:limit] if limit else setups
    count = len(setups)
    cap_note = f'  <span style="color:{C_MUTED};font-size:10px;">showing top {limit} of {count}</span>' if limit and count > limit else f'  <span style="color:{C_MUTED};font-size:10px;">{count} setup{"s" if count!=1 else ""}</span>'

    return f"""
    <div style="background:{C_SURFACE};border:1px solid {C_BORDER};border-radius:8px;
                margin-bottom:14px;overflow:hidden;">
        <div style="padding:11px 16px;border-bottom:1px solid {C_BORDER};
                    display:flex;align-items:center;gap:8px;">
            <span style="width:3px;height:16px;background:{color};
                         border-radius:2px;display:inline-block;flex-shrink:0;"></span>
            <span style="font-size:12px;font-weight:700;color:{color};
                         text-transform:uppercase;letter-spacing:1px;">{title}</span>
            {cap_note}
            {"<span style='font-size:10px;color:"+C_MUTED+";margin-left:4px;'>"+note+"</span>" if note else ""}
        </div>
        <div style="overflow-x:auto;">
            {_table(shown)}
        </div>
    </div>"""


# ── Regime bar ────────────────────────────────────────────────────────────────

def _regime_block(regime_data: Dict) -> str:
    score     = regime_data.get("regime_score", 0) or 0
    label     = regime_data.get("regime", "NEUTRAL").upper()
    spy_close = regime_data.get("spy_close",  0.0) or 0.0
    spy_sma50 = regime_data.get("spy_sma50",  None)

    if "AGGRESSIVE" in label or score >= 70:
        tier, tier_color, bar_color = "AGGRESSIVE", C_GREEN, C_GREEN
    elif "SELECTIVE" in label or score >= 40:
        tier, tier_color, bar_color = "SELECTIVE", C_AMBER, C_AMBER
    else:
        tier, tier_color, bar_color = "DEFENSIVE", C_RED, C_RED

    bar_width = max(4, min(100, int(score)))

    spy_line = ""
    if spy_close:
        diff = ""
        if spy_sma50:
            pct  = (spy_close - spy_sma50) / spy_sma50 * 100
            diff_color = C_GREEN if pct >= 0 else C_RED
            diff = f' &nbsp;<span style="color:{diff_color};font-size:11px;">{"▲" if pct>=0 else "▼"}{abs(pct):.1f}% vs SMA50</span>'
        spy_line = f'<div style="margin-top:6px;font-size:12px;color:{C_MUTED};">SPY <span style="color:{C_TEXT};font-weight:600;">${spy_close:.2f}</span>{diff}</div>'

    return f"""
    <div style="background:{C_SURFACE};border:1px solid {C_BORDER};border-radius:8px;
                padding:16px 20px;margin-bottom:14px;">
        <div style="display:flex;align-items:center;justify-content:space-between;flex-wrap:wrap;gap:8px;">
            <div>
                <span style="font-size:11px;color:{C_MUTED};text-transform:uppercase;
                             letter-spacing:1px;">Market Regime</span>
                <div style="margin-top:4px;display:flex;align-items:baseline;gap:10px;">
                    <span style="font-size:22px;font-weight:700;color:{tier_color};
                                 letter-spacing:0.5px;">{tier}</span>
                    <span style="font-size:28px;font-weight:800;color:{tier_color};">{int(score)}</span>
                    <span style="font-size:13px;color:{C_MUTED};">/ 100</span>
                </div>
            </div>
            <div style="text-align:right;">
                {spy_line}
            </div>
        </div>
        <!-- score bar -->
        <div style="margin-top:12px;background:{C_CARD};border-radius:4px;height:6px;overflow:hidden;">
            <div style="width:{bar_width}%;height:100%;background:{bar_color};
                        border-radius:4px;transition:width 0.3s;"></div>
        </div>
        <div style="display:flex;justify-content:space-between;margin-top:4px;">
            <span style="font-size:9px;color:{C_MUTED};">0 — DEFENSIVE</span>
            <span style="font-size:9px;color:{C_MUTED};">40 — SELECTIVE</span>
            <span style="font-size:9px;color:{C_MUTED};">70 — AGGRESSIVE — 100</span>
        </div>
    </div>"""


# ── Main HTML builder ─────────────────────────────────────────────────────────

def build_html_email(scan_results: Dict, label: str = "Morning Digest") -> str:
    et_tz    = ZoneInfo("America/New_York")
    now_et   = datetime.now(et_tz)
    date_str = now_et.strftime("%A, %B %-d %Y")
    time_str = now_et.strftime("%-I:%M %p ET")

    regime_data = scan_results.get("regime") or {}

    vcp_setups  = scan_results.get("vcp")              or []
    dry_setups  = scan_results.get("vcp_dry")          or []
    res_setups  = scan_results.get("res_breakout")     or []
    pb_setups   = scan_results.get("pullback")         or []
    htf_setups  = scan_results.get("htf")              or []
    lce_setups  = scan_results.get("lce")              or []
    opt_setups  = scan_results.get("options_catalyst") or []

    total = len(vcp_setups) + len(res_setups) + len(pb_setups) + len(htf_setups) + len(lce_setups) + len(opt_setups)

    # Summary pills (only non-zero)
    pills_html = ""
    pill_items = [
        ("VCP",  C_AMBER,  len(vcp_setups)),
        ("BRK",  C_GREEN,  len(res_setups)),
        ("HTF",  C_PINK,   len(htf_setups)),
        ("PB",   C_BLUE,   len(pb_setups)),
        ("LCE",  C_PURPLE, len(lce_setups)),
        ("OPT",  C_MUTED,  len(opt_setups)),
        ("WATCH",C_MUTED,  len(dry_setups)),
    ]
    for label, color, count in pill_items:
        if count > 0:
            pills_html += f"""<span style="display:inline-block;padding:3px 10px;
                border-radius:12px;background:{color}18;border:1px solid {color}40;
                color:{color};font-size:11px;font-weight:700;margin:2px;">{label} {count}</span>"""

    html = f"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>Swing Trading Digest — {date_str}</title>
</head>
<body style="margin:0;padding:0;background:{C_BG};font-family:'Segoe UI',Arial,sans-serif;color:{C_TEXT};">
<div style="max-width:680px;margin:0 auto;padding:20px 12px;">

  <!-- Header -->
  <div style="margin-bottom:14px;">
    <div style="font-size:11px;color:{C_MUTED};text-transform:uppercase;letter-spacing:1.5px;margin-bottom:4px;">
      Swing Trading Dashboard
    </div>
    <div style="font-size:24px;font-weight:700;color:{C_TEXT};letter-spacing:-0.3px;">
      {label}
    </div>
    <div style="font-size:12px;color:{C_MUTED};margin-top:2px;">{date_str} &nbsp;·&nbsp; {time_str}</div>
  </div>

  <!-- Regime block -->
  {_regime_block(regime_data)}

  <!-- Summary -->
  <div style="background:{C_SURFACE};border:1px solid {C_BORDER};border-radius:8px;
              padding:12px 16px;margin-bottom:14px;">
    <div style="font-size:11px;color:{C_MUTED};text-transform:uppercase;letter-spacing:0.8px;margin-bottom:8px;">
      Today's Setups &nbsp;
      <span style="font-size:18px;font-weight:700;color:{C_TEXT};vertical-align:middle;">{total}</span>
    </div>
    <div style="line-height:1.8;">{pills_html if pills_html else f'<span style="color:{C_MUTED};font-size:12px;">No setups today.</span>'}</div>
  </div>

  <!-- Sections (only rendered if non-empty) -->
  {_section("VCP Breakouts", C_AMBER, vcp_setups)}
  {_section("Resistance Breakouts", C_GREEN, res_setups, limit=5)}
  {_section("High Tight Flag", C_PINK, htf_setups)}
  {_section("Pullbacks", C_BLUE, pb_setups, limit=5)}
  {_section("Low Cheat Entry", C_PURPLE, lce_setups)}
  {_section("Options Plays", C_MUTED, opt_setups)}
  {_section("Near-Breakout Watch", C_MUTED, dry_setups, limit=10, note="watchlist")}

  <!-- Footer -->
  <div style="text-align:center;font-size:10px;color:{C_MUTED};padding-top:10px;border-top:1px solid {C_BORDER};">
    Generated at {time_str} &nbsp;·&nbsp; Swing Trading Dashboard &nbsp;·&nbsp; Do not trade based on email alone.
  </div>

</div>
</body>
</html>"""

    return html


# ── SMTP sender ───────────────────────────────────────────────────────────────

def send_digest(scan_results: Dict, label: str = "Morning Digest") -> None:
    """
    Build the HTML email from scan_results and send via Gmail SMTP (port 587, STARTTLS).

    Reads credentials from environment variables (loaded from .env via systemd EnvironmentFile):
        EMAIL_FROM      — Gmail address to send from
        EMAIL_PASSWORD  — Gmail App Password (not account password)
        EMAIL_TO        — Recipient address (default: amit.izhari@gmail.com)

    Errors are logged but not re-raised so the scheduler job never crashes the server.
    """
    email_from     = os.getenv("EMAIL_FROM", "")
    email_password = os.getenv("EMAIL_PASSWORD", "")
    email_to       = os.getenv("EMAIL_TO", DEFAULT_RECIPIENT)

    if not email_from or not email_password:
        log.error(
            "Email digest skipped: EMAIL_FROM and/or EMAIL_PASSWORD not set in .env. "
            "Add Gmail credentials to send the daily digest."
        )
        return

    try:
        html_body = build_html_email(scan_results, label=label)

        et_tz    = ZoneInfo("America/New_York")
        now_et   = datetime.now(et_tz)
        date_str = now_et.strftime("%A, %B %-d %Y")

        msg = MIMEMultipart("alternative")
        msg["Subject"] = f"📊 Swing {label} — {date_str}"
        msg["From"]    = email_from
        msg["To"]      = email_to

        regime_data = scan_results.get("regime") or {}
        regime_str  = regime_data.get("regime", "UNKNOWN")
        regime_score = regime_data.get("regime_score", 0) or 0
        spy_close   = regime_data.get("spy_close", 0.0)
        total = (
            len(scan_results.get("vcp")              or []) +
            len(scan_results.get("res_breakout")     or []) +
            len(scan_results.get("pullback")         or []) +
            len(scan_results.get("htf")              or []) +
            len(scan_results.get("lce")              or []) +
            len(scan_results.get("options_catalyst") or [])
        )
        plain = (
            f"Swing Trading Digest — {date_str}\n"
            f"Regime: {regime_str} ({int(regime_score)}/100)  SPY: ${spy_close:.2f}\n"
            f"Total setups: {total}\n\n"
            "See HTML version for full details."
        )

        msg.attach(MIMEText(plain, "plain"))
        msg.attach(MIMEText(html_body, "html"))

        try:
            import certifi
            context = ssl.create_default_context(cafile=certifi.where())
        except ImportError:
            context = ssl.create_default_context()

        with smtplib.SMTP(SMTP_HOST, SMTP_PORT) as server:
            server.starttls(context=context)
            server.login(email_from, email_password)
            server.sendmail(email_from, email_to, msg.as_string())

        log.info(
            "Email digest sent to %s  (setups=%d  regime=%s  score=%d)",
            email_to, total, regime_str, int(regime_score),
        )

    except smtplib.SMTPAuthenticationError as exc:
        log.error(
            "Email digest failed: Gmail authentication error. "
            "Check EMAIL_FROM / EMAIL_PASSWORD in .env. Detail: %s", exc
        )
    except smtplib.SMTPException as exc:
        log.error("Email digest failed (SMTP error): %s", exc)
    except OSError as exc:
        log.error("Email digest failed (network error): %s", exc)
    except Exception as exc:  # noqa: BLE001
        log.exception("Email digest failed (unexpected error): %s", exc)
