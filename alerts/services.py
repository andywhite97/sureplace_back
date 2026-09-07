from django.utils import timezone
from properties.queries import property_search
from stays.queries import stay_search
from .models import SearchAlertEvent, SearchType


def matches(saved):
    return property_search(saved.criteria) if saved.search_type == SearchType.PROPERTY else stay_search(saved.criteria)


def evaluate(saved):
    qs = matches(saved)
    created = []
    for item in qs:
        kwargs = {"property": item} if saved.search_type == SearchType.PROPERTY else {"stay": item}
        event, new = SearchAlertEvent.objects.get_or_create(
            saved_search=saved, listing_type=saved.search_type, **kwargs
        )
        if new:
            created.append(item)
    saved.last_checked_at = timezone.now()
    saved.save(update_fields=["last_checked_at", "updated_at"])
    return created
