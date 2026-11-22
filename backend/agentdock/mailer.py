"""Transactional email delivery with a safe development fallback."""
import logging
import smtplib
from email.message import EmailMessage

from .config import get_settings

logger = logging.getLogger("agentdock.mail")


def send_email(to: str, subject: str, text: str, html: str | None = None) -> bool:
    settings = get_settings()
    if not settings.smtp_configured:
        logger.info("Email delivery is not configured; message for %s was not sent", to)
        return False
    message = EmailMessage()
    message["From"] = settings.smtp_from
    message["To"] = to
    message["Subject"] = subject
    message.set_content(text)
    if html:
        message.add_alternative(html, subtype="html")
    try:
        with smtplib.SMTP(settings.smtp_host, settings.smtp_port, timeout=15) as server:
            if settings.smtp_starttls:
                server.starttls()
            if settings.smtp_user:
                server.login(settings.smtp_user, settings.smtp_password)
            server.send_message(message)
        return True
    except Exception as exc:  # Delivery failure must not break the account flow.
        logger.error("Email delivery failed (%s)", type(exc).__name__)
        return False


def send_verification(to: str, link: str) -> bool:
    return send_email(to, "Verify your AgentDock email",
                      f"Confirm your AgentDock email address:\n\n{link}\n\nThis link expires in 24 hours.")


def send_password_reset(to: str, link: str) -> bool:
    return send_email(to, "Reset your AgentDock password",
                      f"Reset your AgentDock password:\n\n{link}\n\nThis link expires in 60 minutes. "
                      "If you did not request it, you can ignore this message.")


def send_team_invitation(to: str, team_name: str, link: str) -> bool:
    return send_email(to, f"Join {team_name} on AgentDock",
                      f"You have been invited to {team_name} on AgentDock.\n\nAccept the invitation:\n{link}\n\n"
                      "This invitation expires in 7 days.")


def send_payment_receipt(to: str, reference: str, amount: str, description: str) -> bool:
    return send_email(to, "Your AgentDock receipt",
                      f"Payment received.\n\nReference: {reference}\nAmount: {amount}\n{description}\n\n"
                      "You can view this transaction in your AgentDock billing history.")
