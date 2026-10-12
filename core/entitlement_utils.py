"""Shared mechanics; property and stay catalogues/capacity rules remain separate."""

from contextlib import contextmanager
from decimal import Decimal
from django.db import models, transaction, connection
from django.db.models import Q


def owner_constraints(prefix):
    return [
        models.CheckConstraint(
            condition=(Q(account__isnull=False, agency__isnull=True) | Q(account__isnull=True, agency__isnull=False)),
            name=f"{prefix}_exactly_one_owner",
        )
    ]


@contextmanager
def lock_owner(account_id=None, agency_id=None):
    from accounts.models import User
    from agencies.models import Agency

    with transaction.atomic():
        model, pk = (Agency, agency_id) if agency_id else (User, account_id)
        # NO KEY UPDATE still serializes quotas, while allowing bookings/messages
        # to insert foreign keys to the host during room-before-stay locking.
        model.objects.select_for_update(no_key=connection.features.has_select_for_no_key_update).get(pk=pk)
        yield


def package_unit_amounts(price, quantity):
    per_unit = (price / quantity).quantize(Decimal("0.01"))
    return [per_unit] * (quantity - 1) + [price - per_unit * (quantity - 1)]
