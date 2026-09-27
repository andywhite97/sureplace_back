from rest_framework import serializers
from .models import *


class RequestSerializer(serializers.ModelSerializer):
    requirements = serializers.SerializerMethodField()
    documents = serializers.SerializerMethodField()
    applicant_name = serializers.SerializerMethodField()
    applicant_email = serializers.EmailField(source="applicant.email", read_only=True)
    applicant_phone = serializers.CharField(source="applicant.phone_number", read_only=True)
    entity_name = serializers.SerializerMethodField()
    audit_events = serializers.SerializerMethodField()

    class Meta:
        model = VerificationRequest
        fields = [field.name for field in VerificationRequest._meta.fields] + [
            "requirements",
            "documents",
            "applicant_name",
            "applicant_email",
            "applicant_phone",
            "entity_name",
            "audit_events",
        ]
        read_only_fields = ("applicant", "status", "submitted_at", "reviewed_at", "reviewed_by")

    def validate(self, a):
        kind = a.get("verification_type")
        mapping = {"AGENT": "agent_profile", "AGENCY": "agency", "PROPERTY": "property", "STAY": "stay"}
        expected = mapping.get(kind)
        supplied = [x for x in ("agency", "agent_profile", "property", "stay") if a.get(x)]
        if (expected and supplied != [expected]) or (not expected and supplied):
            raise serializers.ValidationError("Entity does not match verification type.")
        request = self.context.get("request")
        if request:
            from .services import authorized

            if not authorized(request.user, VerificationRequest(applicant=request.user, **a)):
                raise serializers.ValidationError("You cannot request verification for this entity.")
            duplicate = VerificationRequest.objects.filter(
                applicant=request.user,
                verification_type=kind,
                status__in=[
                    RequestStatus.DRAFT,
                    RequestStatus.SUBMITTED,
                    RequestStatus.UNDER_REVIEW,
                    RequestStatus.CHANGES_REQUESTED,
                    RequestStatus.APPROVED,
                ],
            )
            for field in ("agency", "agent_profile", "property", "stay"):
                duplicate = duplicate.filter(**{field: a.get(field)})
            if self.instance:
                duplicate = duplicate.exclude(pk=self.instance.pk)
            if duplicate.exists():
                raise serializers.ValidationError("An active verification request already exists for this item.")
        return a

    def get_requirements(self, obj):
        from .requirements import DEFINITIONS
        documents = list(obj.documents.all())
        result = []
        for requirement in DEFINITIONS.get(obj.verification_type, {}).get("requirements", []):
            alternatives = set(requirement.get("alternatives", [requirement["key"]]))
            matching = [item for item in documents if item.document_type in alternatives]
            active = [item for item in matching if item.status != "REJECTED"]
            note = ""
            if obj.status == "CHANGES_REQUESTED":
                note = obj.requirement_notes.get(requirement["key"], "") or (
                    "" if active else next(
                        (item.rejection_reason for item in reversed(matching) if item.rejection_reason), ""
                    )
                )
            result.append({
                **requirement,
                "uploaded": bool(active),
                "document_types": sorted({item.document_type for item in matching}),
                "review_status": "ACCEPTED" if any(item.status == "ACCEPTED" for item in active) else "NEEDS_REPLACEMENT" if matching and not active else "PENDING" if active else "MISSING",
                "reviewer_note": note,
            })
        return result

    def get_audit_events(self, obj):
        view = self.context.get("view")
        if getattr(view, "action", None) == "list":
            return []
        return [
            {
                "id": str(event.id),
                "event_type": event.event_type,
                "previous_status": event.previous_status,
                "new_status": event.new_status,
                "notes": event.notes,
                "actor_name": (
                    f"{event.actor.first_name} {event.actor.last_name}".strip()
                    or event.actor.email
                    if event.actor else "System"
                ),
                "created_at": event.created_at,
            }
            for event in obj.audit_events.select_related("actor").order_by("created_at")
        ]

    def get_documents(self, obj):
        # File URLs remain private; authorized clients use the protected download endpoint.
        return [
            {"id": str(item.id), "document_type": item.document_type, "status": item.status,
             "file_name": item.file.name.rsplit("/", 1)[-1], "file_size": item.file.size,
             "uploaded_at": item.uploaded_at, "rejection_reason": item.rejection_reason}
            for item in obj.documents.all()
        ]

    def get_applicant_name(self, obj):
        return f"{obj.applicant.first_name} {obj.applicant.last_name}".strip() or obj.applicant.email

    def get_entity_name(self, obj):
        if obj.agency_id:
            return obj.agency.name
        if obj.agent_profile_id:
            return str(obj.agent_profile)
        if obj.property_id:
            return obj.property.title
        if obj.stay_id:
            return obj.stay.name
        return "Personal verification"


class DocumentSerializer(serializers.ModelSerializer):
    class Meta:
        model = VerificationDocument
        exclude = ("verification_request", "reviewed_by", "reviewed_at")
        extra_kwargs = {"file": {"write_only": True}}

    def validate_file(self, f):
        from django.conf import settings

        ext = f.name.rsplit(".", 1)[-1].lower()
        if ext not in {"pdf", "jpg", "jpeg", "png"}:
            raise serializers.ValidationError("Only PDF, JPG, JPEG, and PNG are allowed.")
        if f.size > settings.VERIFICATION_MAX_FILE_MB * 1024 * 1024:
            raise serializers.ValidationError("File is too large.")
        return f
