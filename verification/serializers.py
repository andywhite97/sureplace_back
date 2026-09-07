from rest_framework import serializers
from .models import *


class RequestSerializer(serializers.ModelSerializer):
    class Meta:
        model = VerificationRequest
        fields = "__all__"
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
        return a


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
