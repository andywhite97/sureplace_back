from datetime import timedelta
from decimal import Decimal
from django.conf import settings
from django.core.exceptions import ValidationError
from django.db import transaction
from django.db.models import Sum
from django.utils import timezone
from messaging.services import create_conversation, system_message
from stays.models import RoomAvailability, RoomType, StayStatus
from stays.services import can_manage
from .models import Booking, BookingStatus

ACTIVE = (BookingStatus.PENDING, BookingStatus.CONFIRMED)


def reserved_units(room, day, exclude=None):
    qs = Booking.objects.filter(room_type=room, status__in=ACTIVE, check_in__lte=day, check_out__gt=day)
    if exclude:
        qs = qs.exclude(pk=exclude)
    return qs.aggregate(total=Sum("rooms"))["total"] or 0


def inventory(room, day):
    row = room.availability.filter(date=day).first()
    base = 0 if row and row.is_blocked else (row.available_units if row else room.quantity)
    return max(base - reserved_units(room, day), 0)


@transaction.atomic
def create_booking(
    *,
    guest,
    stay,
    room_type,
    check_in,
    check_out,
    adults,
    children,
    rooms,
    guest_name,
    guest_email,
    guest_phone="",
    special_requests="",
    idempotency_key=None,
):
    if idempotency_key:
        existing = Booking.objects.filter(guest=guest, idempotency_key=idempotency_key).first()
        if existing:
            return existing
    room = RoomType.objects.select_for_update().select_related("stay").get(pk=room_type.pk)
    if room.stay_id != stay.id or stay.status != StayStatus.PUBLISHED or not room.is_active:
        raise ValidationError("Stay or room is unavailable.")
    if can_manage(guest, stay):
        raise ValidationError("Managers cannot book their own stay.")
    result = __import__("stays.services", fromlist=["room_availability"]).room_availability(
        room, check_in, check_out, adults, children, rooms
    )
    if not result["available"]:
        raise ValidationError("Room cannot satisfy dates, occupancy, or minimum stay.")
    for offset in range((check_out - check_in).days):
        day = check_in + timedelta(days=offset)
        RoomAvailability.objects.select_for_update().filter(room_type=room, date=day).first()
        if inventory(room, day) < rooms:
            raise ValidationError("Insufficient inventory.")
    subtotal = sum((Decimal(x["price"]) for x in result["nightly_prices"]), Decimal("0")) * rooms
    conversation = create_conversation(guest, "Booking requested", stay=stay, message_type="BOOKING_ENQUIRY")
    booking = Booking.objects.create(
        stay=stay,
        room_type=room,
        guest=guest,
        conversation=conversation,
        check_in=check_in,
        check_out=check_out,
        adults=adults,
        children=children,
        rooms=rooms,
        nightly_pricing=result["nightly_prices"],
        nightly_subtotal=subtotal,
        taxes=0,
        fees=0,
        total=subtotal,
        currency=room.currency,
        guest_name=guest_name,
        guest_email=guest_email,
        guest_phone=guest_phone,
        special_requests=special_requests,
        idempotency_key=idempotency_key,
        expires_at=timezone.now() + timedelta(minutes=settings.BOOKING_HOLD_MINUTES),
    )
    system_message(conversation, f"Booking {booking.reference} requested for {check_in} to {check_out}")
    from notifications.models import NotificationType
    from notifications.services import notify_transactional

    manager = stay.agent.user if stay.agent_id else stay.owner
    notify_transactional(
        manager,
        NotificationType.BOOKING_REQUESTED,
        "New booking request",
        f"Booking {booking.reference} was requested.",
        {"route": f"/bookings/{booking.id}", "booking_id": str(booking.id)},
        f"booking-requested:{booking.id}",
        "booking_updates_email",
    )
    return booking


TRANSITIONS = {
    BookingStatus.PENDING: {
        BookingStatus.CONFIRMED,
        BookingStatus.DECLINED,
        BookingStatus.CANCELLED,
        BookingStatus.EXPIRED,
    },
    BookingStatus.CONFIRMED: {BookingStatus.CANCELLED, BookingStatus.COMPLETED},
}


@transaction.atomic
def transition(booking, target, user):
    booking = Booking.objects.select_for_update().get(pk=booking.pk)
    if target not in TRANSITIONS.get(booking.status, set()):
        raise ValidationError("Invalid booking transition.")
    manager = can_manage(user, booking.stay)
    if target in (BookingStatus.CONFIRMED, BookingStatus.DECLINED, BookingStatus.COMPLETED) and not manager:
        raise ValidationError("Manager permission required.")
    if target == BookingStatus.CANCELLED and user != booking.guest and not manager:
        raise ValidationError("Permission denied.")
    booking.status = target
    now = timezone.now()
    if target == BookingStatus.CONFIRMED:
        booking.confirmed_at = now
    if target == BookingStatus.CANCELLED:
        booking.cancelled_at = now
    if target == BookingStatus.COMPLETED:
        booking.completed_at = now
    booking.save()
    system_message(booking.conversation, f"Booking {booking.reference} {target.lower()}")
    from notifications.models import NotificationType
    from notifications.services import notify_transactional

    kinds = {
        BookingStatus.CONFIRMED: NotificationType.BOOKING_CONFIRMED,
        BookingStatus.DECLINED: NotificationType.BOOKING_DECLINED,
        BookingStatus.CANCELLED: NotificationType.BOOKING_CANCELLED,
    }
    if target in kinds:
        notify_transactional(
            booking.guest,
            kinds[target],
            f"Booking {target.lower()}",
            f"Booking {booking.reference} was {target.lower()}.",
            {"route": f"/account/bookings/{booking.id}", "booking_id": str(booking.id)},
            f"booking:{target}:{booking.id}",
            "booking_updates_email",
        )
    return booking


def expire_pending():
    return Booking.objects.filter(status=BookingStatus.PENDING, expires_at__lte=timezone.now()).update(
        status=BookingStatus.EXPIRED
    )
