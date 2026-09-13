from rest_framework import serializers
from .models import *


class RequestSerializer(serializers.ModelSerializer):
    requirements = serializers.SerializerMethodField()
    documents = serializers.SerializerMethodField()

    class Meta:
        model = VerificationRequest
        fields = [field.name for field in VerificationRequest._meta.fields] + ["requirements", "documents"]
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
        uploaded = set(obj.documents.values_list("document_type", flat=True))
        result = []
        for requirement in DEFINITIONS.get(obj.verification_type, {}).get("requirements", []):
            alternatives = set(requirement.get("alternatives", [requirement["key"]]))
            result.append({
                **requirement,
                "uploaded": bool(uploaded.intersection(alternatives)),
                "document_types": sorted(uploaded.intersection(alternatives)),
            })
        return result

    def get_documents(self, obj):
        # File URLs remain private; authorized clients use the protected download endpoint.
        return [
            {"id": str(item.id), "document_type": item.document_type, "status": item.status,
             "file_name": item.file.name.rsplit("/", 1)[-1], "file_size": item.file.size,
             "uploaded_at": item.uploaded_at, "rejection_reason": item.rejection_reason}
            for item in obj.documents.all()
        ]


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
