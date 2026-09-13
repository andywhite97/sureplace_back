from datetime import date, timedelta
from django.core.exceptions import ValidationError
from rest_framework.test import APITestCase
from django.test import override_settings
from accounts.models import User
from .models import *
from .services import room_availability


@override_settings(PASSWORD_HASHERS=["django.contrib.auth.hashers.MD5PasswordHasher"])
class StayPhaseTests(APITestCase):

    def setUp(self):
        self.owner = User.objects.create_user(
            is_email_verified=True,
            email="host@example.com",
            password="StrongPass123!",
            first_name="Host",
            last_name="One",
        )
        self.other = User.objects.create_user(
            is_email_verified=True,
            email="otherstay@example.com",
            password="StrongPass123!",
            first_name="Other",
            last_name="One",
        )
        self.stay = Stay.objects.create(
            owner=self.owner,
            name="Mountain Lodge",
            description="Lovely mountain accommodation. " * 5,
            stay_type=StayType.LODGE,
            region="Hhohho",
            town="Mbabane",
            location={"latitude": -26.3, "longitude": 31.1},
            status=StayStatus.PUBLISHED,
            featured=True,
        )
        self.room = RoomType.objects.create(
            stay=self.stay,
            name="Deluxe Room",
            capacity_adults=2,
            capacity_children=1,
            total_capacity=3,
            quantity=3,
            base_price="850",
            minimum_stay=1,
        )

    def test_ids_slug_and_public_visibility(self):
        other = Stay.objects.create(owner=self.owner, name="Mountain Lodge", stay_type=StayType.LODGE)
        self.assertNotEqual(self.stay.slug, other.slug)
        self.assertNotEqual(self.stay.public_id, other.public_id)
        self.assertEqual(self.client.get("/api/stays/").status_code, 200)
        self.assertEqual(self.client.get(f"/api/stays/{self.stay.slug}/").status_code, 200)

    def test_authenticated_creation_and_permissions(self):
        self.client.force_authenticate(self.owner)
        response = self.client.post(
            "/api/stays/",
            {"name": "New Stay", "stay_type": "HOTEL", "latitude": -26.2, "longitude": 31.2},
            format="json",
        )
        self.assertEqual(response.status_code, 201, response.data)
        self.client.force_authenticate(self.other)
        self.assertEqual(
            self.client.patch(f"/api/stays/{self.stay.id}/", {"name": "No"}, format="json").status_code, 403
        )

    def test_owner_can_create_room_on_draft_stay(self):
        draft = Stay.objects.create(owner=self.owner, name="Draft", stay_type=StayType.HOTEL)
        self.client.force_authenticate(self.owner)
        response = self.client.post(
            f"/api/stays/{draft.id}/rooms/",
            {
                "name": "Luxury Suite",
                "description": "Great",
                "capacity_adults": 2,
                "capacity_children": 0,
                "total_capacity": 2,
                "number_of_beds": 1,
                "bed_configuration": "Queen bed",
                "bathroom_type": "Private",
                "quantity": 3,
                "base_price": "1500.00",
                "currency": "SZL",
                "minimum_stay": 1,
                "is_active": True,
            },
            format="json",
        )
        self.assertEqual(response.status_code, 201, response.data)
        room = draft.room_types.get()
        self.assertEqual(room.name, "Luxury Suite")
        self.assertEqual(room.slug, "luxury-suite")

    def test_room_validation_is_structured(self):
        self.client.force_authenticate(self.owner)
        response = self.client.post(
            f"/api/stays/{self.stay.id}/rooms/",
            {"name": "Invalid", "total_capacity": 0, "number_of_beds": 0, "quantity": 0, "base_price": "0"},
            format="json",
        )
        self.assertEqual(response.status_code, 400)
        self.assertIn("errors", response.data)
        self.assertIn("total_capacity", response.data["errors"])

    def test_submission_requires_active_room(self):
        draft = Stay.objects.create(owner=self.owner, name="Draft", stay_type=StayType.HOTEL)
        self.client.force_authenticate(self.owner)
        response = self.client.post(f"/api/stays/{draft.id}/submit/")
        self.assertEqual(response.status_code, 400)
        self.assertEqual(
            response.data["errors"]["room_types"][0],
            "Add at least one active room type before submitting this stay.",
        )

    def test_featured_search_and_bounds(self):
        self.assertEqual(self.client.get("/api/stays/featured/").data["count"], 1)
        self.assertEqual(self.client.get("/api/stays/", {"search": "Mountain"}).data["count"], 1)

    def test_image_order_and_cover(self):
        a = StayImage.objects.create(stay=self.stay, image="a.jpg", sort_order=2, is_cover=True)
        b = StayImage.objects.create(stay=self.stay, image="b.jpg", sort_order=1, is_cover=True)
        a.refresh_from_db()
        self.assertFalse(a.is_cover)
        self.assertEqual(list(self.stay.images.all()), [b, a])
        x = RoomTypeImage.objects.create(room_type=self.room, image="x.jpg", sort_order=2, is_cover=True)
        y = RoomTypeImage.objects.create(room_type=self.room, image="y.jpg", sort_order=1, is_cover=True)
        x.refresh_from_db()
        self.assertFalse(x.is_cover)
        self.assertEqual(list(self.room.images.all()), [y, x])

    def test_room_validation_and_effective_price(self):
        bad = RoomType(stay=self.stay, name="Bad", base_price=-1, minimum_stay=0, total_capacity=0, capacity_adults=1)
        self.assertRaises(ValidationError, bad.full_clean)
        day = date.today() + timedelta(days=1)
        RoomAvailability.objects.create(room_type=self.room, date=day, available_units=2, custom_price="1200")
        self.assertEqual(str(self.room.effective_price(day)), "1200.00")

    def test_availability_rules_and_total(self):
        start = date.today() + timedelta(days=10)
        RoomAvailability.objects.create(room_type=self.room, date=start, available_units=2, custom_price="1000")
        result = room_availability(self.room, start, start + timedelta(days=2), 2, 1, 1)
        self.assertTrue(result["available"])
        self.assertEqual(result["total"], "1850.00")
        row = self.room.availability.get(date=start)
        row.is_blocked = True
        row.save()
        self.assertFalse(room_availability(self.room, start, start + timedelta(days=2), 2, 1, 1)["available"])
        self.assertFalse(room_availability(self.room, start, start + timedelta(days=2), 8, 0, 1)["available"])
        with self.assertRaises(ValidationError):
            room_availability(self.room, start, start, 1, 0, 1)

    def test_availability_endpoint_and_bulk_management(self):
        start = date.today() + timedelta(days=20)
        params = {"check_in": start, "check_out": start + timedelta(days=2), "adults": 2, "children": 0, "rooms": 1}
        self.assertEqual(len(self.client.get(f"/api/stays/{self.stay.id}/availability/", params).data["room_types"]), 1)
        self.client.force_authenticate(self.owner)
        payload = {
            "start_date": str(start),
            "end_date": str(start + timedelta(days=2)),
            "available_units": 2,
            "custom_price": "999",
        }
        response = self.client.post(f"/api/rooms/{self.room.id}/availability/bulk/", payload, format="json")
        self.assertEqual(response.status_code, 200, response.data)
        self.assertEqual(response.data["updated"], 3)

    def test_lifecycle(self):
        draft = Stay.objects.create(
            owner=self.owner,
            name="Draft",
            description="complete " * 20,
            stay_type=StayType.HOTEL,
            region="Manzini",
            town="Manzini",
            location={"latitude": -26.5, "longitude": 31.4},
        )
        RoomType.objects.create(stay=draft, name="Suite", base_price="850")
        self.client.force_authenticate(self.owner)
        self.assertEqual(self.client.post(f"/api/stays/{draft.id}/submit/").status_code, 200)
        self.assertEqual(self.client.post(f"/api/stays/{self.stay.id}/pause/").status_code, 200)

    def test_manager_mine_returns_manageable_stays_with_quality(self):
        draft = Stay.objects.create(owner=self.owner, name="Draft Stay", stay_type=StayType.HOTEL)
        self.client.force_authenticate(self.owner)
        response = self.client.get("/api/stays/mine/")
        ids = [item["id"] for item in response.data["results"]]
        self.assertIn(str(self.stay.id), ids)
        self.assertIn(str(draft.id), ids)
        self.assertIn("quality", response.data["results"][0])


@override_settings(PASSWORD_HASHERS=["django.contrib.auth.hashers.MD5PasswordHasher"])
class StayRoomPhotoSubmissionTests(APITestCase):
    def setUp(self):
        StayPhaseTests.setUp(self)
        import tempfile
        from django.test import override_settings

        self.media = tempfile.TemporaryDirectory()
        self.addCleanup(self.media.cleanup)
        self.override = override_settings(MEDIA_ROOT=self.media.name)
        self.override.enable()
        self.addCleanup(self.override.disable)
        self.client.force_authenticate(self.owner)
        self.stay.status = StayStatus.DRAFT
        self.stay.save()

    def photo(self, name="photo.png", fmt="PNG"):
        from io import BytesIO
        from PIL import Image
        from django.core.files.uploadedfile import SimpleUploadedFile

        stream = BytesIO()
        Image.new("RGB", (10, 10), "green").save(stream, format=fmt)
        return SimpleUploadedFile(name, stream.getvalue(), content_type="image/" + fmt.lower())

    def test_room_upload_cover_reorder_delete_and_persistence(self):
        url = f"/api/rooms/{self.room.id}/images/"
        first = self.client.post(url, {"image": self.photo(), "sort_order": 0}, format="multipart")
        self.assertEqual(first.status_code, 201, first.data)
        self.assertTrue(first.data["is_cover"])
        self.assertTrue(first.data["image"].startswith("http://testserver/"))
        image = RoomTypeImage.objects.get(pk=first.data["id"])
        self.assertEqual(image.room_type_id, self.room.id)
        self.assertEqual(self.stay.images.count(), 0)
        second = self.client.post(url, {"image": self.photo("second.jpg", "JPEG"), "sort_order": 1}, format="multipart")
        self.assertEqual(second.status_code, 201, second.data)
        self.assertFalse(second.data["is_cover"])
        changed = self.client.patch(url, {"id": second.data["id"], "is_cover": True, "sort_order": 0}, format="json")
        self.assertEqual(changed.status_code, 200)
        self.assertEqual(self.room.images.filter(is_cover=True).count(), 1)
        detail = self.client.get(f"/api/stays/{self.stay.id}/")
        self.assertEqual(len(detail.data["room_types"][0]["images"]), 2)
        self.assertTrue(detail.data["room_types"][0]["images"][0]["image"].startswith("http://testserver/"))
        self.assertEqual(self.client.delete(url + f"?id={second.data['id']}").status_code, 204)
        image.refresh_from_db()
        self.assertTrue(image.is_cover)
        self.assertEqual(len(self.client.get(f"/api/stays/{self.stay.id}/").data["room_types"][0]["images"]), 1)

    def test_upload_denies_other_users_and_invalid_images_leave_room_intact(self):
        from django.core.files.uploadedfile import SimpleUploadedFile

        url = f"/api/rooms/{self.room.id}/images/"
        self.client.force_authenticate(self.other)
        self.assertEqual(self.client.post(url, {"image": self.photo()}, format="multipart").status_code, 403)
        self.client.force_authenticate(self.owner)
        self.assertEqual(self.client.post(url, {"image": self.photo()}, format="multipart").status_code, 201)
        for photo in [
            SimpleUploadedFile("fake.jpg", b"not an image", content_type="image/jpeg"),
            self.photo("animated.gif", "GIF"),
        ]:
            self.assertEqual(self.client.post(url, {"image": photo}, format="multipart").status_code, 400)
        self.assertTrue(RoomType.objects.filter(pk=self.room.pk).exists())
        self.assertEqual(self.room.images.count(), 1)

    def test_image_cannot_be_deleted_through_another_room(self):
        image = RoomTypeImage.objects.create(room_type=self.room, image="test.jpg")
        other_room = RoomType.objects.create(stay=self.stay, name="Other", base_price=20)
        self.assertEqual(self.client.delete(f"/api/rooms/{other_room.id}/images/?id={image.id}").status_code, 404)
        self.assertTrue(RoomTypeImage.objects.filter(pk=image.id).exists())

    def test_submit_valid_persisted_room_is_pending_and_retry_is_idempotent(self):
        url = f"/api/stays/{self.stay.id}/submit/"
        response = self.client.post(url)
        self.assertEqual(response.status_code, 200, response.data)
        self.assertEqual(response.data["status"], StayStatus.SUBMITTED)
        self.assertEqual(len(response.data["room_types"]), 1)
        self.assertIsNotNone(response.data["submitted_at"])
        again = self.client.post(url)
        self.assertEqual(again.status_code, 200)
        self.assertEqual(again.data["submitted_at"], response.data["submitted_at"])
        mine = self.client.get("/api/stays/mine/")
        self.assertEqual(mine.data["results"][0]["status"], StayStatus.SUBMITTED)

    def test_structured_missing_and_invalid_room_errors(self):
        self.room.is_active = False
        self.room.save()
        url = f"/api/stays/{self.stay.id}/submit/"
        self.assertEqual(self.client.post(url).data["code"], "room_type_required")
        self.room.is_active = True
        self.room.total_capacity = 1
        self.room.save()
        response = self.client.post(url)
        self.assertEqual(response.status_code, 400)
        self.assertEqual(response.data["code"], "room_type_invalid")
        self.stay.refresh_from_db()
        self.assertEqual(self.stay.status, StayStatus.DRAFT)

    def test_write_response_omits_rooms_but_detail_preserves_them(self):
        url = f"/api/stays/{self.stay.id}/"
        saved = self.client.patch(url, {"description": "Edited description"}, format="json")
        self.assertEqual(saved.status_code, 200)
        self.assertNotIn("room_types", saved.data)
        self.assertEqual(len(self.client.get(url).data["room_types"]), 1)


@override_settings(PASSWORD_HASHERS=["django.contrib.auth.hashers.MD5PasswordHasher"])
class RoomReferenceTests(APITestCase):
    def test_public_reference_choices_match_backend_source_and_serializer(self):
        from django.core.cache import cache
        from .serializers import RoomWriteSerializer

        cache.clear()
        response = self.client.get("/api/v1/reference/")
        self.assertEqual(response.status_code, 200)
        for field, enum in [("bed_configurations", BedConfiguration), ("bathroom_types", BathroomType)]:
            self.assertEqual(
                response.json()[field], [{"value": value, "label": label} for value, label in enum.choices]
            )
        serializer = RoomWriteSerializer()
        for value in BedConfiguration.values:
            self.assertEqual(serializer.validate_bed_configuration(value), value)
        for value in BathroomType.values:
            self.assertEqual(serializer.validate_bathroom_type(value), value)
        from rest_framework.exceptions import ValidationError as ApiValidationError

        with self.assertRaises(ApiValidationError):
            serializer.validate_bathroom_type("NOT_AN_OPTION")

    def test_saved_legacy_values_remain_editable(self):
        from .serializers import RoomWriteSerializer

        room = RoomType(bed_configuration="King plus sofa", bathroom_type="Outdoor shower")
        serializer = RoomWriteSerializer(instance=room)
        self.assertEqual(serializer.validate_bed_configuration("King plus sofa"), "King plus sofa")
        self.assertEqual(serializer.validate_bathroom_type("Outdoor shower"), "Outdoor shower")
