from datetime import time, timedelta
from decimal import Decimal
from random import Random

from django.conf import settings
from django.contrib.auth import get_user_model
from django.core.management.base import BaseCommand, CommandError
from django.db import connection, transaction
from django.utils import timezone
from django.utils.text import slugify

from accounts.models import OnboardingIntent
from agencies.models import Agency, AgentProfile
from alerts.models import SavedSearch, SearchAlertEvent
from bookings.models import Booking, BookingStatus, ViewingRequest
from core.choices import VerificationStatus
from core.seed_data.activity import (
    BOOKING_STATUSES,
    FREQUENCIES,
    MESSAGE_THREADS,
    NOTIFICATION_KINDS,
    PAYMENT_FOR_STATUS,
    SAVED_SEARCHES,
    VIEWING_STATUSES,
)
from core.seed_data.images import PROPERTY_IMAGE_CAPTIONS, ROOM_IMAGE_CAPTIONS, STAY_IMAGE_CAPTIONS, demo_image_file
from core.seed_data.listings import (
    PROPERTY_STATUSES,
    PROPERTY_TITLES,
    STAY_NAMES,
    STAY_STATUSES,
    decimal_price,
    property_description,
    scale_counts,
    stay_description,
)
from core.seed_data.locations import CORE_TOWNS, LOCATIONS, offset_location
from favourites.models import Favourite
from messaging.models import (
    Conversation,
    ConversationParticipant,
    ConversationReport,
    ConversationStatus,
    Message,
    MessageType,
    ParticipantType,
)
from moderation.models import ListingReport, ReportReason, ReportStatus
from notifications.models import EmailDelivery, Notification, NotificationPreference, NotificationType
from properties.models import (
    Amenity,
    AvailabilityStatus,
    ListingStatus,
    PropertyImage,
    PropertyListing,
    PropertyType,
)
from stays.models import RoomAvailability, RoomType, RoomTypeImage, Stay, StayAmenity, StayImage, StayStatus
from verification.models import RequestStatus, VerificationAuditEvent, VerificationRequest, VerificationType

DEMO_DOMAIN = "demo.sureplace.local"
LEGACY_DEMO_DOMAIN = "demo.sureplace.test"
DEMO_PASSWORD = "SurePlaceDemo2026!"
DEFAULT_SEED = 2026
DEFAULT_COUNT = 50
DEMO_AGENCY_SLUGS = [
    "demo-valley-homes-eswatini",
    "demo-mountain-view-realty",
    "demo-central-property-group",
    "demo-horizon-estates",
]


class Command(BaseCommand):
    help = "Create a realistic, idempotent SurePlace demo dataset for development and staging."

    def add_arguments(self, parser):
        parser.add_argument("--reset", action="store_true", help="Delete only seeded demo data before recreating it.")
        parser.add_argument("--yes", action="store_true", help="Required with --reset outside DEBUG.")
        parser.add_argument("--count", type=int, default=DEFAULT_COUNT, help="Approximate total primary listings.")
        parser.add_argument("--seed", type=int, default=DEFAULT_SEED, help="Deterministic random seed.")
        parser.add_argument("--show-credentials", action="store_true", help="Print demo credentials outside DEBUG.")

    def handle(self, *args, **options):
        if options["count"] < 10:
            raise CommandError("--count must be at least 10 so core locations are represented.")
        if options["reset"] and not settings.DEBUG and not options["yes"]:
            raise CommandError("Demo reset outside DEBUG requires both --reset and --yes.")

        with transaction.atomic():
            if options["reset"]:
                self._reset()
            summary = self._seed(options)

        self._print_summary(summary, options)

    def _reset(self):
        User = get_user_model()
        demo_users = User.objects.filter(email__endswith=f"@{DEMO_DOMAIN}") | User.objects.filter(
            email__endswith=f"@{LEGACY_DEMO_DOMAIN}"
        )
        demo_properties = PropertyListing.objects.filter(slug__startswith="demo-")
        demo_stays = Stay.objects.filter(slug__startswith="demo-")
        demo_conversations = (
            Conversation.objects.filter(created_by__in=demo_users)
            | Conversation.objects.filter(property__in=demo_properties)
            | Conversation.objects.filter(stay__in=demo_stays)
        )
        demo_verifications = (
            VerificationRequest.objects.filter(applicant__in=demo_users)
            | VerificationRequest.objects.filter(property__in=demo_properties)
            | VerificationRequest.objects.filter(stay__in=demo_stays)
        )

        demo_email_deliveries = EmailDelivery.objects.filter(
            notification__user__in=demo_users
        ) | EmailDelivery.objects.filter(recipient__endswith=f"@{DEMO_DOMAIN}")
        demo_email_deliveries.delete()
        Notification.objects.filter(user__in=demo_users).delete()
        SearchAlertEvent.objects.filter(saved_search__user__in=demo_users).delete()
        SavedSearch.objects.filter(user__in=demo_users).delete()
        Favourite.objects.filter(user__in=demo_users).delete()
        ViewingRequest.objects.filter(requester__in=demo_users).delete()
        Booking.objects.filter(guest__in=demo_users).delete()
        ConversationReport.objects.filter(conversation__in=demo_conversations).delete()
        Message.objects.filter(conversation__in=demo_conversations).delete()
        ConversationParticipant.objects.filter(conversation__in=demo_conversations).delete()
        demo_conversations.delete()
        ListingReport.objects.filter(property__in=demo_properties).delete()
        ListingReport.objects.filter(stay__in=demo_stays).delete()
        VerificationAuditEvent.objects.filter(verification_request__in=demo_verifications).delete()
        demo_verifications.delete()
        PropertyImage.objects.filter(property__in=demo_properties).delete()
        StayImage.objects.filter(stay__in=demo_stays).delete()
        RoomTypeImage.objects.filter(room_type__stay__in=demo_stays).delete()
        RoomAvailability.objects.filter(room_type__stay__in=demo_stays).delete()
        RoomType.objects.filter(stay__in=demo_stays).delete()
        demo_properties.delete()
        demo_stays.delete()
        AgentProfile.objects.filter(user__in=demo_users).delete()
        Agency.objects.filter(slug__in=DEMO_AGENCY_SLUGS + ["demo-lusushwana-realty"]).delete()
        NotificationPreference.objects.filter(user__in=demo_users).delete()
        demo_users.delete()

    def _seed(self, options):
        rng = Random(options["seed"])
        property_count, stay_count = scale_counts(options["count"])
        users = self._seed_users()
        agencies, agents = self._seed_agencies(users)
        amenities = self._seed_amenities()
        stay_amenities = self._seed_stay_amenities()
        properties = self._seed_properties(property_count, rng, users, agencies, agents, amenities, options["seed"])
        stays, rooms = self._seed_stays(stay_count, rng, users, agencies, agents, stay_amenities, options["seed"])
        self._seed_favourites(users, properties, stays)
        saved_searches = self._seed_saved_searches(users, properties, stays)
        conversations = self._seed_conversations(users, properties, stays)
        viewings = self._seed_viewings(users, properties, conversations)
        bookings = self._seed_bookings(users, stays, rooms, conversations)
        verifications = self._seed_verifications(users, agencies, agents, properties, stays)
        notifications = self._seed_notifications(
            users, properties, stays, saved_searches, bookings, viewings, conversations
        )
        reports = self._seed_reports(users, properties, stays)

        return {
            "users": get_user_model().objects.filter(email__endswith=f"@{DEMO_DOMAIN}").count(),
            "agencies": Agency.objects.filter(slug__in=DEMO_AGENCY_SLUGS).count(),
            "agents": AgentProfile.objects.filter(user__email__endswith=f"@{DEMO_DOMAIN}").count(),
            "properties": len(properties),
            "published_properties": sum(1 for item in properties if item.status == ListingStatus.PUBLISHED),
            "stays": len(stays),
            "published_stays": sum(1 for item in stays if item.status == StayStatus.PUBLISHED),
            "room_types": RoomType.objects.filter(stay__in=stays).count(),
            "property_images": PropertyImage.objects.filter(property__in=properties).count(),
            "stay_images": StayImage.objects.filter(stay__in=stays).count(),
            "room_images": RoomTypeImage.objects.filter(room_type__stay__in=stays).count(),
            "bookings": len(bookings),
            "viewings": len(viewings),
            "conversations": len(conversations),
            "messages": Message.objects.filter(conversation__in=conversations).count(),
            "favourites": Favourite.objects.filter(user__email__endswith=f"@{DEMO_DOMAIN}").count(),
            "saved_searches": len(saved_searches),
            "alert_events": SearchAlertEvent.objects.filter(saved_search__in=saved_searches).count(),
            "notifications": len(notifications),
            "verification_requests": len(verifications),
            "reports": len(reports),
            "seed": options["seed"],
            "reset": options["reset"],
            "db_backend": connection.vendor,
            "postgis": not settings.USE_SQLITE,
        }

    def _seed_users(self):
        User = get_user_model()
        specs = [
            ("seeker1", "Nomsa", "Dlamini", [OnboardingIntent.LOOKING_FOR_PROPERTY]),
            ("seeker2", "Sipho", "Mamba", [OnboardingIntent.LOOKING_FOR_PROPERTY]),
            ("seeker3", "Thandi", "Nkambule", [OnboardingIntent.LOOKING_FOR_PROPERTY]),
            ("owner1", "Bheki", "Simelane", [OnboardingIntent.PROPERTY_OWNER]),
            ("owner2", "Lindiwe", "Shongwe", [OnboardingIntent.PROPERTY_OWNER]),
            ("host1", "Nokwanda", "Maseko", [OnboardingIntent.HOSPITALITY_OPERATOR]),
            ("host2", "Sibusiso", "Tsabedze", [OnboardingIntent.HOSPITALITY_OPERATOR]),
            ("agent1", "Mandla", "Gamedze", [OnboardingIntent.PROPERTY_AGENT]),
            ("agent2", "Zanele", "Khumalo", [OnboardingIntent.PROPERTY_AGENT]),
            ("agent3", "Themba", "Ginindza", [OnboardingIntent.PROPERTY_AGENT]),
            ("staff1", "Ayanda", "Mkhonta", [OnboardingIntent.PROPERTY_AGENT, OnboardingIntent.HOSPITALITY_OPERATOR]),
            ("reviewer", "SurePlace", "Reviewer", [OnboardingIntent.PROPERTY_AGENT]),
        ]
        users = {}
        for index, (local, first, last, intents) in enumerate(specs, start=1):
            user, created = User.objects.update_or_create(
                email=f"{local}@{DEMO_DOMAIN}",
                defaults={
                    "first_name": first,
                    "last_name": last,
                    "phone_number": f"+2687600{index:04d}",
                    "is_email_verified": index % 3 != 0,
                    "is_phone_verified": index % 4 == 0,
                    "is_active": True,
                    "is_staff": local == "reviewer",
                    "onboarding_intents": [intent.value for intent in intents],
                },
            )
            if created or not user.has_usable_password():
                user.set_password(DEMO_PASSWORD)
                user.save(update_fields=["password"])
            users[local] = user
        return users

    def _seed_agencies(self, users):
        specs = [
            ("demo-valley-homes-eswatini", "Valley Homes Eswatini", VerificationStatus.VERIFIED, "Ezulwini"),
            ("demo-mountain-view-realty", "Mountain View Realty", VerificationStatus.VERIFIED, "Mbabane"),
            ("demo-central-property-group", "Central Property Group", VerificationStatus.PENDING, "Manzini"),
            ("demo-horizon-estates", "Horizon Estates", VerificationStatus.UNVERIFIED, "Matsapha"),
        ]
        agencies = []
        for index, (slug, name, status, town) in enumerate(specs, start=1):
            location = next(item for item in LOCATIONS if item["town"] == town)
            agency, _ = Agency.objects.update_or_create(
                slug=slug,
                defaults={
                    "name": name,
                    "description": f"{name} is a fictional SurePlace demo agency for staging and QA.",
                    "phone": f"+2687610{index:04d}",
                    "email": f"agency{index}@{DEMO_DOMAIN}",
                    "region": location["region"],
                    "town": town,
                    "country_code": "SZ",
                    "verification_status": status,
                    "is_active": True,
                },
            )
            agencies.append(agency)
        agent_specs = [
            ("agent1", agencies[0], VerificationStatus.VERIFIED),
            ("agent2", agencies[1], VerificationStatus.PENDING),
            ("agent3", agencies[2], VerificationStatus.UNVERIFIED),
            ("staff1", agencies[0], VerificationStatus.VERIFIED),
            ("reviewer", agencies[3], VerificationStatus.VERIFIED),
        ]
        agents = []
        for index, (local, agency, status) in enumerate(agent_specs, start=1):
            profile, _ = AgentProfile.objects.update_or_create(
                user=users[local],
                agency=agency,
                defaults={
                    "bio": "Fictional SurePlace demo profile used to test agent dashboards and verification badges.",
                    "professional_reference": f"DEMO-AGENT-{index:03d}",
                    "whatsapp_number": f"+2687620{index:04d}",
                    "verification_status": status,
                    "is_active": True,
                },
            )
            agents.append(profile)
        return agencies, agents

    def _seed_amenities(self):
        names = [
            "Wi-Fi",
            "Parking",
            "Security",
            "CCTV",
            "Garden",
            "Pool",
            "Backup power",
            "Furnished",
            "Air conditioning",
            "Balcony",
            "Gated",
            "Pet-friendly",
        ]
        return [
            Amenity.objects.get_or_create(
                slug=slugify(name), defaults={"name": name, "category": "Demo", "is_active": True}
            )[0]
            for name in names
        ]

    def _seed_stay_amenities(self):
        names = [
            "Wi-Fi",
            "Breakfast",
            "Parking",
            "Pool",
            "Restaurant",
            "Laundry",
            "Air conditioning",
            "Conference room",
            "Garden",
            "Airport shuttle",
        ]
        return [
            StayAmenity.objects.get_or_create(
                slug=slugify(name), defaults={"name": name, "category": "Demo", "is_active": True}
            )[0]
            for name in names
        ]

    def _seed_properties(self, count, rng, users, agencies, agents, amenities, seed):
        owners = [users["owner1"], users["owner2"], users["agent1"], users["agent2"]]
        properties = []
        now = timezone.now()
        for index in range(count):
            title, property_type, listing_type, price = PROPERTY_TITLES[index % len(PROPERTY_TITLES)]
            location = LOCATIONS[index % len(LOCATIONS)]
            status = PROPERTY_STATUSES[index % len(PROPERTY_STATUSES)]
            latitude, longitude = offset_location(location, index, seed)
            agency = agencies[index % len(agencies)] if index % 3 != 0 else None
            agent = self._agent_for_agency(agency, agents)
            bedrooms = self._bedrooms(property_type, index)
            bathrooms = None if bedrooms is None else 1 + (index % 3)
            listing, _ = PropertyListing.objects.update_or_create(
                slug=f"demo-{slugify(title)}",
                defaults={
                    "owner": owners[index % len(owners)],
                    "agency": agency,
                    "agent": agent,
                    "title": title,
                    "description": property_description(title, location["town"], listing_type),
                    "listing_type": listing_type,
                    "property_type": property_type,
                    "price": decimal_price(price),
                    "currency": "SZL",
                    "country_code": "SZ",
                    "region": location["region"],
                    "town": location["town"],
                    "suburb": ["CBD", "Extension", "Valley View", "Central", "Outskirts"][index % 5],
                    "address": f"Demo address {index + 1}, {location['town']}",
                    "location": self._point(latitude, longitude),
                    "bedrooms": bedrooms,
                    "bathrooms": bathrooms,
                    "parking_spaces": 0 if property_type == PropertyType.LAND else index % 4,
                    "floor_area": None if property_type == PropertyType.LAND else Decimal(45 + index * 8),
                    "land_area": (
                        Decimal(450 + index * 60)
                        if property_type
                        in {PropertyType.LAND, PropertyType.HOUSE, PropertyType.COMMERCIAL, PropertyType.WAREHOUSE}
                        else None
                    ),
                    "furnished": index % 4 == 0,
                    "pet_friendly": property_type not in self.commercial_types and index % 5 == 0,
                    "status": status,
                    "verification_status": [
                        VerificationStatus.VERIFIED,
                        VerificationStatus.UNVERIFIED,
                        VerificationStatus.PENDING,
                        VerificationStatus.REJECTED,
                    ][index % 4],
                    "availability_status": [
                        AvailabilityStatus.AVAILABLE,
                        AvailabilityStatus.UNDER_OFFER,
                        AvailabilityStatus.UNKNOWN,
                    ][index % 3],
                    "availability_confirmed_at": now - timedelta(days=index % 12),
                    "featured": status == ListingStatus.PUBLISHED and index < 7,
                    "expires_at": now + timedelta(days=90 + index) if status == ListingStatus.PUBLISHED else None,
                },
            )
            listing.amenities.set(rng.sample(amenities, k=min(len(amenities), 3 + index % 4)))
            self._ensure_property_images(listing, 3 + (index % 4))
            properties.append(listing)
        return properties

    def _seed_stays(self, count, rng, users, agencies, agents, amenities, seed):
        owners = [users["host1"], users["host2"], users["owner1"], users["staff1"]]
        stays = []
        rooms = []
        for index in range(count):
            name, stay_type, base_price = STAY_NAMES[index % len(STAY_NAMES)]
            location = LOCATIONS[(index + 2) % len(LOCATIONS)]
            status = STAY_STATUSES[index % len(STAY_STATUSES)]
            latitude, longitude = offset_location(location, index + 40, seed)
            agency = agencies[index % len(agencies)] if index % 4 != 0 else None
            agent = self._agent_for_agency(agency, agents)
            stay, _ = Stay.objects.update_or_create(
                slug=f"demo-{slugify(name)}",
                defaults={
                    "owner": owners[index % len(owners)],
                    "agency": agency,
                    "agent": agent,
                    "name": name,
                    "description": stay_description(name, location["town"]),
                    "stay_type": stay_type,
                    "country_code": "SZ",
                    "region": location["region"],
                    "town": location["town"],
                    "suburb": ["Central", "Valley", "Business District", "Garden Area"][index % 4],
                    "address": f"Demo stay address {index + 1}, {location['town']}",
                    "location": self._point(latitude, longitude),
                    "phone": f"+2687630{index + 1:04d}",
                    "email": f"stay{index + 1}@{DEMO_DOMAIN}",
                    "whatsapp_number": f"+2687640{index + 1:04d}",
                    "check_in_time": time(14, 0),
                    "check_out_time": time(10, 0),
                    "verification_status": [
                        VerificationStatus.VERIFIED,
                        VerificationStatus.UNVERIFIED,
                        VerificationStatus.PENDING,
                    ][index % 3],
                    "status": status,
                    "featured": status == StayStatus.PUBLISHED and index < 5,
                },
            )
            stay.amenities.set(rng.sample(amenities, k=min(len(amenities), 4 + index % 4)))
            self._ensure_stay_images(stay, 3 + (index % 4))
            for room_index in range(1 + (index % 4)):
                room = self._seed_room(stay, room_index, decimal_price(base_price + room_index * 280))
                self._seed_availability(room, index + room_index)
                self._ensure_room_images(room, 1 + (room_index % 3))
                rooms.append(room)
            stays.append(stay)
        return stays, rooms

    def _seed_room(self, stay, index, price):
        names = ["Standard Room", "Deluxe Room", "Executive Suite", "Family Room"]
        adults = 1 + (index % 3)
        children = 2 if index == 3 else index % 2
        room, _ = RoomType.objects.update_or_create(
            stay=stay,
            slug=slugify(names[index]),
            defaults={
                "name": names[index],
                "description": f"{names[index]} at {stay.name}, configured for demo booking and inventory testing.",
                "capacity_adults": adults,
                "capacity_children": children,
                "total_capacity": adults + children,
                "number_of_beds": max(1, adults),
                "bed_configuration": "Double bed" if index % 2 == 0 else "Twin beds",
                "bathroom_type": "Private bathroom",
                "quantity": 2 + index,
                "base_price": price,
                "currency": "SZL",
                "minimum_stay": 2 if index == 2 else 1,
                "is_active": True,
            },
        )
        return room

    def _seed_availability(self, room, offset_seed):
        today = timezone.localdate()
        for offset in range(1, 91):
            blocked = offset % (17 + offset_seed % 4) == 0
            weekend = (today + timedelta(days=offset)).weekday() in {4, 5}
            RoomAvailability.objects.update_or_create(
                room_type=room,
                date=today + timedelta(days=offset),
                defaults={
                    "available_units": 0 if blocked else max(1, room.quantity - (offset + offset_seed) % 2),
                    "custom_price": (room.base_price * Decimal("1.15")).quantize(Decimal("0.01")) if weekend else None,
                    "minimum_stay_override": 2 if weekend and room.minimum_stay == 1 else None,
                    "is_blocked": blocked,
                },
            )

    def _seed_favourites(self, users, properties, stays):
        seekers = [users["seeker1"], users["seeker2"], users["seeker3"]]
        for index, seeker in enumerate(seekers):
            for listing in properties[index : index + 5]:
                Favourite.objects.get_or_create(user=seeker, property=listing)
            for stay in stays[index : index + 3]:
                Favourite.objects.get_or_create(user=seeker, stay=stay)

    def _seed_saved_searches(self, users, properties, stays):
        saved = []
        seekers = [users["seeker1"], users["seeker2"], users["seeker3"]]
        for index, (name, search_type, criteria) in enumerate(SAVED_SEARCHES):
            item, _ = SavedSearch.objects.update_or_create(
                user=seekers[index % len(seekers)],
                name=name,
                defaults={
                    "search_type": search_type,
                    "criteria": criteria,
                    "notifications_enabled": True,
                    "frequency": FREQUENCIES[index % len(FREQUENCIES)],
                    "last_checked_at": timezone.now() - timedelta(hours=index + 1),
                },
            )
            saved.append(item)
        for saved_search in saved[:5]:
            candidates = properties if saved_search.search_type == "PROPERTY" else stays
            target = next(
                (item for item in candidates if item.town.lower() == saved_search.criteria.get("town", "").lower()),
                candidates[0],
            )
            kwargs = {"property": target} if saved_search.search_type == "PROPERTY" else {"stay": target}
            SearchAlertEvent.objects.get_or_create(
                saved_search=saved_search,
                listing_type=saved_search.search_type,
                defaults={"notified_at": timezone.now()},
                **kwargs,
            )
        return saved

    def _seed_conversations(self, users, properties, stays):
        seekers = [users["seeker1"], users["seeker2"], users["seeker3"]]
        conversations = []
        targets = [(property_item, None) for property_item in properties[:7]] + [(None, stay) for stay in stays[:5]]
        for index, (property_item, stay) in enumerate(targets):
            seeker = seekers[index % len(seekers)]
            listing = property_item or stay
            conversation, _ = Conversation.objects.update_or_create(
                created_by=seeker,
                property=property_item,
                stay=stay,
                subject=f"Demo conversation {index + 1}",
                defaults={
                    "assigned_agent": listing.agent,
                    "status": ConversationStatus.ACTIVE,
                    "last_message_at": timezone.now() - timedelta(hours=index),
                },
            )
            manager = listing.agent.user if listing.agent_id else listing.owner
            ConversationParticipant.objects.update_or_create(
                conversation=conversation,
                user=seeker,
                defaults={
                    "participant_type": ParticipantType.SEEKER,
                    "last_read_at": timezone.now() - timedelta(hours=1) if index % 2 == 0 else None,
                },
            )
            ConversationParticipant.objects.update_or_create(
                conversation=conversation,
                user=manager,
                defaults={
                    "participant_type": ParticipantType.AGENT if listing.agent_id else ParticipantType.OWNER,
                    "last_read_at": timezone.now() if index % 3 == 0 else None,
                },
            )
            for body_index, body in enumerate(MESSAGE_THREADS[index % len(MESSAGE_THREADS)]):
                sender = seeker if body_index == 0 else manager
                Message.objects.get_or_create(conversation=conversation, sender=sender, body=body)
            Message.objects.get_or_create(
                conversation=conversation,
                sender=None,
                message_type=MessageType.SYSTEM,
                body="SurePlace demo workflow note: conversation context attached.",
            )
            conversations.append(conversation)
        return conversations

    def _seed_viewings(self, users, properties, conversations):
        seekers = [users["seeker1"], users["seeker2"], users["seeker3"]]
        viewings = []
        today = timezone.localdate()
        for index, status in enumerate(VIEWING_STATUSES * 2):
            listing = properties[index % min(len(properties), 12)]
            viewing, _ = ViewingRequest.objects.update_or_create(
                property=listing,
                requester=seekers[index % len(seekers)],
                requested_date=today + timedelta(days=3 + index),
                requested_time=time(9 + index % 6, 0),
                defaults={
                    "agent": listing.agent,
                    "conversation": conversations[index % len(conversations)],
                    "alternative_date": today + timedelta(days=5 + index) if status == "RESCHEDULE_REQUESTED" else None,
                    "alternative_time": time(14, 0) if status == "RESCHEDULE_REQUESTED" else None,
                    "notes": "Demo viewing request for staging workflows.",
                    "status": status,
                    "confirmed_at": timezone.now() if status in {"CONFIRMED", "COMPLETED"} else None,
                    "cancelled_at": timezone.now() if status == "CANCELLED" else None,
                    "completed_at": timezone.now() if status == "COMPLETED" else None,
                },
            )
            viewings.append(viewing)
        return viewings

    def _seed_bookings(self, users, stays, rooms, conversations):
        seekers = [users["seeker1"], users["seeker2"], users["seeker3"]]
        bookings = []
        today = timezone.localdate()
        eligible_rooms = [room for room in rooms if room.stay.status == StayStatus.PUBLISHED]
        for index, status in enumerate((BOOKING_STATUSES * 2)[:12]):
            room = eligible_rooms[index % len(eligible_rooms)]
            check_in = (
                today - timedelta(days=18 + index)
                if status in {"COMPLETED", "EXPIRED"}
                else today + timedelta(days=10 + index * 3)
            )
            check_out = check_in + timedelta(days=max(2, room.minimum_stay))
            nights = (check_out - check_in).days
            subtotal = room.base_price * nights
            nightly = [
                {"date": (check_in + timedelta(days=offset)).isoformat(), "price": str(room.base_price)}
                for offset in range(nights)
            ]
            guest = seekers[index % len(seekers)]
            booking, _ = Booking.objects.update_or_create(
                guest=guest,
                idempotency_key=f"demo-booking-{index + 1:02d}",
                defaults={
                    "stay": room.stay,
                    "room_type": room,
                    "conversation": conversations[index % len(conversations)],
                    "check_in": check_in,
                    "check_out": check_out,
                    "adults": min(2, room.capacity_adults),
                    "children": min(1, room.capacity_children),
                    "rooms": 1,
                    "nightly_pricing": nightly,
                    "nightly_subtotal": subtotal,
                    "taxes": 0,
                    "fees": 0,
                    "total": subtotal,
                    "currency": room.currency,
                    "status": status,
                    "payment_status": PAYMENT_FOR_STATUS[status],
                    "guest_name": f"{guest.first_name} {guest.last_name}".strip() or guest.email,
                    "guest_email": guest.email,
                    "guest_phone": f"+2687650{index + 1:04d}",
                    "special_requests": "Demo booking created for QA.",
                    "expires_at": (
                        timezone.now() - timedelta(hours=2)
                        if status == BookingStatus.EXPIRED
                        else timezone.now() + timedelta(minutes=30)
                    ),
                    "confirmed_at": (
                        timezone.now() if status in {BookingStatus.CONFIRMED, BookingStatus.COMPLETED} else None
                    ),
                    "cancelled_at": timezone.now() if status == BookingStatus.CANCELLED else None,
                    "completed_at": timezone.now() if status == BookingStatus.COMPLETED else None,
                },
            )
            bookings.append(booking)
        return bookings

    def _seed_verifications(self, users, agencies, agents, properties, stays):
        reviewer = users["reviewer"]
        specs = [
            (users["seeker1"], VerificationType.IDENTITY, RequestStatus.APPROVED, {}),
            (users["seeker2"], VerificationType.IDENTITY, RequestStatus.SUBMITTED, {}),
            (agents[0].user, VerificationType.AGENT, RequestStatus.APPROVED, {"agent_profile": agents[0]}),
            (agents[1].user, VerificationType.AGENT, RequestStatus.UNDER_REVIEW, {"agent_profile": agents[1]}),
            (users["staff1"], VerificationType.AGENCY, RequestStatus.APPROVED, {"agency": agencies[0]}),
            (users["agent3"], VerificationType.AGENCY, RequestStatus.REJECTED, {"agency": agencies[2]}),
            (properties[0].owner, VerificationType.PROPERTY, RequestStatus.APPROVED, {"property": properties[0]}),
            (properties[1].owner, VerificationType.PROPERTY, RequestStatus.REJECTED, {"property": properties[1]}),
            (stays[0].owner, VerificationType.STAY, RequestStatus.APPROVED, {"stay": stays[0]}),
            (stays[1].owner, VerificationType.STAY, RequestStatus.SUBMITTED, {"stay": stays[1]}),
        ]
        requests = []
        for index, (applicant, verification_type, status, target) in enumerate(specs, start=1):
            request, _ = VerificationRequest.objects.update_or_create(
                applicant=applicant,
                verification_type=verification_type,
                **target,
                defaults={
                    "status": status,
                    "submitted_at": timezone.now() - timedelta(days=index),
                    "reviewed_at": (
                        timezone.now() - timedelta(days=index - 1)
                        if status in {RequestStatus.APPROVED, RequestStatus.REJECTED}
                        else None
                    ),
                    "reviewed_by": reviewer if status in {RequestStatus.APPROVED, RequestStatus.REJECTED} else None,
                    "rejection_reason": (
                        "Demo rejection: supporting details need correction."
                        if status == RequestStatus.REJECTED
                        else ""
                    ),
                    "reviewer_notes": "Demo verification scenario.",
                },
            )
            VerificationAuditEvent.objects.get_or_create(
                verification_request=request,
                actor=reviewer,
                event_type=f"DEMO_{status}",
                defaults={"previous_status": "", "new_status": status, "notes": "Seeded demo audit event."},
            )
            requests.append(request)
        properties[0].verification_status = VerificationStatus.VERIFIED
        properties[0].save(update_fields=["verification_status", "updated_at"])
        scoped_agent_listing = next(
            (item for item in properties if item.agent_id == agents[0].id and item.id != properties[0].id), None
        )
        if scoped_agent_listing:
            scoped_agent_listing.verification_status = VerificationStatus.UNVERIFIED
            scoped_agent_listing.save(update_fields=["verification_status", "updated_at"])
        stays[0].verification_status = VerificationStatus.VERIFIED
        stays[0].save(update_fields=["verification_status", "updated_at"])
        return requests

    def _seed_notifications(self, users, properties, stays, saved_searches, bookings, viewings, conversations):
        recipients = [
            users["seeker1"],
            users["seeker2"],
            users["owner1"],
            users["host1"],
            users["agent1"],
            users["staff1"],
        ]
        notifications = []
        for index, (kind, title, message) in enumerate(NOTIFICATION_KINDS * 2):
            notification, _ = Notification.objects.update_or_create(
                user=recipients[index % len(recipients)],
                event_key=f"demo-notification-{index + 1:02d}",
                defaults={
                    "notification_type": getattr(NotificationType, kind),
                    "title": title,
                    "message": message,
                    "data": {
                        "route": ["/account/messages", "/account/viewings", "/account/bookings", "/account/alerts"][
                            index % 4
                        ],
                        "property_id": str(properties[index % len(properties)].id),
                        "stay_id": str(stays[index % len(stays)].id),
                        "booking_id": str(bookings[index % len(bookings)].id),
                        "viewing_id": str(viewings[index % len(viewings)].id),
                        "conversation_id": str(conversations[index % len(conversations)].id),
                        "saved_search_id": str(saved_searches[index % len(saved_searches)].id),
                        "match_count": 2 + index % 4,
                    },
                    "is_read": index % 3 == 0,
                    "read_at": timezone.now() if index % 3 == 0 else None,
                },
            )
            notifications.append(notification)
        return notifications

    def _seed_reports(self, users, properties, stays):
        reports = []
        specs = [
            {
                "property": properties[2],
                "reason": ReportReason.INCORRECT,
                "details": "Demo report: price needs confirmation.",
            },
            {
                "property": properties[5],
                "reason": ReportReason.DUPLICATE,
                "details": "Demo report: possible duplicate listing.",
            },
            {"stay": stays[3], "reason": ReportReason.UNAVAILABLE, "details": "Demo report: dates may be unavailable."},
        ]
        for index, spec in enumerate(specs, start=1):
            report, _ = ListingReport.objects.update_or_create(
                reporter=users[f"seeker{1 + index % 3}"],
                **{key: value for key, value in spec.items() if key in {"property", "stay"}},
                defaults={
                    "reason": spec["reason"],
                    "details": spec["details"],
                    "status": [ReportStatus.OPEN, ReportStatus.UNDER_REVIEW, ReportStatus.RESOLVED][index - 1],
                    "assigned_to": users["reviewer"],
                    "reviewed_at": timezone.now() if index == 3 else None,
                    "resolution_notes": "Demo moderation resolution." if index == 3 else "",
                },
            )
            reports.append(report)
        return reports

    def _ensure_property_images(self, listing, count):
        self._sync_images(listing.images, PropertyImage, "property", listing, PROPERTY_IMAGE_CAPTIONS, count)

    def _ensure_stay_images(self, stay, count):
        self._sync_images(stay.images, StayImage, "stay", stay, STAY_IMAGE_CAPTIONS, count)

    def _ensure_room_images(self, room, count):
        self._sync_images(room.images, RoomTypeImage, "room_type", room, ROOM_IMAGE_CAPTIONS, count)

    def _sync_images(self, related_manager, model, foreign_key, parent, captions, count):
        related_manager.filter(caption__startswith="Demo ").delete()
        parent_slug = getattr(parent, "slug", None) or getattr(parent.stay, "slug", "room")
        for index, caption in enumerate(captions[:count]):
            image = model(**{foreign_key: parent}, caption=f"Demo {caption}", sort_order=index, is_cover=index == 0)
            image.image.save(
                f"demo/{foreign_key}/{parent_slug}-{index + 1}.png", demo_image_file("demo.png"), save=False
            )
            image.save()

    def _point(self, latitude, longitude):
        if settings.USE_SQLITE:
            return {"latitude": round(latitude, 6), "longitude": round(longitude, 6)}
        from django.contrib.gis.geos import Point

        return Point(longitude, latitude, srid=4326)

    @property
    def commercial_types(self):
        return {PropertyType.OFFICE, PropertyType.SHOP, PropertyType.WAREHOUSE, PropertyType.COMMERCIAL}

    def _bedrooms(self, property_type, index):
        return None if property_type in {PropertyType.LAND, *self.commercial_types} else 1 + (index % 4)

    def _agent_for_agency(self, agency, agents):
        if not agency:
            return None
        return next((candidate for candidate in agents if candidate.agency_id == agency.id), None)

    def _print_summary(self, summary, options):
        self.stdout.write(self.style.SUCCESS("SurePlace demo data is ready."))
        for label, key in [
            ("Seed", "seed"),
            ("Reset performed", "reset"),
            ("DB backend", "db_backend"),
            ("PostGIS mode", "postgis"),
            ("Users", "users"),
            ("Agencies", "agencies"),
            ("Agents", "agents"),
            ("Properties", "properties"),
            ("Published properties", "published_properties"),
            ("Stays", "stays"),
            ("Published stays", "published_stays"),
            ("Room types", "room_types"),
            ("Property images", "property_images"),
            ("Stay images", "stay_images"),
            ("Room images", "room_images"),
            ("Bookings", "bookings"),
            ("Viewings", "viewings"),
            ("Conversations", "conversations"),
            ("Messages", "messages"),
            ("Favourites", "favourites"),
            ("Saved searches", "saved_searches"),
            ("Search alert events", "alert_events"),
            ("Notifications", "notifications"),
            ("Verification requests", "verification_requests"),
            ("Moderation reports", "reports"),
        ]:
            value = summary[key]
            if isinstance(value, bool):
                value = "yes" if value else "no"
            self.stdout.write(f"{label}: {value}")
        if settings.DEBUG or options["show_credentials"]:
            self.stdout.write("")
            self.stdout.write("Demo login:")
            self.stdout.write(f"seeker1@{DEMO_DOMAIN}")
            self.stdout.write(f"password: {DEMO_PASSWORD}")
        self.stdout.write("")
        self.stdout.write(f"Core Explore Eswatini towns covered: {', '.join(sorted(CORE_TOWNS))}")
