from datetime import datetime
from xml.sax.saxutils import escape

from django.conf import settings
from django.http import HttpResponse
from django.utils import timezone
from django.views.decorators.http import require_GET

from properties.models import ListingStatus, PropertyListing
from stays.models import Stay, StayStatus


def frontend_url(path):
    base = settings.FRONTEND_BASE_URL.rstrip("/")
    return f"{base}{path if path.startswith('/') else '/' + path}"


def sitemap_entries():
    now = timezone.now()
    entries = [
        {
            "loc": frontend_url("/"),
            "lastmod": now,
            "priority": "1.0",
            "changefreq": "daily",
        },
        {
            "loc": frontend_url("/properties"),
            "lastmod": now,
            "priority": "0.9",
            "changefreq": "daily",
        },
    ]
    if settings.FEATURE_FLAGS.get("stays", True):
        entries.append(
            {
                "loc": frontend_url("/stays"),
                "lastmod": now,
                "priority": "0.9",
                "changefreq": "daily",
            }
        )

    for listing in PropertyListing.objects.filter(status=ListingStatus.PUBLISHED).only(
        "slug",
        "updated_at",
    ):
        entries.append(
            {
                "loc": frontend_url(f"/properties/{listing.slug}"),
                "lastmod": listing.updated_at,
                "priority": "0.8",
                "changefreq": "weekly",
            }
        )

    if settings.FEATURE_FLAGS.get("stays", True):
        for stay in Stay.objects.filter(status=StayStatus.PUBLISHED).only("slug", "updated_at"):
            entries.append(
                {
                    "loc": frontend_url(f"/stays/{stay.slug}"),
                    "lastmod": stay.updated_at,
                    "priority": "0.8",
                    "changefreq": "weekly",
                }
            )

    return entries


@require_GET
def sitemap_xml(_request):
    lines = [
        '<?xml version="1.0" encoding="UTF-8"?>',
        '<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">',
    ]
    for entry in sitemap_entries():
        lines.append("  <url>")
        lines.append(f"    <loc>{escape(entry['loc'])}</loc>")
        lines.append(f"    <lastmod>{format_lastmod(entry['lastmod'])}</lastmod>")
        lines.append(f"    <changefreq>{entry['changefreq']}</changefreq>")
        lines.append(f"    <priority>{entry['priority']}</priority>")
        lines.append("  </url>")
    lines.append("</urlset>")
    return HttpResponse("\n".join(lines), content_type="application/xml")


def format_lastmod(value):
    if isinstance(value, datetime):
        return value.date().isoformat()
    return value.isoformat()
