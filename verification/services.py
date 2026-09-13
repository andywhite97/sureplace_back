from django.core.exceptions import ValidationError
from django.db import transaction
from django.utils import timezone
from core.choices import VerificationStatus
from properties.permissions import can_manage_property
from stays.services import can_manage as can_manage_stay
from .models import *
from .requirements import DEFINITIONS

LEGACY_REQUIRED = {
    VerificationType.IDENTITY: [{"NATIONAL_ID", "PASSPORT"}],
    VerificationType.AGENT: [{"AGENT_IDENTIFICATION"}, {"PROFESSIONAL_REFERENCE", "EMPLOYMENT_CONFIRMATION"}],
    VerificationType.AGENCY: [{"COMPANY_REGISTRATION"}, {"PROOF_OF_ADDRESS"}],
    VerificationType.PROPERTY: [{"TITLE_DEED", "OWNER_AUTHORIZATION"}],
    VerificationType.STAY: [{"BUSINESS_REGISTRATION", "TOURISM_LICENCE"}, {"PROOF_OF_ADDRESS"}],
    VerificationType.BUSINESS: [{"BUSINESS_REGISTRATION"}],
}


def authorized(user, r):
    return r.applicant_id == user.id and (
        r.verification_type in (VerificationType.IDENTITY, VerificationType.BUSINESS)
        or (r.agent_profile_id and r.agent_profile.user_id == user.id)
        or (r.agency_id and user.agent_profiles.filter(agency=r.agency, is_active=True).exists())
        or (r.property_id and can_manage_property(user, r.property))
        or (r.stay_id and can_manage_stay(user, r.stay))
    )


def audit(r, user, event, old, notes=""):
    VerificationAuditEvent.objects.create(
        verification_request=r, actor=user, event_type=event, previous_status=old, new_status=r.status, notes=notes
    )


@transaction.atomic
def submit(r, user):
    if not authorized(user, r) or r.status not in (RequestStatus.DRAFT, RequestStatus.CHANGES_REQUESTED):
        raise ValidationError("Request cannot be submitted.")
    definition = DEFINITIONS.get(r.verification_type, {})
    approved_types = set(
        VerificationRequest.objects.filter(applicant=user, status=RequestStatus.APPROVED)
        .values_list("verification_type", flat=True)
    )
    required_dependencies = {
        item["type"] for item in definition.get("prerequisites", []) if item.get("required")
    }
    missing_dependencies = sorted(required_dependencies - approved_types)
    if missing_dependencies:
        raise ValidationError(f"Complete prerequisite verification first: {missing_dependencies}")
    types = set(
        r.documents.exclude(status=DocumentStatus.REJECTED).values_list("document_type", flat=True)
    )
    missing = []
    for requirement in DEFINITIONS.get(r.verification_type, {}).get("requirements", []):
        if not requirement.get("required"):
            continue
        accepted = set(requirement.get("alternatives", [requirement["key"]]))
        if not types.intersection(accepted):
            missing.append(sorted(accepted))
    if missing:
        raise ValidationError(f"Missing required documents: {missing}")
    old = r.status
    r.status = RequestStatus.SUBMITTED
    r.submitted_at = timezone.now()
    r.save()
    audit(r, user, "SUBMITTED", old)
    return r


@transaction.atomic
def review(r, user, target, notes=""):
    if not user.has_perm("verification.review_verificationrequest") and not user.is_superuser:
        raise ValidationError("Reviewer permission required.")
    allowed = {
        RequestStatus.SUBMITTED: {RequestStatus.UNDER_REVIEW, RequestStatus.APPROVED, RequestStatus.REJECTED},
        RequestStatus.UNDER_REVIEW: {RequestStatus.APPROVED, RequestStatus.REJECTED},
    }
    if target not in allowed.get(r.status, set()):
        raise ValidationError("Invalid verification status transition.")
    old = r.status
    r.status = target
    r.reviewed_by = user
    r.reviewed_at = timezone.now()
    r.reviewer_notes = notes
    if target == RequestStatus.REJECTED:
        r.rejection_reason = notes
    r.save()
    audit(r, user, target, old, notes)
    entity = {
        VerificationType.AGENT: r.agent_profile,
        VerificationType.AGENCY: r.agency,
        VerificationType.PROPERTY: r.property,
        VerificationType.STAY: r.stay,
    }.get(r.verification_type)
    if entity and target == RequestStatus.APPROVED:
        entity.verification_status = VerificationStatus.VERIFIED
        entity.save()
    if target in (RequestStatus.APPROVED, RequestStatus.REJECTED):
        from notifications.models import NotificationType
        from notifications.services import notify_transactional

        notify_transactional(
            r.applicant,
            NotificationType.VERIFICATION_UPDATE,
            f"Verification {target.lower()}",
            f"Your {r.verification_type.lower()} verification was {target.lower()}.",
            {"route": f"/account/verification/{r.id}"},
            f"verification:{target}:{r.id}",
            "email_enabled",
        )
    return r


@transaction.atomic
def suspend(r, user, reason=""):
    if not user.has_perm("verification.review_verificationrequest") and not user.is_superuser:
        raise ValidationError("Reviewer permission required.")
    if r.status != RequestStatus.APPROVED:
        raise ValidationError("Only approved verification can be suspended.")
    entity = {
        VerificationType.AGENT: r.agent_profile,
        VerificationType.AGENCY: r.agency,
        VerificationType.PROPERTY: r.property,
        VerificationType.STAY: r.stay,
    }.get(r.verification_type)
    if not entity:
        raise ValidationError("This verification has no suspendable entity.")
    entity.verification_status = VerificationStatus.SUSPENDED
    entity.save(update_fields=["verification_status"])
    audit(r, user, "SUSPENDED", r.status, reason)
    from notifications.models import NotificationType
    from notifications.services import notify_transactional

    notify_transactional(
        r.applicant,
        NotificationType.VERIFICATION_UPDATE,
        "Verification suspended",
        f"Your {r.verification_type.lower()} verification was suspended.",
        {"route": f"/account/verification/{r.id}"},
        f"verification:SUSPENDED:{r.id}",
        "email_enabled",
    )
    return r
