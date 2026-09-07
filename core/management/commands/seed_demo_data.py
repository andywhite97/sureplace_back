from datetime import date, timedelta
from decimal import Decimal
from django.conf import settings
from django.contrib.auth import get_user_model
from django.core.management.base import BaseCommand, CommandError
from django.db import transaction
from django.utils import timezone
from agencies.models import Agency, AgentProfile
from alerts.models import SavedSearch, SearchType
from bookings.models import Booking, ViewingRequest
from core.choices import VerificationStatus
from favourites.models import Favourite
from messaging.models import Conversation, ConversationParticipant, Message, ParticipantType
from notifications.models import Notification, NotificationType
from properties.models import Amenity, AvailabilityStatus, ListingStatus, ListingType, PropertyListing, PropertyType
from stays.models import RoomAvailability, RoomType, Stay, StayStatus, StayType
from verification.models import RequestStatus, VerificationRequest, VerificationType

EMAILS = [
    "seeker@demo.sureplace.test",
    "owner@demo.sureplace.test",
    "agent@demo.sureplace.test",
    "staff@demo.sureplace.test",
    "host@demo.sureplace.test",
]


class Command(BaseCommand):
    help = "Create fictional, idempotent SurePlace frontend demo data."

    def add_arguments(self, parser):
        parser.add_argument("--reset", action="store_true")
        parser.add_argument("--yes", action="store_true")

    def handle(self, *args, **options):
        User = get_user_model()
        if options["reset"]:
            if not settings.DEBUG or not options["yes"]:
                raise CommandError("Demo reset requires DEBUG=True and both --reset --yes.")
        with transaction.atomic():
            return self._seed(User, options)

    def _seed(self, User, options):
        if options["reset"]:
            User.objects.filter(email__in=EMAILS).delete()
            Agency.objects.filter(slug="demo-lusushwana-realty").delete()
        users = []
        for email, first in zip(EMAILS, ["Seeker", "Owner", "Agent", "Staff", "Host"]):
            obj, created = User.objects.get_or_create(email=email, defaults={"first_name": first, "last_name": "Demo"})
            if created:
                obj.set_password("DemoPass123!")
                obj.save(update_fields=["password"])
            users.append(obj)
        seeker, owner, agent_user, staff, host = users
        agency, _ = Agency.objects.get_or_create(
            slug="demo-lusushwana-realty",
            defaults={
                "name": "Lusushwana Realty",
                "country_code": "SZ",
                "region": "Hhohho",
                "town": "Mbabane",
                "verification_status": VerificationStatus.VERIFIED,
            },
        )
        agent, _ = AgentProfile.objects.get_or_create(
            user=agent_user, agency=agency, defaults={"verification_status": VerificationStatus.VERIFIED}
        )
        AgentProfile.objects.get_or_create(user=staff, agency=agency)
        towns = [
            ("Mbabane", "Hhohho", -26.3054, 31.1367),
            ("Manzini", "Manzini", -26.4988, 31.3800),
            ("Matsapha", "Manzini", -26.5167, 31.3167),
            ("Ezulwini", "Hhohho", -26.4017, 31.1775),
            ("Lobamba", "Hhohho", -26.4667, 31.2000),
            ("Siteki", "Lubombo", -26.4500, 31.9500),
            ("Nhlangano", "Shiselweni", -27.1122, 31.1983),
            ("Malkerns", "Manzini", -26.5667, 31.1833),
        ]
        properties = []
        for index, (town, region, latitude, longitude) in enumerate(towns):
            item, _ = PropertyListing.objects.get_or_create(
                owner=owner,
                title=f"Demo {town} Home {index+1}",
                defaults={
                    "description": "Fictional demonstration listing.",
                    "listing_type": ListingType.RENT if index % 2 else ListingType.SALE,
                    "property_type": PropertyType.HOUSE if index % 3 else PropertyType.APARTMENT,
                    "price": Decimal(3500 + index * 1250),
                    "country_code": "SZ",
                    "region": region,
                    "town": town,
                    "status": ListingStatus.PUBLISHED,
                    "featured": index < 3,
                    "verification_status": (
                        VerificationStatus.VERIFIED if index % 2 == 0 else VerificationStatus.UNVERIFIED
                    ),
                    "agency": agency,
                    "agent": agent,
                },
            )
            # Keep repeated seed runs useful after the homepage contract evolves.
            # The featured endpoint only exposes published listings whose
            # availability has been explicitly confirmed.
            item.featured = index < 3
            item.status = ListingStatus.PUBLISHED
            if item.featured:
                item.availability_status = AvailabilityStatus.AVAILABLE
                item.availability_confirmed_at = timezone.now()
            if settings.USE_SQLITE:
                item.location = {"latitude": latitude, "longitude": longitude}
            else:
                from django.contrib.gis.geos import Point

                item.location = Point(longitude, latitude, srid=4326)
            item.save(
                update_fields=[
                    "featured",
                    "status",
                    "availability_status",
                    "availability_confirmed_at",
                    "location",
                    "updated_at",
                ]
            )
            demo_amenities = list(Amenity.objects.filter(is_active=True).order_by("name")[:3])
            item.amenities.set(demo_amenities)
            properties.append(item)
        stays = []
        for index, (town, region, latitude, longitude) in enumerate(towns[:4]):
            stay, _ = Stay.objects.get_or_create(
                owner=host,
                name=f"Demo {town} Lodge",
                defaults={
                    "description": "Fictional demonstration stay.",
                    "stay_type": StayType.LODGE,
                    "country_code": "SZ",
                    "region": region,
                    "town": town,
                    "status": StayStatus.PUBLISHED,
                    "featured": index == 0,
                },
            )
            stay.featured = index == 0
            stay.status = StayStatus.PUBLISHED
            if settings.USE_SQLITE:
                stay.location = {"latitude": latitude, "longitude": longitude}
            else:
                from django.contrib.gis.geos import Point

                stay.location = Point(longitude, latitude, srid=4326)
            stay.save(update_fields=["featured", "status", "location", "updated_at"])
            room, _ = RoomType.objects.get_or_create(
                stay=stay,
                name="Standard Room",
                defaults={
                    "capacity_adults": 2,
                    "total_capacity": 2,
                    "quantity": 3,
                    "base_price": Decimal(850 + index * 100),
                },
            )
            for offset in range(14):
                RoomAvailability.objects.get_or_create(
                    room_type=room, date=date.today() + timedelta(days=offset + 1), defaults={"available_units": 3}
                )
            stays.append((stay, room))
        Favourite.objects.get_or_create(user=seeker, property=properties[0])
        SavedSearch.objects.get_or_create(
            user=seeker,
            name="Mbabane rentals",
            defaults={"search_type": SearchType.PROPERTY, "criteria": {"town": "Mbabane", "listing_type": "RENT"}},
        )
        conversation, _ = Conversation.objects.get_or_create(
            property=properties[0], created_by=seeker, defaults={"subject": "Demo enquiry"}
        )
        ConversationParticipant.objects.get_or_create(
            conversation=conversation, user=seeker, defaults={"participant_type": ParticipantType.SEEKER}
        )
        ConversationParticipant.objects.get_or_create(
            conversation=conversation, user=owner, defaults={"participant_type": ParticipantType.OWNER}
        )
        Message.objects.get_or_create(
            conversation=conversation, sender=seeker, body="Is this fictional demo home available?"
        )
        ViewingRequest.objects.get_or_create(
            property=properties[0],
            requester=seeker,
            requested_date=date.today() + timedelta(days=3),
            requested_time="10:00",
            defaults={"conversation": conversation},
        )
        stay, room = stays[0]
        Booking.objects.get_or_create(
            guest=seeker,
            idempotency_key="demo-booking",
            defaults={
                "stay": stay,
                "room_type": room,
                "check_in": date.today() + timedelta(days=7),
                "check_out": date.today() + timedelta(days=9),
                "adults": 2,
                "children": 0,
                "rooms": 1,
                "nightly_pricing": [],
                "nightly_subtotal": 1700,
                "total": 1700,
                "guest_name": "Seeker Demo",
                "guest_email": seeker.email,
            },
        )
        Notification.objects.get_or_create(
            user=seeker,
            event_key="demo-welcome",
            defaults={
                "notification_type": NotificationType.SYSTEM,
                "title": "Welcome to SurePlace",
                "message": "This is fictional demo data.",
            },
        )
        VerificationRequest.objects.get_or_create(
            applicant=owner,
            verification_type=VerificationType.PROPERTY,
            property=properties[0],
            defaults={"status": RequestStatus.APPROVED},
        )
        self.stdout.write(self.style.SUCCESS("Demo data is ready: 5 users, 8 properties, and 4 stays."))
