"""
email_digest.py — Daily Swing Trading Email Digest
====================================================
Builds a dark-themed HTML email summarising today's scan results and sends
it via Gmail SMTP (port 465, SSL).

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
            "regime":     "BULLISH" | "BEARISH" | "NEUTRAL" | "NO_DATA",
            "spy_close":  float,
            "spy_sma50":  float,  # optional, used for BULL/BEAR badge
            "is_bullish": bool,
        },
        "vcp":              [ {ticker, entry, stop_loss, rr, rs_score, ...}, ... ],
        "vcp_dry":          [ {ticker, entry, stop_loss, rr, rs_score, ...}, ... ],
        "res_breakout":     [ {ticker, entry, stop_loss, rr, rs_score, ...}, ... ],
        "pullback":         [ {ticker, entry, stop_loss, rr, rs_score, ...}, ... ],
        "options_catalyst": [ {ticker, entry, stop_loss, rr, rs_score, ...}, ... ],
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

# ── Constants ────────────────────────────────────────────────────────────────

SMTP_HOST = "smtp.gmail.com"
SMTP_PORT = 465
DEFAULT_RECIPIENT = "amit.izhari@gmail.com"

# Dark-theme palette
COLOR_BG        = "#1a1a1a"
COLOR_SURFACE   = "#252525"
COLOR_BORDER    = "#333333"
COLOR_TEXT      = "#e0e0e0"
COLOR_MUTED     = "#999999"
COLOR_GREEN     = "#00ff88"
COLOR_RED       = "#ff4d4d"
COLOR_AMBER     = "#ffaa00"
COLOR_BLUE      = "#4da6ff"


# ── HTML builder ─────────────────────────────────────────────────────────────

def build_html_email(scan_results: Dict) -> str:
    """
    Build and return a dark-themed HTML email string from scan_results.

    Parameters
    ----------
    scan_results : dict
        Keys: regime, vcp, vcp_dry, res_breakout, pullback, options_catalyst
        Any missing key falls back to an empty list / default regime.
    """
    et_tz = ZoneInfo("America/New_York")
    now_et = datetime.now(et_tz)
    date_str = now_et.strftime("%A, %B %-d %Y")
    time_str = now_et.strftime("%-I:%M %p ET")

    regime_data: Dict = scan_results.get("regime") or {}
    spy_close   = regime_data.get("spy_close",  0.0)
    spy_sma50   = regime_data.get("spy_sma50",  None)
    is_bullish  = regime_data.get("is_bullish", False)
    regime_str  = regime_data.get("regime", "NEUTRAL")

    # Derive BULL / BEAR / NEUTRAL badge
    if regime_str.upper().startswith("BULL") or is_bullish:
        badge_label = "BULL"
        badge_color = COLOR_GREEN
    elif regime_str.upper().startswith("BEAR"):
        badge_label = "BEAR"
        badge_color = COLOR_RED
    else:
        badge_label = "NEUTRAL"
        badge_color = COLOR_AMBER

    vcp_setups      = scan_results.get("vcp")              or []
    vcp_dry_setups  = scan_results.get("vcp_dry")          or []
    res_setups      = scan_results.get("res_breakout")      or []
    pb_setups       = scan_results.get("pullback")          or []
    opt_setups      = scan_results.get("options_catalyst")  or []

    total_setups = (
        len(vcp_setups) + len(vcp_dry_setups) +
        len(res_setups) + len(pb_setups) + len(opt_setups)
    )

    # ── Global styles ─────────────────────────────────────────────────────────
    css = f"""
        body {{ margin:0; padding:0; background:{COLOR_BG}; font-family:'Segoe UI',Arial,sans-serif; color:{COLOR_TEXT}; }}
        .wrapper {{ max-width:700px; margin:0 auto; padding:20px 10px; }}
        .header {{ background:{COLOR_SURFACE}; border:1px solid {COLOR_BORDER}; border-radius:8px;
                   padding:20px 24px; margin-bottom:16px; }}
        .header h1 {{ margin:0 0 6px; font-size:22px; color:{COLOR_GREEN}; letter-spacing:0.5px; }}
        .header .sub {{ font-size:13px; color:{COLOR_MUTED}; margin:0; }}
        .badge {{ display:inline-block; padding:4px 10px; border-radius:4px; font-size:12px;
                  font-weight:700; letter-spacing:1px; color:#000;
                  background:{badge_color}; margin-left:10px; vertical-align:middle; }}
        .spy-info {{ font-size:13px; color:{COLOR_MUTED}; margin-top:8px; }}
        .section {{ background:{COLOR_SURFACE}; border:1px solid {COLOR_BORDER}; border-radius:8px;
                    padding:16px 20px; margin-bottom:14px; }}
        .section-title {{ font-size:14px; font-weight:700; color:{COLOR_GREEN};
                          text-transform:uppercase; letter-spacing:1px; margin:0 0 12px; }}
        .empty {{ font-size:13px; color:{COLOR_MUTED}; font-style:italic; }}
        table {{ width:100%; border-collapse:collapse; font-size:13px; }}
        th {{ text-align:left; padding:6px 8px; border-bottom:1px solid {COLOR_BORDER};
              color:{COLOR_MUTED}; font-weight:600; font-size:11px; text-transform:uppercase;
              letter-spacing:0.5px; }}
        td {{ padding:7px 8px; border-bottom:1px solid {COLOR_BORDER}; color:{COLOR_TEXT}; vertical-align:middle; }}
        tr:last-child td {{ border-bottom:none; }}
        .ticker {{ font-weight:700; color:{COLOR_GREEN}; font-size:14px; }}
        .num {{ font-family:'Courier New',monospace; }}
        .rs-high {{ color:{COLOR_GREEN}; font-weight:600; }}
        .rs-mid  {{ color:{COLOR_AMBER}; }}
        .rs-low  {{ color:{COLOR_MUTED}; }}
        .rr-good {{ color:{COLOR_GREEN}; font-weight:600; }}
        .rr-ok   {{ color:{COLOR_TEXT}; }}
        .footer  {{ font-size:11px; color:{COLOR_MUTED}; text-align:center; padding-top:12px; }}
        .summary {{ background:{COLOR_BG}; border:1px solid {COLOR_BORDER}; border-radius:6px;
                    padding:10px 16px; margin-bottom:16px; font-size:13px; }}
        .summary span {{ color:{COLOR_GREEN}; font-weight:600; }}
    """

    # ── Section builder ───────────────────────────────────────────────────────
    def _setup_rows(setups: List[Dict], show_rr: bool = True) -> str:
        if not setups:
            return '<p class="empty">No setups found.</p>'

        headers = ["Ticker", "Entry", "Stop", "R:R", "RS Score"] if show_rr else ["Ticker", "Entry", "Stop", "RS Score"]

        th_cells = "".join(f"<th>{h}</th>" for h in headers)
        rows_html = f"<table><thead><tr>{th_cells}</tr></thead><tbody>"

        for s in setups:
            ticker   = s.get("ticker", "—")
            entry    = s.get("entry",    0.0)
            stop     = s.get("stop_loss", 0.0)
            rr       = s.get("rr",        None)
            rs_score = s.get("rs_score",  None)

            entry_str = f"{entry:.2f}" if entry else "—"
            stop_str  = f"{stop:.2f}"  if stop  else "—"

            if rr is not None:
                rr_class = "rr-good" if rr >= 2.5 else "rr-ok"
                rr_str   = f'<span class="{rr_class}">{rr:.1f}×</span>'
            else:
                rr_str = "—"

            if rs_score is not None:
                rs_class = "rs-high" if rs_score >= 80 else ("rs-mid" if rs_score >= 50 else "rs-low")
                rs_str   = f'<span class="{rs_class}">{int(rs_score)}</span>'
            else:
                rs_str = "—"

            if show_rr:
                cells = (
                    f'<td class="ticker">{ticker}</td>'
                    f'<td class="num">{entry_str}</td>'
                    f'<td class="num">{stop_str}</td>'
                    f'<td class="num">{rr_str}</td>'
                    f'<td class="num">{rs_str}</td>'
                )
            else:
                cells = (
                    f'<td class="ticker">{ticker}</td>'
                    f'<td class="num">{entry_str}</td>'
                    f'<td class="num">{stop_str}</td>'
                    f'<td class="num">{rs_str}</td>'
                )

            rows_html += f"<tr>{cells}</tr>"

        rows_html += "</tbody></table>"
        return rows_html

    def _section(title: str, setups: List[Dict], show_rr: bool = True) -> str:
        count = len(setups)
        count_badge = f' <span style="color:{COLOR_MUTED};font-weight:400;font-size:12px;">({count})</span>'
        return f"""
        <div class="section">
            <p class="section-title">{title}{count_badge}</p>
            {_setup_rows(setups, show_rr)}
        </div>"""

    # SPY SMA50 context line
    if spy_sma50 and spy_close:
        spy_vs_sma50 = "above" if spy_close >= spy_sma50 else "below"
        spy_info_html = (
            f'<p class="spy-info">SPY {spy_close:.2f} &nbsp;|&nbsp; '
            f'50-day SMA {spy_sma50:.2f} &nbsp;|&nbsp; {spy_vs_sma50} SMA50</p>'
        )
    elif spy_close:
        spy_info_html = f'<p class="spy-info">SPY {spy_close:.2f}</p>'
    else:
        spy_info_html = ""

    html = f"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>Swing Trading Digest — {date_str}</title>
<style>{css}</style>
</head>
<body>
<div class="wrapper">

  <!-- Header -->
  <div class="header">
    <h1>Swing Trading Digest
      <span class="badge">{badge_label}</span>
    </h1>
    <p class="sub">{date_str}</p>
    {spy_info_html}
  </div>

  <!-- Summary bar -->
  <div class="summary">
    <span>{total_setups}</span> setup{"s" if total_setups != 1 else ""} across all strategies &nbsp;|&nbsp;
    VCP: <span>{len(vcp_setups)}</span> &nbsp;
    VCP Dry: <span>{len(vcp_dry_setups)}</span> &nbsp;
    Resistance: <span>{len(res_setups)}</span> &nbsp;
    Pullback: <span>{len(pb_setups)}</span> &nbsp;
    Options: <span>{len(opt_setups)}</span>
  </div>

  {_section("VCP Breakouts", vcp_setups)}
  {_section("VCP Dry Setups (Near-Breakout Watchlist)", vcp_dry_setups, show_rr=False)}
  {_section("Resistance Breakouts", res_setups)}
  {_section("Pullbacks", pb_setups)}
  {_section("Options Plays", opt_setups)}

  <!-- Footer -->
  <div class="footer">
    Generated at {time_str} &nbsp;&middot;&nbsp; Swing Trading Dashboard
  </div>

</div>
</body>
</html>"""

    return html


# ── SMTP sender ───────────────────────────────────────────────────────────────

def send_digest(scan_results: Dict) -> None:
    """
    Build the HTML email from scan_results and send via Gmail SMTP (SSL, port 465).

    Reads credentials from environment variables (loaded by python-dotenv in main.py):
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
        html_body = build_html_email(scan_results)

        et_tz    = ZoneInfo("America/New_York")
        now_et   = datetime.now(et_tz)
        date_str = now_et.strftime("%A, %B %-d %Y")

        msg = MIMEMultipart("alternative")
        msg["Subject"] = f"Swing Trading Digest — {date_str}"
        msg["From"]    = email_from
        msg["To"]      = email_to

        # Plain-text fallback (minimal)
        regime_data = scan_results.get("regime") or {}
        regime_str  = regime_data.get("regime", "UNKNOWN")
        spy_close   = regime_data.get("spy_close", 0.0)
        total = (
            len(scan_results.get("vcp")              or []) +
            len(scan_results.get("vcp_dry")          or []) +
            len(scan_results.get("res_breakout")      or []) +
            len(scan_results.get("pullback")          or []) +
            len(scan_results.get("options_catalyst")  or [])
        )
        plain = (
            f"Swing Trading Digest — {date_str}\n"
            f"Regime: {regime_str}  SPY: {spy_close:.2f}\n"
            f"Total setups: {total}\n\n"
            "See HTML version for full details."
        )

        msg.attach(MIMEText(plain, "plain"))
        msg.attach(MIMEText(html_body, "html"))

        context = ssl.create_default_context()
        with smtplib.SMTP_SSL(SMTP_HOST, SMTP_PORT, context=context) as server:
            server.login(email_from, email_password)
            server.sendmail(email_from, email_to, msg.as_string())

        log.info(
            "Email digest sent to %s  (setups=%d  regime=%s)",
            email_to, total, regime_str,
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
        log.error("Email digest failed (unexpected error): %s", exc)
