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

Visit your dashboard: https://astrojunction.com

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
                <a href="https://astrojunction.com" style="display: inline-block; background: linear-gradient(135deg, #C9A050 0%, #A67C28 100%); color: #FFFFFF; text-decoration: none; font-size: 14px; font-weight: bold; padding: 13px 32px; border-radius: 8px; letter-spacing: 0.5px; box-shadow: 0 4px 15px rgba(201,160,80,0.35);">
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

Access your premium dashboard: https://astrojunction.com

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
                <a href="https://astrojunction.com" style="display: inline-block; background: linear-gradient(135deg, #C9A050 0%, #A67C28 100%); color: #FFFFFF; text-decoration: none; font-size: 14px; font-weight: bold; padding: 13px 32px; border-radius: 8px; letter-spacing: 0.5px; box-shadow: 0 4px 15px rgba(201,160,80,0.35);">
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
