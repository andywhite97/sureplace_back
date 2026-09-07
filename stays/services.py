from datetime import timedelta
from decimal import Decimal
from django.core.exceptions import ValidationError
from .models import StayStatus


def can_manage(user, stay):
    return bool(
        user
        and user.is_authenticated
        and (
            user.is_staff
            or stay.owner_id == user.id
            or (stay.agent_id and stay.agent.user_id == user.id and stay.agent.is_active)
            or (stay.agency_id and user.agent_profiles.filter(agency_id=stay.agency_id, is_active=True).exists())
        )
    )


def room_availability(room, check_in, check_out, adults, children, rooms_required):
    if check_out <= check_in:
        raise ValidationError("Check-out must be after check-in.")
    if adults > room.capacity_adults * rooms_required or children > room.capacity_children * rooms_required:
        return {"available": False, "reason": "occupancy"}
    nights = (check_out - check_in).days
    cached = getattr(room, "_prefetched_objects_cache", {}).get("availability")
    source = cached if cached is not None else room.availability.filter(date__gte=check_in, date__lt=check_out)
    rows = {r.date: r for r in source if check_in <= r.date < check_out}
    prices = []
    minimum = room.minimum_stay
    inventory = room.quantity
    for offset in range(nights):
        day = check_in + timedelta(days=offset)
        row = rows.get(day)
        if row:
            minimum = max(minimum, row.minimum_stay_override or 1)
            units = 0 if row.is_blocked else row.available_units
            price = row.custom_price if row.custom_price is not None else room.base_price
        else:
            units = room.quantity
            price = room.base_price
        try:
            from bookings.services import reserved_units

            units = max(units - reserved_units(room, day), 0)
        except ImportError:
            pass
        inventory = min(inventory, units)
        prices.append({"date": day.isoformat(), "price": str(price)})
    available = nights >= minimum and inventory >= rooms_required
    total = sum((Decimal(x["price"]) for x in prices), Decimal("0")) * rooms_required
    return {
        "available": available,
        "room_type_id": str(room.id),
        "rooms_available": inventory,
        "nightly_prices": prices,
        "total": str(total.quantize(Decimal("0.01"))),
    }


def quality(stay):
    checks = [
        (stay.name, 10, "Add a name"),
        (len(stay.description) >= 100, 15, "Add a detailed description"),
        (stay.location, 15, "Add a map location"),
        (stay.images.count() >= 5, 15, "Add at least 5 photos"),
        (stay.amenities.count() >= 5, 10, "Add more amenities"),
        (stay.phone or stay.email, 10, "Add contact information"),
        (stay.room_types.filter(is_active=True).exists(), 15, "Add a room type"),
        (stay.check_in_time and stay.check_out_time, 10, "Add check-in and check-out times"),
    ]
    return {"score": sum(p for ok, p, _ in checks if ok), "suggestions": [s for ok, _, s in checks if not ok]}


def submit(stay):
    if stay.status not in (StayStatus.DRAFT, StayStatus.REJECTED):
        raise ValidationError("Only draft or rejected stays can be submitted.")
    stay.status = StayStatus.PUBLISHED
    stay.full_clean()
    stay.status = StayStatus.SUBMITTED
    stay.save()
    return stay


def pause(stay):
    if stay.status != StayStatus.PUBLISHED:
        raise ValidationError("Only published stays can be paused.")
    stay.status = StayStatus.PAUSED
    stay.save()
    return stay
