from django.contrib import admin
from .models import Conversation, ConversationParticipant, Message, GuestEnquiry, ConversationReport

admin.site.register([Conversation, ConversationParticipant, Message, GuestEnquiry, ConversationReport])
