from django.contrib import admin
from .models import VerificationRequest, VerificationDocument, VerificationAuditEvent

admin.site.register([VerificationRequest, VerificationDocument, VerificationAuditEvent])
