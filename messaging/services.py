from django.db import transaction
from properties.models import ListingStatus
from stays.models import StayStatus
from properties.permissions import can_manage_property
from stays.services import can_manage as can_manage_stay
from .models import *


def can_access(user, c):
    return user.is_authenticated and (
        c.participants.filter(user=user, is_active=True).exists()
        or (c.property_id and can_manage_property(user, c.property))
        or (c.stay_id and can_manage_stay(user, c.stay))
    )


@transaction.atomic
def create_conversation(user, body, property=None, stay=None, message_type=MessageType.ENQUIRY):
    if bool(property) == bool(stay):
        raise ValueError("Exactly one target is required")
    if property and property.status != ListingStatus.PUBLISHED or stay and stay.status != StayStatus.PUBLISHED:
        raise ValueError("Listing is not public")
    lookup = {
        "created_by": user,
        "property": property,
        "stay": stay,
        "status__in": [ConversationStatus.OPEN, ConversationStatus.ACTIVE],
    }
    c = Conversation.objects.filter(**lookup).first()
    if not c:
        c = Conversation.objects.create(
            created_by=user, property=property, stay=stay, assigned_agent=(property or stay).agent
        )
        ConversationParticipant.objects.create(conversation=c, user=user, participant_type=ParticipantType.SEEKER)
        manager = (property or stay).agent.user if (property or stay).agent_id else (property or stay).owner
        ConversationParticipant.objects.get_or_create(
            conversation=c,
            user=manager,
            defaults={
                "participant_type": ParticipantType.AGENT if (property or stay).agent_id else ParticipantType.OWNER
            },
        )
    m = Message.objects.create(conversation=c, sender=user, message_type=message_type, body=body)
    c.last_message_at = m.created_at
    c.status = ConversationStatus.ACTIVE
    c.save()
    return c


def system_message(c, body, kind=MessageType.VIEWING_UPDATE):
    m = Message.objects.create(conversation=c, message_type=kind, body=body)
    c.last_message_at = m.created_at
    c.save(update_fields=["last_message_at", "updated_at"])
    return m


def notify_message(message):
    from notifications.models import NotificationType
    from notifications.services import create_notification

    for participant in message.conversation.participants.exclude(user=message.sender).filter(is_active=True):
        create_notification(
            participant.user,
            NotificationType.NEW_MESSAGE,
            "New SurePlace message",
            message.body[:160],
            {"route": f"/account/messages/{message.conversation_id}", "conversation_id": str(message.conversation_id)},
            f"message:{message.id}:{participant.user_id}",
        )
