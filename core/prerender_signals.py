"""Signal hooks for changes that affect public SurePlace prerendered pages.

Register in CoreConfig.ready(). All callbacks run after database commit,
and the GitHub dispatch is optional when credentials are not configured.
"""
from django.db.models.signals import m2m_changed, post_delete, post_save, pre_save
from django.dispatch import receiver

from agencies.models import Agency, AgentProfile
from properties.models import ListingStatus, PropertyImage, PropertyListing
from stays.models import RoomType, Stay, StayImage, StayStatus

from .prerender import request_prerender_refresh


@receiver(pre_save, sender=PropertyListing, dispatch_uid="prerender_property_before")
@receiver(pre_save, sender=Stay, dispatch_uid="prerender_stay_before")
def remember_publication(sender, instance, **kwargs):
    if not instance.pk:
        instance._prerender_was_public = False
        return
    instance._prerender_was_public = sender.objects.filter(
        pk=instance.pk, status="PUBLISHED"
    ).exists()


@receiver(post_save, sender=PropertyListing, dispatch_uid="prerender_property_save")
@receiver(post_save, sender=Stay, dispatch_uid="prerender_stay_save")
def listing_changed(sender, instance, **kwargs):
    if instance.status == "PUBLISHED" or getattr(instance, "_prerender_was_public", False):
        request_prerender_refresh()


@receiver(post_delete, sender=PropertyListing, dispatch_uid="prerender_property_delete")
@receiver(post_delete, sender=Stay, dispatch_uid="prerender_stay_delete")
def listing_deleted(sender, instance, **kwargs):
    if instance.status == "PUBLISHED":
        request_prerender_refresh()


@receiver(post_save, sender=PropertyImage, dispatch_uid="prerender_property_image_save")
@receiver(post_delete, sender=PropertyImage, dispatch_uid="prerender_property_image_delete")
def property_image_changed(sender, instance, **kwargs):
    if PropertyListing.objects.filter(pk=instance.property_id, status=ListingStatus.PUBLISHED).exists():
        request_prerender_refresh()


@receiver(post_save, sender=StayImage, dispatch_uid="prerender_stay_image_save")
@receiver(post_delete, sender=StayImage, dispatch_uid="prerender_stay_image_delete")
def stay_image_changed(sender, instance, **kwargs):
    if Stay.objects.filter(pk=instance.stay_id, status=StayStatus.PUBLISHED).exists():
        request_prerender_refresh()


@receiver(post_save, sender=RoomType, dispatch_uid="prerender_room_save")
@receiver(post_delete, sender=RoomType, dispatch_uid="prerender_room_delete")
def room_changed(sender, instance, **kwargs):
    if Stay.objects.filter(pk=instance.stay_id, status=StayStatus.PUBLISHED).exists():
        request_prerender_refresh()


@receiver(m2m_changed, sender=PropertyListing.amenities.through, dispatch_uid="prerender_property_amenities")
@receiver(m2m_changed, sender=Stay.amenities.through, dispatch_uid="prerender_stay_amenities")
def listing_amenities_changed(sender, instance, action, reverse, pk_set, **kwargs):
    if action not in {"post_add", "post_remove", "post_clear"}:
        return
    if not reverse:
        if instance.status == "PUBLISHED":
            request_prerender_refresh()
    else:
        # A change from the amenity side may affect multiple public listings.
        model = PropertyListing if sender is PropertyListing.amenities.through else Stay
        if model.objects.filter(amenities=instance, status="PUBLISHED").exists():
            request_prerender_refresh()


@receiver(post_save, sender=Agency, dispatch_uid="prerender_agency_save")
@receiver(post_delete, sender=Agency, dispatch_uid="prerender_agency_delete")
@receiver(post_save, sender=AgentProfile, dispatch_uid="prerender_agent_save")
@receiver(post_delete, sender=AgentProfile, dispatch_uid="prerender_agent_delete")
def professional_changed(sender, instance, **kwargs):
    # Public search/profile pages depend on these records and their active state.
    request_prerender_refresh()
