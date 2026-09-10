from alerts.models import Frequency, SearchType
from bookings.models import BookingStatus, PaymentStatus, ViewingStatus

SAVED_SEARCHES = [
    (
        "Mbabane rentals under E8,000",
        SearchType.PROPERTY,
        {"town": "Mbabane", "listing_type": "RENT", "max_price": 8000},
    ),
    ("Ezulwini 3 bedroom homes", SearchType.PROPERTY, {"town": "Ezulwini", "min_bedrooms": 3}),
    ("Manzini apartments", SearchType.PROPERTY, {"town": "Manzini", "property_type": "APARTMENT"}),
    ("Matsapha commercial spaces", SearchType.PROPERTY, {"town": "Matsapha", "property_type": "COMMERCIAL"}),
    ("Siteki homes for sale", SearchType.PROPERTY, {"town": "Siteki", "listing_type": "SALE"}),
    ("Ezulwini stays for two", SearchType.STAY, {"town": "Ezulwini"}),
    ("Guest houses under E1,200", SearchType.STAY, {"stay_type": "GUEST_HOUSE", "max_price": 1200}),
]

VIEWING_STATUSES = [
    ViewingStatus.PENDING,
    ViewingStatus.CONFIRMED,
    ViewingStatus.DECLINED,
    ViewingStatus.CANCELLED,
    ViewingStatus.COMPLETED,
    ViewingStatus.RESCHEDULE_REQUESTED,
]

BOOKING_STATUSES = [
    BookingStatus.PENDING,
    BookingStatus.CONFIRMED,
    BookingStatus.DECLINED,
    BookingStatus.CANCELLED,
    BookingStatus.COMPLETED,
    BookingStatus.EXPIRED,
]

PAYMENT_FOR_STATUS = {
    BookingStatus.PENDING: PaymentStatus.UNPAID,
    BookingStatus.CONFIRMED: PaymentStatus.PARTIALLY_PAID,
    BookingStatus.DECLINED: PaymentStatus.NOT_REQUIRED,
    BookingStatus.CANCELLED: PaymentStatus.REFUNDED,
    BookingStatus.COMPLETED: PaymentStatus.PAID,
    BookingStatus.EXPIRED: PaymentStatus.UNPAID,
}

MESSAGE_THREADS = [
    ["Hi, is this property still available?", "Yes, it is available. Would you like to view it this week?"],
    ["Would Saturday morning work for a viewing?", "Saturday at 10:00 works well."],
    ["Is parking included?", "Yes, there is allocated parking on site."],
    ["Can I check in after 7 PM?", "Late check-in can be arranged with advance notice."],
    ["Is the area close to public transport?", "There are regular routes nearby and easy road access."],
]

NOTIFICATION_KINDS = [
    ("NEW_MESSAGE", "New SurePlace message", "You have a new reply about a listing."),
    ("VIEWING_CONFIRMED", "Viewing confirmed", "Your viewing time has been confirmed."),
    ("BOOKING_REQUESTED", "New booking request", "A guest requested a booking."),
    ("BOOKING_CONFIRMED", "Booking confirmed", "Your booking has been confirmed."),
    ("VERIFICATION_UPDATE", "Verification approved", "A demo verification was approved."),
    ("SAVED_SEARCH_MATCH", "Saved search match", "New listings match one of your saved searches."),
]

FREQUENCIES = [Frequency.INSTANT, Frequency.DAILY, Frequency.WEEKLY]
