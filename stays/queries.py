from .models import Stay, StayStatus


def stay_search(criteria, queryset=None):
    qs = (queryset or Stay.objects.all()).filter(status=StayStatus.PUBLISHED)
    for f in ("stay_type", "featured", "verification_status"):
        if f in criteria:
            qs = qs.filter(**{f: criteria[f]})
    for f in ("region", "town", "suburb"):
        if criteria.get(f):
            qs = qs.filter(**{f + "__iexact": criteria[f]})
    if criteria.get("amenities"):
        qs = qs.filter(amenities__id__in=criteria["amenities"])
    if criteria.get("min_price") is not None:
        qs = qs.filter(room_types__base_price__gte=criteria["min_price"])
    if criteria.get("max_price") is not None:
        qs = qs.filter(room_types__base_price__lte=criteria["max_price"])
    return qs.distinct()
