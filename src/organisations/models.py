# -*- coding: utf-8 -*-
from __future__ import unicode_literals

import enum

from django.db import models
from django.utils.encoding import python_2_unicode_compatible


class OrganisationRole(enum.Enum):
    ADMIN = "Admin"
    USER = "User"


organisation_roles = ((tag.name, tag.value) for tag in OrganisationRole)


@python_2_unicode_compatible
class Organisation(models.Model):
    name = models.CharField(max_length=2000)
    has_requested_features = models.BooleanField(default=False)
    webhook_notification_email = models.EmailField(null=True, blank=True)
    created_date = models.DateTimeField('DateCreated', auto_now_add=True)
    alerted_over_plan_limit = models.BooleanField(default=False)

    class Meta:
        ordering = ['id']

    def __str__(self):
        return "Org %s" % self.name

    # noinspection PyTypeChecker
    def get_unique_slug(self):
        return str(self.id) + "-" + self.name

    @property
    def num_seats(self):
        return self.users.count()

    def has_subscription(self):
        return hasattr(self, 'subscription')

    def over_plan_seats_limit(self):
        return self.has_subscription() and 0 < self.subscription.max_seats < self.num_seats

    def reset_alert_status(self):
        self.alerted_over_plan_limit = False
        self.save()


class UserOrganisation(models.Model):
    user = models.ForeignKey('users.FFAdminUser', on_delete=models.CASCADE)
    organisation = models.ForeignKey(Organisation, on_delete=models.CASCADE)
    date_joined = models.DateTimeField(auto_now_add=True)
    role = models.CharField(max_length=50, choices=organisation_roles)


class Subscription(models.Model):
    organisation = models.OneToOneField(Organisation, on_delete=models.CASCADE, related_name='subscription')
    subscription_id = models.CharField(max_length=100, blank=True, null=True)
    subscription_date = models.DateField(blank=True, null=True)
    paid_subscription = models.BooleanField(default=False)
    free_to_use_subscription = models.BooleanField(default=True)
    plan = models.CharField(max_length=20, null=True, blank=True)
    pending_cancellation = models.BooleanField(default=False)
    max_seats = models.IntegerField(default=1)
