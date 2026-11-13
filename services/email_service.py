import os
import smtplib
import threading
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from datetime import datetime
from dotenv import load_dotenv

load_dotenv()


def _get_smtp_config():
    host = os.getenv("SMTP_HOST", "").strip()
    port_str = os.getenv("SMTP_PORT", "").strip()
    port = int(port_str) if port_str.isdigit() else 0

    user = os.getenv("SMTP_USER", "").strip()
    password = os.getenv("SMTP_PASSWORD", "").strip()
    from_name = os.getenv("SMTP_FROM_NAME", "").strip()
    from_email = os.getenv("SMTP_FROM_EMAIL", "").strip()
    use_tls = str(os.getenv("SMTP_USE_TLS", "")).lower() in ("true", "1", "yes")

    return {
        "host": host,
        "port": port,
        "user": user,
        "password": password,
        "from_name": from_name,
        "from_email": from_email,
        "use_tls": use_tls,
        "is_configured": bool(host and user and password and port > 0),
    }


def _send_mail_worker(to_email: str, subject: str, html_body: str, text_body: str = ""):
    """Internal synchronous sender run in a daemon thread."""
    config = _get_smtp_config()

    print(f"\n{'='*65}")
    print(f"📧 [EMAIL DISPATCH] Recipient: {to_email} | Subject: '{subject}'")

    if not config["is_configured"]:
        print(f"⚠️  [EMAIL NOTICE] SMTP is not yet configured (Host/User/Password missing in .env).")
        print(f"ℹ️  [EMAIL PREVIEW] Email was instigated successfully. Content prepared for <{to_email}>.")
        print(f"{'='*65}\n")
        return

    msg = MIMEMultipart("alternative")
    msg["Subject"] = subject
    msg["From"] = f"{config['from_name']} <{config['from_email']}>"
    msg["To"] = to_email

    if text_body:
        msg.attach(MIMEText(text_body, "plain", "utf-8"))
    if html_body:
        msg.attach(MIMEText(html_body, "html", "utf-8"))

    try:
        if config["port"] == 465:
            # Direct SSL connection (standard for Port 465)
            server = smtplib.SMTP_SSL(config["host"], config["port"], timeout=15)
        else:
            # Port 587 with STARTTLS
            server = smtplib.SMTP(config["host"], config["port"], timeout=15)
            if config["use_tls"]:
                server.starttls()

        server.login(config["user"], config["password"])
        server.sendmail(config["from_email"], [to_email], msg.as_string())
        server.quit()
        print(f"✅ [EMAIL SENT] Confirmation email delivered to {to_email}")
    except Exception as e:
        print(f"❌ [EMAIL ERROR] Failed to send email to {to_email}: {e}")
    finally:
        print(f"{'='*65}\n")


def send_email_async(to_email: str, subject: str, html_body: str, text_body: str = ""):
    """Dispatches email in background daemon thread to avoid blocking HTTP latency."""
    t = threading.Thread(
        target=_send_mail_worker,
        args=(to_email, subject, html_body, text_body),
        daemon=True
    )
    t.start()


# ==============================================================================
# 1. REGISTRATION CONFIRMATION EMAIL TEMPLATE
# ==============================================================================
def send_registration_confirmation_email(email: str, full_name: str, birth_date: str = ""):
    """Sends a warm Vedic welcome and registration confirmation email to newly signed-up users."""
    display_name = full_name.strip() if full_name else "Cosmic Seeker"
    subject = "✨ Welcome to AstroJunction - Your Registration is Confirmed"

    text_body = f"""Namaste {display_name},

Welcome to AstroJunction! Your account has been successfully created.

Your registered email: {email}
{f'Registered Date of Birth: {birth_date}' if birth_date else ''}

What awaits you in AstroJunction:
- Personalized Vedic Janma Kundli (Lagna & Navamsha charts)
- Daily Ephemeris-backed Panchang & Transit Forecasts
- Authentic Daivajna Counsellor for real-time guidance
- Numerology & Compatibility Reports

Visit your dashboard: https://astrojunction.in/

May the celestial planets guide your path with wisdom and prosperity.

Warm regards,
Team AstroJunction
"""

    html_body = f"""<!DOCTYPE html>
<html>
<head>
  <meta charset="utf-8">
  <title>Welcome to AstroJunction</title>
</head>
<body style="margin: 0; padding: 0; background-color: #F4F5F7; font-family: 'Helvetica Neue', Helvetica, Arial, sans-serif; color: #1F2937;">
  <table role="presentation" width="100%" cellspacing="0" cellpadding="0" style="background-color: #F4F5F7; padding: 30px 10px;">
    <tr>
      <td align="center">
        <!-- Main Card -->
        <table role="presentation" width="600" cellspacing="0" cellpadding="0" style="background-color: #FFFFFF; border: 1px solid #E5E7EB; border-top: 5px solid #C9A050; border-radius: 12px; overflow: hidden; box-shadow: 0 4px 20px rgba(0,0,0,0.06);">
          
          <!-- Header Banner -->
          <tr>
            <td style="padding: 32px 30px; text-align: center; background: #FFFDF8; border-bottom: 1px solid #F0ECE1;">
              <div style="font-size: 26px; font-weight: bold; letter-spacing: 2px; color: #1F2937; text-transform: uppercase;">
                ASTRO<span style="color: #C9A050;">JUNCTION</span>
              </div>
              <div style="font-size: 11px; letter-spacing: 3px; color: #94691E; text-transform: uppercase; margin-top: 5px; font-weight: 600;">
                Authentic Vedic Astrology &amp; Celestial Wisdom
              </div>
            </td>
          </tr>

          <!-- Body Content -->
          <tr>
            <td style="padding: 35px 35px 25px 35px;">
              <h1 style="font-size: 22px; color: #111827; margin: 0 0 15px 0; font-weight: 600;">
                Namaste, <span style="color: #94691E;">{display_name}</span> 🙏
              </h1>
              <p style="font-size: 14px; line-height: 1.6; color: #4B5563; margin: 0 0 22px 0;">
                We are delighted to confirm that your <strong>AstroJunction</strong> account has been successfully created. Your journey into the ancient wisdom of Vedic astrology, planetary alignments, and personalized destiny begins today.
              </p>

              <!-- Account Summary Box -->
              <table role="presentation" width="100%" cellspacing="0" cellpadding="0" style="background-color: #FAF6ED; border: 1px solid #EFE4CC; border-left: 4px solid #C9A050; border-radius: 8px; padding: 16px 20px; margin-bottom: 25px;">
                <tr>
                  <td>
                    <div style="font-size: 12px; font-weight: bold; color: #94691E; text-transform: uppercase; letter-spacing: 1px; margin-bottom: 8px;">Registration Summary</div>
                    <div style="font-size: 13px; color: #1F2937; margin-bottom: 4px;">• <strong>Email:</strong> {email}</div>
                    {f'<div style="font-size: 13px; color: #1F2937; margin-bottom: 4px;">• <strong>Date of Birth:</strong> {birth_date}</div>' if birth_date else ''}
                    <div style="font-size: 13px; color: #059669; font-weight: 600;">• Status: Active &amp; Verified</div>
                  </td>
                </tr>
              </table>

              <!-- What's Unlocked -->
              <div style="font-size: 14px; font-weight: 600; color: #94691E; margin-bottom: 12px;">🌟 What You Can Explore Now:</div>
              <table role="presentation" width="100%" cellspacing="0" cellpadding="0" style="margin-bottom: 28px;">
                <tr>
                  <td style="font-size: 13px; color: #4B5563; line-height: 1.8;">
                    ✦ <strong>Personalized Janma Kundli:</strong> Exact Ascendant, Moon sign, and Graha degrees.<br>
                    ✦ <strong>Daily Panchang &amp; Muhurta:</strong> Tithi, Nakshatra, and auspicious timings calculated live.<br>
                    ✦ <strong>Daivajna Astrologer:</strong> Real-time guidance rooted in authentic Brihat Parashara principles.<br>
                    ✦ <strong>Vedic Numerology:</strong> Uncover your Mulank, Bhagyank, and harmonious frequencies.
                  </td>
                </tr>
              </table>

              <!-- Call to Action Button -->
              <div style="text-align: center; margin-bottom: 25px;">
                <a href="https://astrojunction.in/" style="display: inline-block; background: linear-gradient(135deg, #C9A050 0%, #A67C28 100%); color: #FFFFFF; text-decoration: none; font-size: 14px; font-weight: bold; padding: 13px 32px; border-radius: 8px; letter-spacing: 0.5px; box-shadow: 0 4px 15px rgba(201,160,80,0.35);">
                  Open AstroJunction Dashboard &rarr;
                </a>
              </div>

              <p style="font-size: 12px; color: #6B7280; line-height: 1.5; margin: 0; text-align: center;">
                If you did not initiate this registration, please contact our security team immediately at support@astrojunction.in.
              </p>
            </td>
          </tr>

          <!-- Footer -->
          <tr>
            <td style="background-color: #F9FAFB; padding: 22px 30px; text-align: center; border-top: 1px solid #E5E7EB; font-size: 11px; color: #6B7280;">
              &copy; {datetime.utcnow().year} AstroJunction. All sacred astrological wisdom preserved.<br>
              This is an automated confirmation of account creation.
            </td>
          </tr>

        </table>
      </td>
    </tr>
  </table>
</body>
</html>"""

    send_email_async(email, subject, html_body, text_body)


# ==============================================================================
# 2. SUBSCRIPTION / PAYMENT CONFIRMATION EMAIL TEMPLATE
# ==============================================================================
def send_subscription_confirmation_email(
    email: str,
    full_name: str,
    plan_name: str,
    amount: float,
    currency: str,
    order_id: str,
    payment_id: str,
    invoice_date: str = None
):
    """Sends a detailed payment receipt and premium subscription confirmation email."""
    display_name = full_name.strip() if full_name else "Valued Seeker"
    date_str = invoice_date or datetime.utcnow().strftime("%d %B %Y, %I:%M %p UTC")
    currency_symbol = "₹" if currency.upper() in ("INR", "RS") else ("$" if currency.upper() == "USD" else currency)
    subject = f"💎 Payment Confirmed: Welcome to AstroJunction Premium ({plan_name})"

    text_body = f"""Namaste {display_name},

Thank you for your purchase! Your AstroJunction Premium subscription has been successfully activated.

Subscription Details:
- Item / Plan: {plan_name}
- Amount Paid: {currency_symbol}{amount:.2f} {currency.upper()}
- Payment ID: {payment_id}
- Order ID: {order_id}
- Date: {date_str}

Unlocked Premium Benefits:
- Comprehensive Master Vedic Life Report (All 4 Pillars)
- Unlimited In-depth Daivajna Consultations
- Complete Planetary Dasha & Gochara Transit Timeline
- Full Remedies, Gemstone & Mantra Prescription

Access your premium dashboard: https://astrojunction.in/

Thank you for trusting AstroJunction on your spiritual and astrological journey.

Warm regards,
Team AstroJunction
"""

    html_body = f"""<!DOCTYPE html>
<html>
<head>
  <meta charset="utf-8">
  <title>Payment & Subscription Confirmed</title>
</head>
<body style="margin: 0; padding: 0; background-color: #F4F5F7; font-family: 'Helvetica Neue', Helvetica, Arial, sans-serif; color: #1F2937;">
  <table role="presentation" width="100%" cellspacing="0" cellpadding="0" style="background-color: #F4F5F7; padding: 30px 10px;">
    <tr>
      <td align="center">
        <!-- Main Card -->
        <table role="presentation" width="600" cellspacing="0" cellpadding="0" style="background-color: #FFFFFF; border: 1px solid #E5E7EB; border-top: 5px solid #C9A050; border-radius: 12px; overflow: hidden; box-shadow: 0 4px 20px rgba(0,0,0,0.06);">
          
          <!-- Header Banner -->
          <tr>
            <td style="padding: 32px 30px; text-align: center; background: #FFFDF8; border-bottom: 1px solid #F0ECE1;">
              <div style="font-size: 26px; font-weight: bold; letter-spacing: 2px; color: #1F2937; text-transform: uppercase;">
                ASTRO<span style="color: #C9A050;">JUNCTION</span>
              </div>
              <div style="font-size: 11px; letter-spacing: 3px; color: #94691E; text-transform: uppercase; margin-top: 5px; font-weight: 600;">
                Official Payment Receipt &amp; Subscription Confirmation
              </div>
            </td>
          </tr>

          <!-- Body Content -->
          <tr>
            <td style="padding: 35px 35px 25px 35px;">
              <div style="text-align: center; margin-bottom: 20px;">
                <span style="display: inline-block; background-color: #ECFDF5; color: #059669; border: 1px solid #A7F3D0; padding: 6px 16px; border-radius: 20px; font-size: 12px; font-weight: bold; text-transform: uppercase; letter-spacing: 1px;">
                  ✓ Payment Successful
                </span>
              </div>

              <h1 style="font-size: 20px; color: #111827; margin: 0 0 10px 0; font-weight: 600; text-align: center;">
                Thank you, <span style="color: #94691E;">{display_name}</span>!
              </h1>
              <p style="font-size: 13px; line-height: 1.6; color: #4B5563; margin: 0 0 25px 0; text-align: center;">
                Your premium access has been unlocked. Below are your official payment details for your records.
              </p>

              <!-- Invoice Details Table -->
              <table role="presentation" width="100%" cellspacing="0" cellpadding="0" style="background-color: #FFFFFF; border: 1px solid #E5E7EB; border-radius: 8px; margin-bottom: 25px; overflow: hidden;">
                <tr style="border-bottom: 1px solid #F3F4F6;">
                  <td style="padding: 12px 18px; font-size: 12px; color: #6B7280; font-weight: 500;">Plan / Item</td>
                  <td style="padding: 12px 18px; font-size: 13px; color: #94691E; font-weight: bold; text-align: right;">{plan_name}</td>
                </tr>
                <tr style="border-bottom: 1px solid #F3F4F6;">
                  <td style="padding: 12px 18px; font-size: 12px; color: #6B7280; font-weight: 500;">Amount Paid</td>
                  <td style="padding: 12px 18px; font-size: 15px; color: #059669; font-weight: bold; text-align: right;">{currency_symbol}{amount:.2f} {currency.upper()}</td>
                </tr>
                <tr style="border-bottom: 1px solid #F3F4F6;">
                  <td style="padding: 12px 18px; font-size: 12px; color: #6B7280; font-weight: 500;">Payment ID</td>
                  <td style="padding: 12px 18px; font-size: 12px; font-family: monospace; color: #1F2937; text-align: right;">{payment_id}</td>
                </tr>
                <tr style="border-bottom: 1px solid #F3F4F6;">
                  <td style="padding: 12px 18px; font-size: 12px; color: #6B7280; font-weight: 500;">Order ID</td>
                  <td style="padding: 12px 18px; font-size: 12px; font-family: monospace; color: #1F2937; text-align: right;">{order_id}</td>
                </tr>
                <tr>
                  <td style="padding: 12px 18px; font-size: 12px; color: #6B7280; font-weight: 500;">Date &amp; Time</td>
                  <td style="padding: 12px 18px; font-size: 12px; color: #1F2937; text-align: right;">{date_str}</td>
                </tr>
              </table>

              <!-- Unlocked Features -->
              <div style="font-size: 13px; font-weight: 600; color: #94691E; margin-bottom: 10px;">👑 Premium Features Now Available:</div>
              <ul style="font-size: 13px; color: #4B5563; line-height: 1.8; margin: 0 0 25px 0; padding-left: 20px;">
                <li><strong>Comprehensive Full Vedic Report:</strong> Download multi-pillar natal charts and deep analysis.</li>
                <li><strong>Priority Daivajna Counsellor:</strong> Unlimited consultation with advanced Vedic astrological context.</li>
                <li><strong>Deep Transit &amp; Dasha Milestones:</strong> 10-year major life timeline and timing of events.</li>
                <li><strong>Personalized Vedic Remedies:</strong> Custom gemstones, rudraksha, and yantra recommendations.</li>
              </ul>

              <!-- CTA -->
              <div style="text-align: center; margin-bottom: 20px;">
                <a href="https://astrojunction.in/" style="display: inline-block; background: linear-gradient(135deg, #C9A050 0%, #A67C28 100%); color: #FFFFFF; text-decoration: none; font-size: 14px; font-weight: bold; padding: 13px 32px; border-radius: 8px; letter-spacing: 0.5px; box-shadow: 0 4px 15px rgba(201,160,80,0.35);">
                  Explore Your Premium Benefits &rarr;
                </a>
              </div>
            </td>
          </tr>

          <!-- Footer -->
          <tr>
            <td style="background-color: #F9FAFB; padding: 20px 30px; text-align: center; border-top: 1px solid #E5E7EB; font-size: 11px; color: #6B7280;">
              &copy; {datetime.utcnow().year} AstroJunction. All rights reserved.<br>
              Need assistance? Email support@astrojunction.in with your Order ID.
            </td>
          </tr>

        </table>
      </td>
    </tr>
  </table>
</body>
</html>"""

    send_email_async(email, subject, html_body, text_body)


# ==============================================================================
# 3. DAILY ZODIAC & CATEGORY INSIGHTS EMAIL TEMPLATE
# ==============================================================================
CATEGORY_DISPLAY_NAMES = {
    "health": "Health",
    "wealth": "Wealth",
    "relationship": "Relationship",
    "love_line": "Love Line",
    "education": "Education",
    "professional": "Professional",
    "travel": "Travel"
}

CATEGORY_ICONS = {
    "health": "🌿",
    "wealth": "🪙",
    "relationship": "🤝",
    "love_line": "❤️",
    "education": "🎓",
    "professional": "💼",
    "travel": "✈️"
}


def get_email_color_badge(score: int):
    s = max(0, min(100, int(score)))
    if s >= 80:
        return {
            "name": "Green",
            "label": "Excellent / Highly Favourable",
            "color": "#16a34a",
            "bg": "#f0fdf4",
            "border": "#bbf7d0"
        }
    elif s >= 60:
        return {
            "name": "Emerald",
            "label": "Good / Favourable",
            "color": "#059669",
            "bg": "#ecfdf5",
            "border": "#a7f3d0"
        }
    elif s >= 40:
        return {
            "name": "Yellow",
            "label": "Average / Moderate",
            "color": "#d97706",
            "bg": "#fffbeb",
            "border": "#fde68a"
        }
    elif s >= 20:
        return {
            "name": "Orange",
            "label": "Challenging",
            "color": "#ea580c",
            "bg": "#fff7ed",
            "border": "#fed7aa"
        }
    else:
        return {
            "name": "Red",
            "label": "Unfavourable",
            "color": "#dc2626",
            "bg": "#fef2f2",
            "border": "#fecaca"
        }


def send_daily_zodiac_insight_email(
    email: str,
    zodiac_sign: str,
    daily_data: dict,
    preferred_categories: list = None
):
    """
    Sends a personalized daily horoscope update to subscribed users with their
    selected zodiac sign, preferred categories, percentage scores, and color indicators.
    """
    sign_name = (zodiac_sign or "Aries").strip().title()
    date_str = datetime.utcnow().strftime("%A, %d %B %Y")
    subject = f"✨ {sign_name} Horizon: Today's Cosmic Pulse & Category Insights ({datetime.utcnow().strftime('%b %d, %Y')})"

    forecast_text = daily_data.get("forecast") or f"Auspicious cosmic planetary transits guide {sign_name} with heightened intuition and steady vital progress today."
    tip_for_the_day = (
        daily_data.get("tip_for_the_day") or
        daily_data.get("categoryInsights", {}).get("cosmic_pulse", {}).get("tip_for_the_day")
    )
    if tip_for_the_day:
        tip_for_the_day = str(tip_for_the_day).strip()

    vitality = daily_data.get("vitalityToday", 88)
    affirmation = daily_data.get("affirmation") or "I step forward with clarity and courage, trusting my inner wisdom."
    resonant_chakra = daily_data.get("resonantChakra") or "Solar Plexus (Manipura)"

    category_insights = daily_data.get("categoryInsights") or {}
    if not preferred_categories or len(preferred_categories) == 0:
        target_cats = list(CATEGORY_DISPLAY_NAMES.keys())
    else:
        target_cats = [c.lower().strip() for c in preferred_categories if c.lower().strip() in CATEGORY_DISPLAY_NAMES]
        if not target_cats:
            target_cats = list(CATEGORY_DISPLAY_NAMES.keys())

    # Build HTML for category sections
    category_cards_html = ""
    category_text_lines = []

    for cat_key in target_cats:
        cat_info = category_insights.get(cat_key) or {}
        score = cat_info.get("score", 75)
        insight = cat_info.get("insight") or "Favorable planetary transits indicate steady progress and positive developments today."
        transit_aspect = cat_info.get("transitAspect") or "Harmonious Celestial Aspect"

        badge = get_email_color_badge(score)
        display_name = CATEGORY_DISPLAY_NAMES.get(cat_key, cat_key.title())
        icon = CATEGORY_ICONS.get(cat_key, "✦")

        category_text_lines.append(
            f"• {display_name} ({score}% - {badge['label']}):\n  {insight}\n  Transit: {transit_aspect}\n"
        )

        category_cards_html += f"""
        <table role="presentation" width="100%" cellspacing="0" cellpadding="0" style="background-color: #FFFFFF; border: 1px solid #EAE5D9; border-radius: 10px; margin-bottom: 16px; overflow: hidden; box-shadow: 0 2px 6px rgba(0,0,0,0.02);">
          <tr>
            <td style="padding: 16px 20px;">
              <table role="presentation" width="100%" cellspacing="0" cellpadding="0">
                <tr>
                  <td align="left">
                    <span style="font-size: 15px; font-weight: bold; color: #111827;">{icon} {display_name}</span>
                  </td>
                  <td align="right">
                    <span style="display: inline-block; padding: 4px 10px; font-size: 11px; font-weight: bold; font-family: monospace; border-radius: 20px; background-color: {badge['bg']}; color: {badge['color']}; border: 1px solid {badge['border']};">
                      <span style="display: inline-block; width: 6px; height: 6px; border-radius: 50%; background-color: {badge['color']}; margin-right: 4px;"></span>
                      {score}% • {badge['label']}
                    </span>
                  </td>
                </tr>
              </table>
              <div style="font-size: 11px; color: #8D6723; font-family: monospace; margin-top: 6px; margin-bottom: 8px;">
                ✦ {transit_aspect}
              </div>
              <p style="font-size: 13px; line-height: 1.6; color: #374151; margin: 0; white-space: pre-line;">
                {insight}
              </p>
            </td>
          </tr>
        </table>
        """

    tip_text_section = f"\nTip for the Day:\n{tip_for_the_day}\n" if tip_for_the_day else ""
    tip_html_section = f"""
              <div style="background-color: #FBF8F1; border: 1px solid #E5DBC7; border-radius: 8px; padding: 12px 16px; margin: 0 0 16px 0;">
                <div style="font-size: 11px; font-weight: bold; text-transform: uppercase; letter-spacing: 1px; color: #8D6723; margin-bottom: 4px;">Tip for the Day:</div>
                <p style="font-size: 13px; line-height: 1.5; color: #1F2937; margin: 0;">{tip_for_the_day}</p>
              </div>""" if tip_for_the_day else ""

    text_body = f"""ASTROJUNCTION - TODAY'S COSMIC PULSE
Sign: {sign_name} Horizon
Date: {date_str}

OVERALL COSMIC OUTLOOK ({vitality}% Vitality):
{forecast_text}
{tip_text_section}
Celestial Affirmation: "{affirmation}"
Resonant Chakra: {resonant_chakra}

CATEGORY-WISE DAILY INSIGHTS:
{"".join(category_text_lines)}

Auspicious Resonances:
• Lucky Gemstone: {daily_data.get('luckyGemstone', 'Red Coral')}
• Lucky Color: {daily_data.get('luckyColor', 'Deep Red')}
• Lucky Day: {daily_data.get('luckyDay', 'Tuesday')}
• Power Numbers: {daily_data.get('powerNumbers', '3, 7, 9')}

Visit your interactive dashboard: https://astrojunction.in/
To manage preferences or unsubscribe, visit your AstroJunction profile.
"""

    html_body = f"""<!DOCTYPE html>
<html>
<head>
  <meta charset="utf-8">
  <title>{sign_name} Horizon - Daily Cosmic Pulse</title>
</head>
<body style="margin: 0; padding: 0; background-color: #FAF7F2; font-family: 'Helvetica Neue', Helvetica, Arial, sans-serif; color: #1F2937;">
  <table role="presentation" width="100%" cellspacing="0" cellpadding="0" style="background-color: #FAF7F2; padding: 30px 10px;">
    <tr>
      <td align="center">
        <!-- Main Container -->
        <table role="presentation" width="620" cellspacing="0" cellpadding="0" style="background-color: #FFFFFF; border: 1px solid #E8E1D5; border-top: 5px solid #C9A050; border-radius: 14px; overflow: hidden; box-shadow: 0 4px 24px rgba(201,160,80,0.08);">
          
          <!-- Header Banner -->
          <tr>
            <td style="padding: 28px 30px; text-align: center; background: #FFFDF9; border-bottom: 1px solid #EFEAE0;">
              <div style="font-size: 24px; font-weight: bold; letter-spacing: 2px; color: #1F2937; text-transform: uppercase;">
                ASTRO<span style="color: #C9A050;">JUNCTION</span>
              </div>
              <div style="font-size: 10px; letter-spacing: 3px; color: #8D6723; text-transform: uppercase; margin-top: 4px; font-weight: 600;">
                Today's Cosmic Pulse • {date_str}
              </div>
            </td>
          </tr>

          <!-- Zodiac Spotlight Banner -->
          <tr>
            <td style="padding: 24px 30px 10px 30px;">
              <table role="presentation" width="100%" cellspacing="0" cellpadding="0" style="background: linear-gradient(135deg, #FBF8F1 0%, #F5EEDB 100%); border: 1px solid #E5DBC7; border-radius: 12px; padding: 18px 22px;">
                <tr>
                  <td>
                    <div style="font-size: 11px; text-transform: uppercase; letter-spacing: 1.5px; color: #8D6723; font-weight: bold;">Daily Horizon Reading</div>
                    <div style="font-size: 22px; font-weight: bold; color: #1A1816; margin-top: 2px; font-family: Georgia, serif;">
                      {sign_name} Horizon
                    </div>
                  </td>
                  <td align="right">
                    <div style="display: inline-block; background-color: #C9A050; color: #0D0D0F; font-weight: bold; font-size: 14px; padding: 6px 14px; border-radius: 20px; font-family: monospace; box-shadow: 0 2px 8px rgba(201,160,80,0.3);">
                      {vitality}% Vitality
                    </div>
                  </td>
                </tr>
              </table>
            </td>
          </tr>

          <!-- Forecast Summary Box -->
          <tr>
            <td style="padding: 10px 30px 20px 30px;">
              <p style="font-size: 14px; line-height: 1.7; color: #374151; margin: 0 0 16px 0;">
                {forecast_text}
              </p>
              {tip_html_section}

              <!-- Affirmation & Chakra Strip -->
              <table role="presentation" width="100%" cellspacing="0" cellpadding="0" style="background-color: #F8F5EE; border-left: 3px solid #C9A050; border-radius: 6px; padding: 12px 16px; margin-bottom: 20px;">
                <tr>
                  <td style="font-size: 12px; color: #4B5563; line-height: 1.5;">
                    <strong style="color: #8D6723;">Celestial Affirmation:</strong> <em>&ldquo;{affirmation}&rdquo;</em><br>
                    <strong style="color: #8D6723;">Resonant Chakra:</strong> {resonant_chakra}
                  </td>
                </tr>
              </table>

              <!-- Category-Wise Insights Header -->
              <div style="font-size: 13px; font-weight: bold; color: #8D6723; text-transform: uppercase; letter-spacing: 1px; margin-bottom: 12px;">
                Category-Wise Insights &amp; Percentage Outlook:
              </div>

              <!-- Dynamic Category Cards -->
              {category_cards_html}

              <!-- Auspicious Resonances Strip -->
              <table role="presentation" width="100%" cellspacing="0" cellpadding="0" style="background-color: #FAF8F3; border: 1px solid #ECE4D4; border-radius: 8px; padding: 14px 18px; margin-top: 15px; margin-bottom: 25px;">
                <tr>
                  <td style="font-size: 12px; color: #4B5563; line-height: 1.7;">
                    <div style="font-weight: bold; color: #8D6723; margin-bottom: 4px;">✦ Auspicious Cosmic Resonances:</div>
                    <strong>Lucky Gemstone:</strong> {daily_data.get('luckyGemstone', 'Red Coral')} &bull;
                    <strong>Lucky Color:</strong> {daily_data.get('luckyColor', 'Deep Red')} &bull;
                    <strong>Favorable Day:</strong> {daily_data.get('luckyDay', 'Tuesday')} &bull;
                    <strong>Power Numbers:</strong> {daily_data.get('powerNumbers', '3, 7, 9')}
                  </td>
                </tr>
              </table>

              <!-- CTA Button -->
              <div style="text-align: center; margin-bottom: 15px;">
                <a href="https://astrojunction.in/" style="display: inline-block; background: linear-gradient(135deg, #D4AF37 0%, #C9A050 100%); color: #0D0D0F; text-decoration: none; font-size: 13px; font-weight: bold; padding: 12px 28px; border-radius: 8px; letter-spacing: 0.5px; box-shadow: 0 4px 15px rgba(201,160,80,0.25);">
                  View Interactive Global Zodiac Dashboard &rarr;
                </a>
              </div>
            </td>
          </tr>

          <!-- Footer -->
          <tr>
            <td style="background-color: #F8F5EE; padding: 20px 30px; text-align: center; border-top: 1px solid #EBE4D6; font-size: 11px; color: #78716C; line-height: 1.5;">
              You received this daily update because you subscribed on AstroJunction for <strong>{sign_name} Horizon</strong>.<br>
              &copy; {datetime.utcnow().year} AstroJunction. All sacred astrological wisdom preserved.<br>
              To change your preferred categories or sign, visit your AstroJunction settings.
            </td>
          </tr>

        </table>
      </td>
    </tr>
  </table>
</body>
</html>"""

    send_email_async(email, subject, html_body, text_body)

