import threading
from datetime import date, timedelta
from django.core.exceptions import ValidationError
from django.db import close_old_connections
from django.test import TransactionTestCase, skipUnlessDBFeature
from accounts.models import User
from stays.models import RoomType, Stay, StayStatus, StayType
from .models import Booking
from .services import create_booking


class BookingConcurrencyTests(TransactionTestCase):
    @skipUnlessDBFeature("has_select_for_update")
    def test_only_one_guest_can_reserve_last_room(self):
        host = User.objects.create_user(
            email="host-lock@example.com", password="StrongPass123!", first_name="Host", last_name="Lock"
        )
        guests = [
            User.objects.create_user(
                email=f"guest-lock-{i}@example.com", password="StrongPass123!", first_name="Guest", last_name=str(i)
            )
            for i in range(2)
        ]
        stay = Stay.objects.create(
            owner=host, name="Lock Lodge", description="Test", stay_type=StayType.LODGE, status=StayStatus.PUBLISHED
        )
        room = RoomType.objects.create(
            stay=stay, name="Last room", capacity_adults=2, total_capacity=2, quantity=1, base_price=500
        )
        start = date.today() + timedelta(days=10)
        barrier = threading.Barrier(2)
        outcomes = []

        def reserve(guest_id):
            close_old_connections()
            guest = User.objects.get(pk=guest_id)
            local_stay = Stay.objects.get(pk=stay.pk)
            local_room = RoomType.objects.get(pk=room.pk)
            barrier.wait()
            try:
                create_booking(
                    guest=guest,
                    stay=local_stay,
                    room_type=local_room,
                    check_in=start,
                    check_out=start + timedelta(days=1),
                    adults=1,
                    children=0,
                    rooms=1,
                    guest_name="Guest",
                    guest_email=guest.email,
                )
                outcomes.append("created")
            except ValidationError:
                outcomes.append("rejected")
            finally:
                close_old_connections()

        threads = [threading.Thread(target=reserve, args=(guest.id,)) for guest in guests]
        [thread.start() for thread in threads]
        [thread.join() for thread in threads]
        self.assertEqual(outcomes.count("created"), 1)
        self.assertEqual(Booking.objects.count(), 1)
