"""
email_generator.py — Email Generation & Sending Module
Supports SMTP and SendGrid with HTML + plain text
"""

import smtplib
import logging
import time
from datetime import datetime
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from pathlib import Path
from typing import Optional

from jinja2 import Environment, FileSystemLoader
from tenacity import retry, stop_after_attempt, wait_exponential

logger = logging.getLogger(__name__)

TEMPLATE_DIR = Path(__file__).parent.parent / "templates"


class EmailGenerator:
    """Generates personalized HTML + plain text emails using Jinja2 templates."""

    def __init__(self, config: dict):
        self.config    = config
        self.company   = config["company"]
        self.email_cfg = config["email"]
        self.jinja_env = Environment(
            loader=FileSystemLoader(str(TEMPLATE_DIR)),
            autoescape=True
        )

    def build_context(self, post) -> dict:
        """Build template context from a LinkedInPost object."""
        # Truncate post content for snippet
        snippet = (
            post.content[:180].rstrip() + "..."
            if len(post.content) > 180
            else post.content
        )

        # Infer requirement summary from content
        summary = self._infer_summary(post.content, post.keyword_match)

        return {
            # Recipient
            "recipient_name":    post.poster_name or "Sir/Madam",
            "recipient_email":   post.contact_email,
            "company_of_buyer":  post.company_name or "your company",

            # Post context
            "requirement_summary": summary,
            "post_snippet":        snippet,

            # Sender / Our company
            "company_name":     self.company["name"],
            "company_tagline":  self.company["tagline"],
            "company_location": self.company["address"],
            "company_website":  self.company["website"],
            "catalog_url":      self.company["catalog_url"],
            "contact_email":    self.company["contact_email"],
            "contact_phone":    self.company["contact_phone"],
            "linkedin_page":    self.company["linkedin_page"],
            "company_address":  self.company["address"],

            # Certifications
            "certifications":      self.company.get("certifications", []),
            "certifications_text": ", ".join(
                self.company.get("certifications", [])
            ),

            # Compliance
            "unsubscribe_url": self.config["compliance"]["unsubscribe_url"],
            "sender_name":     self.email_cfg["from_name"],
        }

    def render(self, post) -> tuple[str, str, str]:
        """
        Render email templates for a post.

        Returns:
            Tuple of (subject, html_body, text_body)
        """
        ctx = self.build_context(post)

        subject = (
            f"Leather Goods Supply Partnership — "
            f"{self.company['name']} | {post.country_code}"
        )

        html_tmpl = self.jinja_env.get_template("email_template.html")
        txt_tmpl  = self.jinja_env.get_template("email_template.txt")

        return subject, html_tmpl.render(**ctx), txt_tmpl.render(**ctx)

    def _infer_summary(self, content: str, keyword: str) -> str:
        """Extract a concise summary of the requirement from post content."""
        content_lower = content.lower()
        if "bag" in content_lower:       return "leather bag sourcing requirements"
        if "wallet" in content_lower:    return "leather wallet procurement needs"
        if "belt" in content_lower:      return "leather belt supply requirements"
        if "export" in content_lower:    return "leather goods export opportunities"
        if "supplier" in content_lower:  return "leather supplier requirements"
        return f"{keyword} requirements"


class EmailSender:
    """Sends emails via SMTP or SendGrid with retry logic."""

    def __init__(self, config: dict):
        self.config    = config
        self.email_cfg = config["email"]
        self.use_sendgrid = self.email_cfg.get("use_sendgrid", False)

    def send(
        self,
        to_email: str,
        to_name: str,
        subject: str,
        html_body: str,
        text_body: str
    ) -> tuple[bool, str]:
        """
        Send an email to a recipient.

        Returns:
            (success: bool, message_id_or_error: str)
        """
        if self.use_sendgrid:
            return self._send_sendgrid(
                to_email, to_name, subject, html_body, text_body
            )
        else:
            return self._send_smtp(
                to_email, to_name, subject, html_body, text_body
            )

    @retry(
        stop=stop_after_attempt(3),
        wait=wait_exponential(multiplier=2, min=5, max=30)
    )
    def _send_smtp(
        self,
        to_email: str,
        to_name: str,
        subject: str,
        html_body: str,
        text_body: str
    ) -> tuple[bool, str]:
        """Send via SMTP."""
        msg = MIMEMultipart("alternative")
        msg["Subject"] = subject
        msg["From"]    = (
            f"{self.email_cfg['from_name']} <{self.email_cfg['from_email']}>"
        )
        msg["To"]      = f"{to_name} <{to_email}>"
        msg["List-Unsubscribe"] = (
            f"<{self.config['compliance']['unsubscribe_url']}"
            f"?email={to_email}>"
        )

        msg.attach(MIMEText(text_body, "plain"))
        msg.attach(MIMEText(html_body, "html"))

        with smtplib.SMTP(
            self.email_cfg["smtp_host"],
            self.email_cfg["smtp_port"]
        ) as server:
            server.ehlo()
            server.starttls()
            server.login(
                self.email_cfg["smtp_user"],
                self.email_cfg["smtp_password"]
            )
            server.sendmail(
                self.email_cfg["from_email"],
                to_email,
                msg.as_string()
            )

        message_id = msg.get("Message-ID", f"smtp-{datetime.utcnow().timestamp()}")
        logger.info(f"✅ Email sent to {to_email} | ID: {message_id}")
        return True, message_id

    @retry(
        stop=stop_after_attempt(3),
        wait=wait_exponential(multiplier=2, min=5, max=30)
    )
    def _send_sendgrid(
        self,
        to_email: str,
        to_name: str,
        subject: str,
        html_body: str,
        text_body: str
    ) -> tuple[bool, str]:
        """Send via SendGrid API."""
        import sendgrid
        from sendgrid.helpers.mail import (
            Mail, Content, To, From, PlainTextContent, HtmlContent
        )

        sg = sendgrid.SendGridAPIClient(
            api_key=self.email_cfg["sendgrid_api_key"]
        )
        message = Mail(
            from_email=From(
                self.email_cfg["from_email"],
                self.email_cfg["from_name"]
            ),
            to_emails=To(to_email, to_name),
            subject=subject,
        )
        message.content = [
            Content("text/plain", text_body),
            Content("text/html",  html_body),
        ]

        response = sg.send(message)
        if response.status_code in (200, 201, 202):
            msg_id = response.headers.get("X-Message-Id", "")
            logger.info(f"✅ SendGrid sent to {to_email} | ID: {msg_id}")
            return True, msg_id
        else:
            error = f"SendGrid status {response.status_code}"
            logger.error(f"❌ SendGrid failed: {error}")
            return False, error
