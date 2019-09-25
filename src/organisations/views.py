# -*- coding: utf-8 -*-
from __future__ import unicode_literals

import logging
from datetime import datetime

from drf_yasg.utils import swagger_auto_schema
from rest_framework import viewsets, status
from rest_framework.authentication import BasicAuthentication
from rest_framework.decorators import action, api_view, authentication_classes
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response

from analytics.query import get_events_for_organisation
from organisations.models import OrganisationRole, Subscription
from organisations.permissions import OrganisationPermission, NestedOrganisationEntityPermission
from organisations.serializers import OrganisationSerializerFull, MultiInvitesSerializer, UpdateSubscriptionSerializer
from projects.serializers import ProjectSerializer
from users.models import Invite, FFAdminUser
from users.serializers import InviteListSerializer, UserIdSerializer

logger = logging.getLogger(__name__)


class OrganisationViewSet(viewsets.ModelViewSet):
    permission_classes = (IsAuthenticated, OrganisationPermission)

    def get_serializer_class(self):
        if self.action == 'remove_users':
            return UserIdSerializer
        elif self.action == 'invite':
            return MultiInvitesSerializer
        elif self.action == 'update_subscription':
            return UpdateSubscriptionSerializer
        return OrganisationSerializerFull

    def get_serializer_context(self):
        context = super(OrganisationViewSet, self).get_serializer_context()
        if self.action in ('remove_users', 'invite', 'update_subscription'):
            context['organisation'] = self.kwargs.get('pk')
        return context

    def get_queryset(self):
        return self.request.user.organisations.all()

    def create(self, request, **kwargs):
        """
        Override create method to add new organisation to authenticated user
        """
        user = request.user
        serializer = OrganisationSerializerFull(data=request.data)
        if serializer.is_valid():
            org = serializer.save()
            user.add_organisation(org, OrganisationRole.ADMIN)

            return Response(serializer.data, status.HTTP_201_CREATED)
        else:
            return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)

    @action(detail=True)
    def projects(self, request, pk):
        organisation = self.get_object()
        projects = organisation.projects.all()
        return Response(ProjectSerializer(projects, many=True).data)

    @action(detail=True, methods=["POST"])
    def invite(self, request, pk):
        serializer = self.get_serializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        serializer.save()
        return Response(status=status.HTTP_201_CREATED)

    @action(detail=True, methods=['POST'], url_path='remove-users')
    def remove_users(self, request, pk):
        """
        Takes a list of users and removes them from the organisation provided in the url
        """
        serializer = self.get_serializer(data=request.data, many=True)
        serializer.is_valid(raise_exception=True)
        serializer.save()
        return Response(serializer.data, status=200)

    @action(detail=True, methods=["GET"])
    def usage(self, request, pk):
        organisation = self.get_object()

        try:
            events = get_events_for_organisation(organisation)
        except (TypeError, ValueError):
            # TypeError can be thrown when getting service account if not configured
            # ValueError can be thrown if GA returns a value that cannot be converted to integer
            return Response({"error": "Couldn't get number of events for organisation."},
                            status=status.HTTP_500_INTERNAL_SERVER_ERROR)

        return Response({"events": events}, status=status.HTTP_200_OK)

    @action(detail=True, methods=['POST'], url_path='update-subscription')
    @swagger_auto_schema(responses={200: OrganisationSerializerFull})
    def update_subscription(self, request, pk):
        serializer = self.get_serializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        serializer.save()
        return Response(OrganisationSerializerFull(instance=self.get_object()).data, status=status.HTTP_200_OK)


class InviteViewSet(viewsets.ModelViewSet):
    serializer_class = InviteListSerializer
    permission_classes = (IsAuthenticated, NestedOrganisationEntityPermission)

    def get_queryset(self):
        organisation_pk = self.kwargs.get('organisation_pk')
        if int(organisation_pk) not in [org.id for org in self.request.user.organisations.all()]:
            return []
        return Invite.objects.filter(organisation__id=organisation_pk)

    @action(detail=True, methods=["POST"])
    def resend(self, request, organisation_pk, pk):
        invite = self.get_object()
        invite.send_invite_mail()
        return Response(status=status.HTTP_200_OK)


@api_view(['POST'])
@authentication_classes([BasicAuthentication])
def chargebee_webhook(request):
    """
    Endpoint to handle webhooks from chargebee.

     - If subscription is active, check to see if plan has changed and update if so. Always update cancellation date to
       None to ensure that if a subscription is reactivated, it is updated on our end.

     - If subscription is cancelled or not renewing, update subscription on our end to include cancellation date and
       send alert to admin users.
    """

    if request.data.get('content') and 'subscription' in request.data.get('content'):
        subscription_data = request.data['content']['subscription']

        try:
            existing_subscription = Subscription.objects.get(subscription_id=subscription_data.get('id'))
        except (Subscription.DoesNotExist, Subscription.MultipleObjectsReturned):
            error_message = 'Couldn\'t get unique subscription for ChargeBee id %s' % subscription_data.get('id')
            logger.error(error_message)
            return Response(data=error_message, status=status.HTTP_400_BAD_REQUEST)

        subscription_status = subscription_data.get('status')
        if subscription_status == 'active':
            if subscription_data.get('plan_id') != existing_subscription.plan:
                existing_subscription.update_plan(subscription_data.get('plan_id'))
        elif subscription_status in ('non_renewing', 'cancelled'):
            existing_subscription.cancel(datetime.fromtimestamp(subscription_data.get('current_term_end')))

    return Response(status=status.HTTP_200_OK)
