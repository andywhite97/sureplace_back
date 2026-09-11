import re
from dataclasses import dataclass
from datetime import date, datetime
from typing import Any, Callable
from urllib.parse import urljoin, urlparse

from django.conf import settings
from django.template.loader import render_to_string


@dataclass(frozen=True)
class RenderedEmail:
    subject: str
    html: str
    text: str
    template_key: str
    preheader: str


@dataclass(frozen=True)
class EmailTemplateDefinition:
    subject: Callable[[dict[str, Any]], str] | str
    html_template: str
    text_template: str
    preheader: Callable[[dict[str, Any]], str] | str = ""
    default_cta_label: str = "View Details"
    status: str = "info"


def value(path: str, fallback: str = "") -> Callable[[dict[str, Any]], str]:
    def read(context: dict[str, Any]) -> str:
        current: Any = context
        for part in path.split("."):
            if isinstance(current, dict):
                current = current.get(part)
            else:
                current = getattr(current, part, None)
            if current in (None, ""):
                return fallback
        return str(current)

    return read


TEMPLATES: dict[str, EmailTemplateDefinition] = {
    "transactional": EmailTemplateDefinition(
        subject=value("subject", "SurePlace update"),
        html_template="emails/transactional.html",
        text_template="emails/transactional.txt",
        preheader=value("message", "You have a SurePlace update."),
    ),
    "auth.welcome": EmailTemplateDefinition(
        subject="Welcome to SurePlace",
        html_template="emails/auth/welcome.html",
        text_template="emails/auth/welcome.txt",
        preheader="Your SurePlace account is ready.",
        default_cta_label="Explore Properties",
        status="success",
    ),
    "auth.password_reset": EmailTemplateDefinition(
        subject="Reset your SurePlace password",
        html_template="emails/auth/password_reset.html",
        text_template="emails/auth/password_reset.txt",
        preheader="Use this secure link to reset your SurePlace password.",
        default_cta_label="Reset Password",
        status="info",
    ),
    "auth.verify_email": EmailTemplateDefinition(
        subject="Verify your SurePlace email",
        html_template="emails/auth/verify_email.html",
        text_template="emails/auth/verify_email.txt",
        preheader="Confirm your email address to finish setting up your SurePlace account.",
        default_cta_label="Verify Email",
        status="info",
    ),
    "system.email_diagnostic": EmailTemplateDefinition(
        subject="SurePlace email delivery test",
        html_template="emails/system/email_diagnostic.html",
        text_template="emails/system/email_diagnostic.txt",
        preheader="This diagnostic message was sent manually by a SurePlace administrator.",
        default_cta_label="Open SurePlace",
        status="success",
    ),
    "booking.requested_host": EmailTemplateDefinition(
        subject=lambda c: f"New booking request - {value('stay.name', 'SurePlace stay')(c)}",
        html_template="emails/bookings/requested_host.html",
        text_template="emails/bookings/requested_host.txt",
        preheader=lambda c: f"A guest requested {value('stay.name', 'your stay')(c)}.",
        default_cta_label="View Request",
        status="warning",
    ),
    "booking.confirmed": EmailTemplateDefinition(
        subject=lambda c: f"Your booking is confirmed - {value('stay.name', 'SurePlace stay')(c)}",
        html_template="emails/bookings/confirmed.html",
        text_template="emails/bookings/confirmed.txt",
        preheader=lambda c: f"Your stay at {value('stay.name', 'SurePlace')(c)} is confirmed.",
        default_cta_label="View Booking",
        status="success",
    ),
    "booking.declined": EmailTemplateDefinition(
        subject=lambda c: f"Booking request update - {value('stay.name', 'SurePlace stay')(c)}",
        html_template="emails/bookings/declined.html",
        text_template="emails/bookings/declined.txt",
        preheader="Your booking request was not accepted.",
        default_cta_label="Browse Other Stays",
        status="error",
    ),
    "booking.cancelled": EmailTemplateDefinition(
        subject=lambda c: f"Your booking was cancelled - {value('stay.name', 'SurePlace stay')(c)}",
        html_template="emails/bookings/cancelled.html",
        text_template="emails/bookings/cancelled.txt",
        preheader="A SurePlace booking has been cancelled.",
        default_cta_label="Browse Other Stays",
        status="error",
    ),
    "booking.expired": EmailTemplateDefinition(
        subject=lambda c: f"Booking request expired - {value('stay.name', 'SurePlace stay')(c)}",
        html_template="emails/bookings/expired.html",
        text_template="emails/bookings/expired.txt",
        preheader="A pending booking request expired.",
        default_cta_label="Search Stays",
        status="warning",
    ),
    "viewing.requested": EmailTemplateDefinition(
        subject=lambda c: f"New viewing request - {value('property.title', 'SurePlace property')(c)}",
        html_template="emails/viewings/requested.html",
        text_template="emails/viewings/requested.txt",
        preheader="A seeker requested a property viewing.",
        default_cta_label="Respond to Request",
        status="info",
    ),
    "viewing.confirmed": EmailTemplateDefinition(
        subject=lambda c: f"Viewing confirmed - {value('property.title', 'SurePlace property')(c)}",
        html_template="emails/viewings/confirmed.html",
        text_template="emails/viewings/confirmed.txt",
        preheader="Your property viewing has been confirmed.",
        default_cta_label="View Details",
        status="success",
    ),
    "viewing.declined": EmailTemplateDefinition(
        subject=lambda c: f"Viewing request update - {value('property.title', 'SurePlace property')(c)}",
        html_template="emails/viewings/declined.html",
        text_template="emails/viewings/declined.txt",
        preheader="Your viewing request was not accepted.",
        default_cta_label="Browse Similar Properties",
        status="error",
    ),
    "verification.submitted": EmailTemplateDefinition(
        subject="Verification submitted",
        html_template="emails/verification/submitted.html",
        text_template="emails/verification/submitted.txt",
        preheader="Your verification request has been received.",
        default_cta_label="View Verification",
        status="info",
    ),
    "verification.approved": EmailTemplateDefinition(
        subject="Your verification has been approved",
        html_template="emails/verification/approved.html",
        text_template="emails/verification/approved.txt",
        preheader="Your reviewed verification information has been approved.",
        default_cta_label="Go to Dashboard",
        status="success",
    ),
    "verification.rejected": EmailTemplateDefinition(
        subject="Verification needs attention",
        html_template="emails/verification/rejected.html",
        text_template="emails/verification/rejected.txt",
        preheader="Your verification request needs attention.",
        default_cta_label="Review Verification",
        status="warning",
    ),
    "messaging.new_message": EmailTemplateDefinition(
        subject="You have a new SurePlace message",
        html_template="emails/messaging/new_message.html",
        text_template="emails/messaging/new_message.txt",
        preheader="A new message is waiting in your SurePlace inbox.",
        default_cta_label="View Message",
        status="info",
    ),
    "alerts.saved_search_match": EmailTemplateDefinition(
        subject="New properties match your saved search",
        html_template="emails/alerts/saved_search_match.html",
        text_template="emails/alerts/saved_search_match.txt",
        preheader="New listings match your saved search.",
        default_cta_label="View All Matches",
        status="info",
    ),
}

NOTIFICATION_TEMPLATE_KEYS = {
    "BOOKING_REQUESTED": "booking.requested_host",
    "BOOKING_CONFIRMED": "booking.confirmed",
    "BOOKING_DECLINED": "booking.declined",
    "BOOKING_CANCELLED": "booking.cancelled",
    "BOOKING_EXPIRING": "booking.expired",
    "VIEWING_REQUEST": "viewing.requested",
    "VIEWING_CONFIRMED": "viewing.confirmed",
    "VIEWING_DECLINED": "viewing.declined",
    "VERIFICATION_UPDATE": "verification.submitted",
    "NEW_MESSAGE": "messaging.new_message",
    "GUEST_ENQUIRY": "messaging.new_message",
    "SAVED_SEARCH_MATCH": "alerts.saved_search_match",
}


def template_for_notification(kind: str, title: str = "") -> str:
    if kind == "VERIFICATION_UPDATE":
        lowered = title.lower()
        if "approved" in lowered:
            return "verification.approved"
        if "rejected" in lowered or "attention" in lowered:
            return "verification.rejected"
        return "verification.submitted"
    return NOTIFICATION_TEMPLATE_KEYS.get(kind, "transactional")


def render_email(template_key: str, context: dict[str, Any] | None = None) -> RenderedEmail:
    definition = TEMPLATES.get(template_key, TEMPLATES["transactional"])
    context = normalize_context(context or {}, definition)
    subject = _resolve(definition.subject, context)
    preheader = context.get("preheader") or _resolve(definition.preheader, context)
    context = {**context, "subject": subject, "preheader": preheader, "template_key": template_key}
    return RenderedEmail(
        subject=subject,
        html=render_to_string(definition.html_template, context),
        text=render_to_string(definition.text_template, context).strip() + "\n",
        template_key=template_key,
        preheader=preheader,
    )


def normalize_context(context: dict[str, Any], definition: EmailTemplateDefinition) -> dict[str, Any]:
    frontend_base_url = getattr(settings, "FRONTEND_BASE_URL", "http://localhost:4200").rstrip("/")
    support_email = getattr(settings, "DEFAULT_REPLY_TO_EMAIL", "")
    cta_url = absolute_url(context.get("cta_url") or context.get("route") or "/", frontend_base_url)
    secondary_cta_url = context.get("secondary_cta_url")
    return {
        **context,
        "site_name": "SurePlace",
        "brand_name": "SurePlace",
        "tagline": "Property. Without the noise.",
        "frontend_base_url": frontend_base_url,
        "logo_url": getattr(settings, "EMAIL_LOGO_URL", ""),
        "support_email": support_email,
        "current_year": date.today().year,
        "headline": context.get("headline") or context.get("subject") or "SurePlace update",
        "message": clean_preview(context.get("message", "")),
        "cta_label": context.get("cta_label") or definition.default_cta_label,
        "cta_url": cta_url,
        "secondary_cta_label": context.get("secondary_cta_label", ""),
        "secondary_cta_url": absolute_url(secondary_cta_url, frontend_base_url) if secondary_cta_url else "",
        "details": normalize_details(context.get("details") or details_from_data(context.get("data") or {})),
        "status": context.get("status") or definition.status,
    }


def absolute_url(value: str, frontend_base_url: str | None = None) -> str:
    if not value:
        return ""
    parsed = urlparse(value)
    if parsed.scheme in {"http", "https"}:
        return value
    base = (frontend_base_url or getattr(settings, "FRONTEND_BASE_URL", "http://localhost:4200")).rstrip("/") + "/"
    return urljoin(base, value.lstrip("/"))


def details_from_data(data: dict[str, Any]) -> list[dict[str, str]]:
    details = []
    labels = {
        "booking_id": "Booking",
        "viewing_id": "Viewing",
        "saved_search_id": "Saved Search",
        "match_count": "Matches",
        "property_id": "Property",
        "stay_id": "Stay",
    }
    for key, label in labels.items():
        if data.get(key):
            details.append({"label": label, "value": str(data[key])})
    return details


def normalize_details(details: list[dict[str, Any]]) -> list[dict[str, str]]:
    return [{"label": str(item.get("label", "")), "value": display_value(item.get("value", ""))} for item in details]


def display_value(value: Any) -> str:
    if isinstance(value, datetime):
        return value.strftime("%d %b %Y")
    if isinstance(value, date):
        return value.strftime("%d %b %Y")
    text = str(value)
    if re.fullmatch(r"\d{4}-\d{2}-\d{2}", text):
        try:
            return datetime.strptime(text, "%Y-%m-%d").strftime("%d %b %Y")
        except ValueError:
            return text
    return text


def clean_preview(value: Any, limit: int = 240) -> str:
    text = re.sub(r"[\x00-\x08\x0b\x0c\x0e-\x1f]", "", str(value or ""))
    return text[: limit - 1] + "..." if len(text) > limit else text


def sample_context(template_key: str) -> dict[str, Any]:
    samples = {
        "auth.welcome": {
            "headline": "Welcome to SurePlace",
            "message": "Your account is ready. You can now explore properties, save favourites, request viewings, book stays, and message hosts or agents.",
            "cta_url": "/properties",
        },
        "auth.password_reset": {
            "headline": "Reset your password",
            "message": "A password reset was requested for your SurePlace account.",
            "cta_url": "/reset-password?uid=sample&token=sample-token",
            "expiry_text": "For your security, this reset link will expire after a limited time.",
        },
        "auth.verify_email": {
            "headline": "Verify your email",
            "message": "Thanks for joining SurePlace. Confirm your email address to finish setting up your account.",
            "cta_url": "/verify-email?token=sample-token",
            "expiry_text": "This link expires in 24 hours.",
        },
        "system.email_diagnostic": {
            "headline": "SurePlace email delivery test",
            "message": (
                "Your SurePlace email provider is configured correctly. "
                "This diagnostic message was sent manually by a SurePlace administrator. "
                "No action is required."
            ),
            "cta_url": "/",
        },
        "booking.requested_host": _booking_sample("New booking request", "/account/bookings/sample"),
        "booking.confirmed": _booking_sample("Booking confirmed", "/account/bookings/sample"),
        "booking.declined": _booking_sample("Booking request declined", "/stays"),
        "booking.cancelled": _booking_sample("Booking cancelled", "/stays"),
        "booking.expired": _booking_sample("Booking request expired", "/stays"),
        "viewing.requested": _viewing_sample("New viewing request", "/account/viewings/sample"),
        "viewing.confirmed": _viewing_sample("Viewing confirmed", "/account/viewings/sample"),
        "viewing.declined": _viewing_sample("Viewing request declined", "/properties"),
        "verification.submitted": _verification_sample("Verification submitted", "Submitted"),
        "verification.approved": _verification_sample("Verification approved", "Approved"),
        "verification.rejected": _verification_sample("Verification needs attention", "Needs attention"),
        "messaging.new_message": {
            "headline": "You have a new message",
            "message": "Nomsa sent a message about Modern Ezulwini Apartment.",
            "sender": {"name": "Nomsa Dlamini"},
            "listing": {"title": "Modern Ezulwini Apartment", "location": "Ezulwini"},
            "message_preview": "Hi, is this still available for viewing this weekend?",
            "cta_url": "/account/messages/sample",
        },
        "alerts.saved_search_match": {
            "headline": "New properties match your search",
            "message": "We found 3 new listings for your Mbabane rentals search.",
            "saved_search": {"name": "Mbabane rentals", "criteria": "2+ bedrooms, under E8,000"},
            "matches": [
                {"title": "Sunny 2-bedroom flat", "location": "Mbabane", "price": "E7,500", "image_url": ""},
                {"title": "Garden cottage", "location": "Ezulwini", "price": "E6,900", "image_url": ""},
            ],
            "cta_url": "/saved-searches/sample",
            "secondary_cta_label": "Manage Saved Searches",
            "secondary_cta_url": "/account/saved-searches",
        },
    }
    return samples.get(
        template_key, {"headline": "SurePlace update", "message": "You have a SurePlace update.", "cta_url": "/"}
    )


def _booking_sample(headline: str, cta_url: str) -> dict[str, Any]:
    return {
        "headline": headline,
        "message": booking_message(headline),
        "stay": {"name": "Royal Villas Guest House", "location": "Ezulwini", "image_url": "", "price": "E1,200/night"},
        "booking": {
            "reference": "SP-BKG-2026-AB12CD34EF",
            "guest_name": "Nomsa Dlamini",
            "check_in": "2026-10-12",
            "check_out": "2026-10-15",
            "guests": "2 adults",
            "total": "E3,600",
            "status": headline,
        },
        "details": [
            {"label": "Booking reference", "value": "SP-BKG-2026-AB12CD34EF"},
            {"label": "Stay", "value": "Royal Villas Guest House"},
            {"label": "Check-in", "value": "12 Oct 2026"},
            {"label": "Check-out", "value": "15 Oct 2026"},
            {"label": "Guests", "value": "2 adults"},
            {"label": "Total", "value": "E3,600"},
        ],
        "cta_url": cta_url,
        "secondary_cta_label": "Open Conversation",
        "secondary_cta_url": "/account/messages/sample",
    }


def _viewing_sample(headline: str, cta_url: str) -> dict[str, Any]:
    return {
        "headline": headline,
        "message": viewing_message(headline),
        "property": {
            "title": "Modern Ezulwini Apartment",
            "location": "Ezulwini",
            "image_url": "",
            "price": "E7,500/month",
        },
        "viewing": {
            "requester_name": "Nomsa Dlamini",
            "date": "2026-10-10",
            "time": "14:00",
            "message": "Weekend viewing preferred.",
        },
        "details": [
            {"label": "Property", "value": "Modern Ezulwini Apartment"},
            {"label": "Date", "value": "10 Oct 2026"},
            {"label": "Time", "value": "14:00"},
            {"label": "Requester", "value": "Nomsa Dlamini"},
        ],
        "cta_url": cta_url,
    }


def _verification_sample(headline: str, status: str) -> dict[str, Any]:
    return {
        "headline": headline,
        "message": verification_message(headline, status),
        "verification": {
            "type": "Identity",
            "status": status,
            "submitted_date": "2026-10-08",
            "reason": "Please upload a clearer document image.",
        },
        "details": [
            {"label": "Verification type", "value": "Identity"},
            {"label": "Current status", "value": status},
            {"label": "Submitted", "value": "08 Oct 2026"},
        ],
        "cta_url": "/account/verification/sample",
    }


def _resolve(value_or_callable: Callable[[dict[str, Any]], str] | str, context: dict[str, Any]) -> str:
    return value_or_callable(context) if callable(value_or_callable) else value_or_callable


def booking_message(headline: str) -> str:
    if "confirmed" in headline.lower():
        return "Your stay at Royal Villas Guest House is confirmed."
    if "cancelled" in headline.lower():
        return "Your booking at Royal Villas Guest House has been cancelled."
    if "declined" in headline.lower():
        return "This booking request was not accepted. You can browse other stays on SurePlace."
    if "expired" in headline.lower():
        return "The pending booking was not confirmed before the hold expired."
    return "Nomsa Dlamini requested a stay. The booking is pending until you confirm it."


def viewing_message(headline: str) -> str:
    lowered = headline.lower()
    if "confirmed" in lowered:
        return "Your viewing for Modern Ezulwini Apartment has been confirmed."
    if "declined" in lowered:
        return "This viewing request was not accepted. You can continue browsing similar properties."
    return "Nomsa Dlamini requested a viewing for Modern Ezulwini Apartment."


def verification_message(headline: str, status: str) -> str:
    verification_type = "identity"
    if "approved" in headline.lower():
        return f"Your {verification_type} verification has been approved."
    if "attention" in headline.lower() or "rejected" in headline.lower():
        return f"Your {verification_type} verification needs attention before it can be approved."
    return f"Your {verification_type} verification was received and is pending review."
