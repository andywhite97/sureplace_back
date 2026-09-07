from django.contrib import admin
from .models import ListingReport, ModerationAuditEvent

admin.site.register([ListingReport, ModerationAuditEvent])
