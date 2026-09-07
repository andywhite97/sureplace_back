from datetime import date, timedelta

from rest_framework.test import APITestCase

from accounts.models import User
from bookings.models import ViewingRequest, ViewingStatus
from properties.models import AvailabilityStatus, ListingStatus, PropertyListing
from stays.models import Stay, StayStatus, StayType
from .models import Conversation, GuestEnquiry, Message, MessageType


class MessagingAndViewingTests(APITestCase):
    def setUp(self):
        self.owner = User.objects.create_user(
            email="msgowner@example.com", password="StrongPass123!", first_name="Owner", last_name="One"
        )
        self.seeker = User.objects.create_user(
            email="seeker@example.com", password="StrongPass123!", first_name="Seek", last_name="Er"
        )
        self.other = User.objects.create_user(
            email="stranger@example.com", password="StrongPass123!", first_name="Strange", last_name="R"
        )
        self.property = PropertyListing.objects.create(
            owner=self.owner,
            title="Message Home",
            description="Public home",
            listing_type="RENT",
            property_type="HOUSE",
            price=5000,
            region="Hhohho",
            town="Mbabane",
            location={"latitude": -26.3, "longitude": 31.1},
            status=ListingStatus.PUBLISHED,
            availability_status=AvailabilityStatus.AVAILABLE,
        )
        self.stay = Stay.objects.create(
            owner=self.owner,
            name="Message Lodge",
            description="Public lodge",
            stay_type=StayType.LODGE,
            region="Hhohho",
            town="Mbabane",
            location={"latitude": -26.3, "longitude": 31.1},
            status=StayStatus.PUBLISHED,
        )

    def create_conversation(self, target="property"):
        self.client.force_authenticate(self.seeker)
        payload = {target: str(getattr(self, target).id), "message": "Is this available?"}
        response = self.client.post("/api/conversations/", payload, format="json")
        self.assertEqual(response.status_code, 201, response.data)
        return Conversation.objects.get(id=response.data["id"])

    def test_authentication_reuse_property_and_stay_conversations(self):
        self.assertEqual(self.client.post("/api/conversations/", {}).status_code, 401)
        conversation = self.create_conversation()
        second = self.client.post(
            "/api/conversations/", {"property": str(self.property.id), "message": "Follow up"}, format="json"
        )
        self.assertEqual(str(conversation.id), second.data["id"])
        self.assertEqual(conversation.participants.count(), 2)
        stay_conversation = self.create_conversation("stay")
        self.assertEqual(stay_conversation.stay, self.stay)

    def test_participant_and_manager_access_but_stranger_denied(self):
        conversation = self.create_conversation()
        self.client.force_authenticate(self.owner)
        self.assertEqual(self.client.get(f"/api/conversations/{conversation.id}/").status_code, 200)
        self.client.force_authenticate(self.other)
        self.assertEqual(self.client.get(f"/api/conversations/{conversation.id}/").status_code, 404)

    def test_message_sender_spoofing_system_protection_read_and_soft_delete(self):
        conversation = self.create_conversation()
        response = self.client.post(
            f"/api/conversations/{conversation.id}/messages/",
            {"body": "Hello", "sender": str(self.other.id)},
            format="json",
        )
        self.assertEqual(response.status_code, 201)
        message = Message.objects.get(id=response.data["id"])
        self.assertEqual(message.sender, self.seeker)
        self.assertEqual(
            self.client.post(
                f"/api/conversations/{conversation.id}/messages/",
                {"body": "fake", "message_type": "SYSTEM"},
                format="json",
            ).status_code,
            400,
        )
        self.assertEqual(self.client.post(f"/api/conversations/{conversation.id}/mark-read/").data["unread_count"], 0)
        self.assertEqual(self.client.delete(f"/api/messages/{message.id}/remove/").status_code, 204)
        message.refresh_from_db()
        self.assertIsNotNone(message.deleted_at)

    def test_inbox_exposes_safe_context_participants_and_real_unread_count(self):
        conversation = self.create_conversation()
        self.client.force_authenticate(self.owner)
        Message.objects.create(conversation=conversation, sender=self.seeker, body="A newer unread message")
        response = self.client.get("/api/conversations/")
        self.assertEqual(response.status_code, 200)
        row = response.data["results"][0]
        self.assertEqual(row["context"]["title"], "Message Home")
        self.assertEqual(row["context"]["type"], "PROPERTY")
        self.assertGreaterEqual(row["unread_count"], 1)
        self.assertTrue(any(p["display_name"] == "Seek Er" for p in row["participants"]))
        self.assertNotIn("email", row["participants"][0])
        self.client.post(f"/api/conversations/{conversation.id}/mark-read/")
        refreshed = self.client.get("/api/conversations/").data["results"][0]
        self.assertEqual(refreshed["unread_count"], 0)

    def test_guest_enquiries_validate_target_and_contact(self):
        self.client.force_authenticate(None)
        good = self.client.post(
            "/api/enquiries/guest/",
            {"property": str(self.property.id), "name": "Guest", "email": "guest@example.com", "message": "Call me"},
            format="json",
        )
        self.assertEqual(good.status_code, 201, good.data)
        self.assertEqual(GuestEnquiry.objects.count(), 1)
        bad = self.client.post("/api/enquiries/guest/", {"name": "Guest", "message": "No contact"}, format="json")
        self.assertEqual(bad.status_code, 400)

    def test_viewing_creation_conversation_and_workflows(self):
        tomorrow = date.today() + timedelta(days=1)
        self.client.force_authenticate(self.seeker)
        response = self.client.post(
            f"/api/properties/{self.property.id}/viewing-requests/",
            {"requested_date": str(tomorrow), "requested_time": "10:00", "notes": "Morning"},
            format="json",
        )
        self.assertEqual(response.status_code, 201, response.data)
        viewing = ViewingRequest.objects.get(id=response.data["id"])
        self.assertIsNotNone(viewing.conversation)
        self.assertTrue(viewing.conversation.messages.filter(message_type=MessageType.VIEWING_REQUEST).exists())
        self.client.force_authenticate(self.owner)
        confirmed = self.client.post(f"/api/viewing-requests/{viewing.id}/confirm/")
        self.assertEqual(confirmed.status_code, 200)
        viewing.refresh_from_db()
        self.assertEqual(viewing.status, ViewingStatus.CONFIRMED)
        self.assertIsNotNone(viewing.confirmed_at)

    def test_own_property_past_date_duplicate_and_unauthorized_workflow(self):
        tomorrow = date.today() + timedelta(days=1)
        payload = {"requested_date": str(tomorrow), "requested_time": "10:00"}
        self.client.force_authenticate(self.owner)
        self.assertEqual(
            self.client.post(
                f"/api/properties/{self.property.id}/viewing-requests/", payload, format="json"
            ).status_code,
            400,
        )
        self.client.force_authenticate(self.seeker)
        self.assertEqual(
            self.client.post(
                f"/api/properties/{self.property.id}/viewing-requests/",
                {"requested_date": str(date.today() - timedelta(days=1)), "requested_time": "10:00"},
                format="json",
            ).status_code,
            400,
        )
        first = self.client.post(f"/api/properties/{self.property.id}/viewing-requests/", payload, format="json")
        self.assertEqual(first.status_code, 201)
        self.assertEqual(
            self.client.post(
                f"/api/properties/{self.property.id}/viewing-requests/", payload, format="json"
            ).status_code,
            400,
        )
        self.client.force_authenticate(self.other)
        self.assertEqual(self.client.post(f"/api/viewing-requests/{first.data['id']}/confirm/").status_code, 404)
