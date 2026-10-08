from datetime import timedelta
from decimal import Decimal
from django.conf import settings
from django.core.exceptions import ValidationError
from django.db import transaction
from django.db.models import Sum
from django.utils import timezone
from messaging.services import create_conversation, system_message
from stays.models import BookingMode, RoomAvailability, RoomType, StayStatus
from stays.services import can_manage
from .models import Booking, BookingEvent, BookingStatus

ACTIVE = (BookingStatus.PENDING, BookingStatus.CONFIRMED)


class PriceChanged(ValidationError):
    def __init__(self, total, nightly_prices):
        self.total = str(total)
        self.nightly_prices = nightly_prices
        super().__init__("The price for this stay has changed.")


def reserved_units(room, day, exclude=None):
    qs = Booking.objects.filter(room_type=room, status__in=ACTIVE, check_in__lte=day, check_out__gt=day)
    qs = qs.exclude(status=BookingStatus.PENDING, expires_at__lte=timezone.now())
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
    expected_total=None,
    policies_accepted=None,
):
    if idempotency_key:
        existing = Booking.objects.filter(guest=guest, idempotency_key=idempotency_key).first()
        if existing:
            return existing
    room = RoomType.objects.select_for_update().select_related("stay").get(pk=room_type.pk)
    # A concurrent retry may have committed while this request waited for the room lock.
    if idempotency_key:
        existing = Booking.objects.filter(guest=guest, idempotency_key=idempotency_key).first()
        if existing:
            return existing
    contact = {}
    for field, value in (
        ("guest_name", guest_name.strip() if isinstance(guest_name, str) else guest_name),
        ("guest_email", guest_email),
        ("guest_phone", guest_phone),
        ("special_requests", special_requests),
        ("idempotency_key", idempotency_key),
    ):
        contact[field] = Booking._meta.get_field(field).clean(value, None)
    if not contact["guest_name"]:
        raise ValidationError({"guest_name": "Guest name is required."})
    if room.stay_id != stay.id or room.stay.status != StayStatus.PUBLISHED or not room.is_active:
        raise ValidationError("Stay or room is unavailable.")
    if can_manage(guest, room.stay):
        raise ValidationError("Managers cannot book their own stay.")
    if len(special_requests) > 1000:
        raise ValidationError({"special_requests": "Use at most 1000 characters."})
    if policies_accepted is False:
        raise ValidationError({"policies_accepted": "Accept the booking and cancellation policies."})
    if check_in < timezone.localdate():
        raise ValidationError({"check_in": "Check-in must not be in the past."})
    for field, value, minimum in (("adults", adults, 1), ("children", children, 0), ("rooms", rooms, 1)):
        if isinstance(value, bool) or not isinstance(value, int) or not minimum <= value <= 32767:
            raise ValidationError({field: f"Enter an integer between {minimum} and 32767."})
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
    if expected_total is not None and Decimal(expected_total) != subtotal:
        raise PriceChanged(subtotal, result["nightly_prices"])
    current_stay = room.stay
    instant = current_stay.booking_mode == BookingMode.INSTANT_BOOK
    policy = {
        "payment_method": "PAY_AT_PROPERTY",
        "cancellation_policy": current_stay.cancellation_policy,
        "house_rules": current_stay.house_rules,
        "check_in_time": str(current_stay.check_in_time) if current_stay.check_in_time else None,
        "check_out_time": str(current_stay.check_out_time) if current_stay.check_out_time else None,
        "minimum_stay": result.get("minimum_stay", room.minimum_stay),
    }
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
        booking_mode=current_stay.booking_mode,
        policy_snapshot=policy,
        status=BookingStatus.CONFIRMED if instant else BookingStatus.PENDING,
        confirmed_at=timezone.now() if instant else None,
        **contact,
        expires_at=None if instant else timezone.now() + timedelta(minutes=settings.BOOKING_HOLD_MINUTES),
    )
    system_message(conversation, f"Booking {booking.reference} {'confirmed' if instant else 'requested'} for {check_in} to {check_out}")
    BookingEvent.objects.create(booking=booking, status=booking.status, actor=guest)
    from notifications.models import NotificationType
    from notifications.services import notify_transactional

    manager = current_stay.agent.user if current_stay.agent_id and current_stay.agent.is_active else current_stay.owner
    notify_transactional(
        manager,
        NotificationType.BOOKING_INSTANT_CONFIRMED if instant else NotificationType.BOOKING_REQUESTED,
        "New confirmed booking" if instant else "New booking request",
        f"Booking {booking.reference} was {'confirmed instantly' if instant else 'requested'}.",
        {"route": f"/account/manage/bookings/{booking.id}", "booking_id": str(booking.id), "manager": True},
        f"booking-requested:{booking.id}",
        "booking_updates_email",
    )
    notify_transactional(
        guest, NotificationType.BOOKING_CONFIRMED if instant else NotificationType.BOOKING_REQUEST_SUBMITTED,
        "Booking confirmed" if instant else "Booking request sent",
        f"Booking {booking.reference} is {'confirmed' if instant else 'pending property confirmation'}.",
        {"route": f"/account/bookings/{booking.id}", "booking_id": str(booking.id)},
        f"booking-created-guest:{booking.id}", "booking_updates_email",
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
def transition(booking, target, user, reason="", note=""):
    # Serialize confirmations with new reservations, including holds expiring
    # while a confirmation transaction is still in progress.
    RoomType.objects.select_for_update().get(pk=booking.room_type_id)
    booking = Booking.objects.select_for_update().get(pk=booking.pk)
    if target not in TRANSITIONS.get(booking.status, set()):
        raise ValidationError("Invalid booking transition.")
    manager = can_manage(user, booking.stay)
    if target in (BookingStatus.CONFIRMED, BookingStatus.DECLINED, BookingStatus.COMPLETED) and not manager:
        raise ValidationError("Manager permission required.")
    if target == BookingStatus.CANCELLED and user != booking.guest and not manager:
        raise ValidationError("Permission denied.")
    if target == BookingStatus.EXPIRED and user is not None:
        raise ValidationError("Only the expiry workflow can expire a booking.")
    if target == BookingStatus.DECLINED and reason not in ("NO_AVAILABILITY", "CANNOT_ACCOMMODATE", "PROPERTY_UNAVAILABLE", "OTHER"):
        raise ValidationError({"reason": "Choose a decline reason."})
    if target == BookingStatus.CANCELLED and manager and user != booking.guest and not reason.strip():
        raise ValidationError({"reason": "A cancellation reason is required."})
    if len(reason) > 1000 or len(note) > 1000:
        raise ValidationError("Use at most 1000 characters for reasons and notes.")
    now = timezone.now()
    if target == BookingStatus.CONFIRMED and booking.expires_at and booking.expires_at <= now:
        raise ValidationError("This booking hold has expired. Please submit a new booking request.")
    if target == BookingStatus.COMPLETED and booking.check_out > timezone.localdate():
        raise ValidationError("A booking can only be completed on or after check-out.")
    booking.status = target
    if target == BookingStatus.DECLINED:
        booking.decline_reason = reason
        booking.action_note = note
    if target == BookingStatus.CANCELLED:
        booking.cancellation_reason = reason
    if target == BookingStatus.CONFIRMED:
        booking.confirmed_at = now
    if target == BookingStatus.CANCELLED:
        booking.cancelled_at = now
    if target == BookingStatus.COMPLETED:
        booking.completed_at = now
    booking.save()
    BookingEvent.objects.create(booking=booking, status=target, actor=user, reason=reason, note=note)
    if booking.conversation_id:
        system_message(booking.conversation, f"Booking {booking.reference} {target.lower()}. {reason.replace('_', ' ').lower()} {note}".strip())
    from notifications.models import NotificationType
    from notifications.services import notify_transactional

    kinds = {
        BookingStatus.CONFIRMED: NotificationType.BOOKING_CONFIRMED,
        BookingStatus.DECLINED: NotificationType.BOOKING_DECLINED,
        BookingStatus.CANCELLED: NotificationType.BOOKING_CANCELLED,
        BookingStatus.EXPIRED: NotificationType.BOOKING_EXPIRED,
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
    if target == BookingStatus.CANCELLED and user == booking.guest:
        stay = booking.stay
        operator = stay.agent.user if stay.agent_id and stay.agent.is_active else stay.owner
        notify_transactional(
            operator, NotificationType.BOOKING_CANCELLED, "Guest cancelled a booking",
            f"Booking {booking.reference} was cancelled by the guest.",
            {"route": f"/account/manage/bookings/{booking.id}", "booking_id": str(booking.id), "manager": True},
            f"booking-cancelled-host:{booking.id}", "booking_updates_email",
        )
    return booking


def expire_pending():
    count = 0
    for booking in Booking.objects.filter(status=BookingStatus.PENDING, expires_at__lte=timezone.now()):
        try:
            transition(booking, BookingStatus.EXPIRED, None)
            count += 1
        except ValidationError:
            continue  # Another worker or a guest action already transitioned it.
    return count
