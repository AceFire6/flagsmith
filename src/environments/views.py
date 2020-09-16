# -*- coding: utf-8 -*-
from __future__ import unicode_literals

import coreapi
from django.db.models import Q
from django.utils.decorators import method_decorator
from drf_yasg import openapi
from drf_yasg.utils import swagger_auto_schema
from rest_framework import viewsets, status, mixins
from rest_framework.decorators import action
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework.schemas import AutoSchema

from environments.authentication import EnvironmentKeyAuthentication
from environments.permissions.permissions import EnvironmentKeyPermissions, EnvironmentPermissions, \
    NestedEnvironmentPermissions, TraitPersistencePermissions
from permissions.serializers import PermissionModelSerializer, MyUserObjectPermissionsSerializer
from util.logging import get_logger
from util.views import SDKAPIView
from .models import Environment, Trait, Webhook
from .identities.models import Identity
from .permissions.models import EnvironmentPermissionModel, UserEnvironmentPermission, \
    UserPermissionGroupEnvironmentPermission
from .serializers import EnvironmentSerializerLight, WebhookSerializer
from .identities.traits.serializers import TraitSerializerFull, TraitSerializerBasic, \
    IncrementTraitValueSerializer, TraitKeysSerializer, DeleteAllTraitKeysSerializer
from .sdk.serializers import SDKCreateUpdateTraitSerializer, \
    SDKBulkCreateUpdateTraitSerializer

logger = get_logger(__name__)


@method_decorator(name='list', decorator=swagger_auto_schema(manual_parameters=[
    openapi.Parameter('project', openapi.IN_QUERY,
                      'ID of the project to filter by.', required=False, type=openapi.TYPE_INTEGER)
]))
class EnvironmentViewSet(viewsets.ModelViewSet):
    lookup_field = 'api_key'
    permission_classes = [IsAuthenticated, EnvironmentPermissions]

    def get_serializer_class(self):
        if self.action == 'trait_keys':
            return TraitKeysSerializer
        if self.action == 'delete_traits':
            return DeleteAllTraitKeysSerializer
        return EnvironmentSerializerLight

    def get_serializer_context(self):
        context = super(EnvironmentViewSet, self).get_serializer_context()
        if self.kwargs.get('api_key'):
            context['environment'] = self.get_object()
        return context

    def get_queryset(self):
        queryset = self.request.user.get_permitted_environments(['VIEW_ENVIRONMENT'])

        project_id = self.request.query_params.get('project')
        if project_id:
            queryset = queryset.filter(project__id=project_id)

        return queryset

    def perform_create(self, serializer):
        environment = serializer.save()
        UserEnvironmentPermission.objects.create(user=self.request.user, environment=environment, admin=True)

    @action(detail=True, methods=['GET'], url_path='trait-keys')
    def trait_keys(self, request, *args, **kwargs):
        keys = [trait_key for trait_key in Trait.objects.filter(
            identity__environment=self.get_object()).order_by().values_list('trait_key', flat=True).distinct()]

        data = {
            'keys': keys
        }

        serializer = self.get_serializer(data=data)
        if serializer.is_valid():
            return Response(serializer.data, status=status.HTTP_200_OK)
        else:
            return Response({'detail': 'Couldn\'t get trait keys'}, status=status.HTTP_500_INTERNAL_SERVER_ERROR)

    @action(detail=True, methods=['POST'], url_path='delete-traits')
    def delete_traits(self, request, *args, **kwargs):
        serializer = self.get_serializer(data=request.data)
        if serializer.is_valid():
            serializer.delete()
            return Response(status=status.HTTP_200_OK)
        else:
            return Response({'detail': 'Couldn\'t delete trait keys.'}, status=status.HTTP_400_BAD_REQUEST)

    @swagger_auto_schema(responses={200: PermissionModelSerializer})
    @action(detail=False, methods=["GET"])
    def permissions(self, *args, **kwargs):
        return Response(PermissionModelSerializer(instance=EnvironmentPermissionModel.objects.all(), many=True).data)

    @swagger_auto_schema(responses={200: MyUserObjectPermissionsSerializer})
    @action(detail=True, methods=["GET"], url_path="my-permissions", url_name="my-permissions")
    def user_permissions(self, request, *args, **kwargs):
        # TODO: tidy this mess up
        environment = self.get_object()

        group_permissions = UserPermissionGroupEnvironmentPermission.objects.filter(group__users=request.user,
                                                                                    environment=environment)
        user_permissions = UserEnvironmentPermission.objects.filter(user=request.user, environment=environment)

        permissions = set()
        for group_permission in group_permissions:
            permissions = permissions.union(
                {permission.key for permission in group_permission.permissions.all() if permission.key})
        for user_permission in user_permissions:
            permissions = permissions.union(
                {permission.key for permission in user_permission.permissions.all() if permission.key})

        is_project_admin = request.user.is_project_admin(environment.project)

        data = {
            'admin': group_permissions.filter(admin=True).exists() or user_permissions.filter(
                admin=True).exists() or is_project_admin,
            'permissions': permissions
        }

        serializer = MyUserObjectPermissionsSerializer(data=data)
        serializer.is_valid()

        return Response(serializer.data)


class TraitViewSet(viewsets.ModelViewSet):
    serializer_class = TraitSerializerFull

    def get_queryset(self):
        """
        Override queryset to filter based on provided URL parameters.
        """
        environment_api_key = self.kwargs['environment_api_key']
        identity_pk = self.kwargs.get('identity_pk')
        environment = self.request.user.get_permitted_environments(['VIEW_ENVIRONMENT']).get(
            api_key=environment_api_key)

        if identity_pk:
            identity = Identity.objects.get(pk=identity_pk, environment=environment)
        else:
            identity = None

        return Trait.objects.filter(identity=identity)

    def get_environment_from_request(self):
        """
        Get environment object from URL parameters in request.
        """
        return Environment.objects.get(api_key=self.kwargs['environment_api_key'])

    def get_identity_from_request(self, environment):
        """
        Get identity object from URL parameters in request.
        """
        return Identity.objects.get(pk=self.kwargs['identity_pk'])

    def create(self, request, *args, **kwargs):
        """
        Override create method to add identity (if present) from URL parameters.

        TODO: fix this - it doesn't work, the FE uses the SDK endpoint instead
        """
        data = request.data
        environment = self.get_environment_from_request()
        if environment.project.organisation not in self.request.user.organisations.all():
            return Response(status=status.HTTP_403_FORBIDDEN)

        identity_pk = self.kwargs.get('identity_pk')

        # check if identity in data or in request
        if 'identity' not in data and not identity_pk:
            error = {"detail": "Identity not provided"}
            return Response(error, status=status.HTTP_400_BAD_REQUEST)

        # TODO: do we give priority to request identity or data?
        # Override with request identity
        if identity_pk:
            data['identity'] = identity_pk

        serializer = self.get_serializer(data=data)
        serializer.is_valid(raise_exception=True)
        self.perform_create(serializer)
        headers = self.get_success_headers(serializer.data)

        return Response(serializer.data, status=status.HTTP_201_CREATED, headers=headers)

    def update(self, request, *args, **kwargs):
        """
        Override update method to always assume update request is partial and create / update
        trait value.
        """
        trait_to_update = self.get_object()
        trait_data = request.data

        # Check if trait value was provided with request data. If so, we need to figure out value_type from
        # the given value and also use correct value field e.g. boolean_value, float_value, integer_value or
        # string_value, and override request data
        if 'trait_value' in trait_data:
            trait_data = trait_to_update.generate_trait_value_data(trait_data['trait_value'])

        serializer = TraitSerializerFull(trait_to_update, data=trait_data, partial=True)

        serializer.is_valid(raise_exception=True)
        self.perform_update(serializer)

        return Response(serializer.data)

    def partial_update(self, request, *args, **kwargs):
        """
        Override partial_update as overridden update method assumes partial True for all requests.
        """
        return self.update(request, *args, **kwargs)

    @swagger_auto_schema(manual_parameters=[
        openapi.Parameter('deleteAllMatchingTraits', openapi.IN_QUERY,
                          'Deletes all traits in this environment matching the key of the deleted trait',
                          type=openapi.TYPE_BOOLEAN)
    ])
    def destroy(self, request, *args, **kwargs):
        delete_all_traits = request.query_params.get('deleteAllMatchingTraits')
        if delete_all_traits and delete_all_traits in ('true', 'True'):
            trait = self.get_object()
            self._delete_all_traits_matching_key(trait.trait_key, trait.identity.environment)
            return Response(status=status.HTTP_204_NO_CONTENT)
        else:
            return super(TraitViewSet, self).destroy(request, *args, **kwargs)

    def _delete_all_traits_matching_key(self, trait_key, environment):
        Trait.objects.filter(trait_key=trait_key, identity__environment=environment).delete()


class WebhookViewSet(mixins.ListModelMixin, mixins.CreateModelMixin, mixins.UpdateModelMixin, mixins.DestroyModelMixin,
                     viewsets.GenericViewSet):
    serializer_class = WebhookSerializer
    pagination_class = None
    permission_classes = [IsAuthenticated, NestedEnvironmentPermissions]

    def get_queryset(self):
        return Webhook.objects.filter(environment__api_key=self.kwargs.get('environment_api_key'))

    def perform_create(self, serializer):
        environment = Environment.objects.get(api_key=self.kwargs.get('environment_api_key'))
        serializer.save(environment=environment)

    def perform_update(self, serializer):
        environment = Environment.objects.get(api_key=self.kwargs.get('environment_api_key'))
        serializer.save(environment=environment)


class SDKTraitsDeprecated(SDKAPIView):
    # API to handle /api/v1/identities/<identifier>/traits/<trait_key> endpoints
    # if Identity or Trait does not exist it will create one, otherwise will fetch existing
    serializer_class = TraitSerializerBasic

    schema = AutoSchema(
        manual_fields=[
            coreapi.Field("X-Environment-Key", location="header",
                          description="API Key for an Environment"),
            coreapi.Field("identifier", location="path", required=True,
                          description="Identity user identifier"),
            coreapi.Field("trait_key", location="path", required=True,
                          description="User trait unique key")
        ]
    )

    def post(self, request, identifier, trait_key, *args, **kwargs):
        """
        THIS ENDPOINT IS DEPRECATED. Please use `/traits/` instead.
        """
        trait_data = request.data

        if 'trait_value' not in trait_data:
            error = {"detail": "Trait value not provided"}
            return Response(error, status=status.HTTP_400_BAD_REQUEST)

        # if we have identifier fetch, or create if does not exist
        if identifier:
            identity, _ = Identity.objects.get_or_create(
                identifier=identifier,
                environment=request.environment,
            )

        else:
            return Response(
                {"detail": "Missing identifier"},
                status=status.HTTP_400_BAD_REQUEST
            )

        # if we have identity trait fetch, or create if does not exist
        if trait_key:
            # need to create one if does not exist
            trait, _ = Trait.objects.get_or_create(
                identity=identity,
                trait_key=trait_key,
            )

        else:
            return Response(
                {"detail": "Missing trait key"},
                status=status.HTTP_400_BAD_REQUEST
            )

        if trait and 'trait_value' in trait_data:
            # Check if trait value was provided with request data. If so, we need to figure out value_type from
            # the given value and also use correct value field e.g. boolean_value, float_value, integer_value or
            # string_value, and override request data
            trait_data = trait.generate_trait_value_data(trait_data['trait_value'])

            trait_full_serializer = TraitSerializerFull(trait, data=trait_data, partial=True)

            if trait_full_serializer.is_valid():
                trait_full_serializer.save()
                return Response(self.get_serializer(trait).data, status=status.HTTP_200_OK)
            else:
                return Response(trait_full_serializer.errors, status=status.HTTP_400_BAD_REQUEST)

        else:
            return Response({"detail": "Failed to update user trait"}, status=status.HTTP_400_BAD_REQUEST)


class SDKTraits(mixins.CreateModelMixin, viewsets.GenericViewSet):
    permission_classes = (EnvironmentKeyPermissions, TraitPersistencePermissions)
    authentication_classes = (EnvironmentKeyAuthentication,)

    def get_serializer_class(self):
        if self.action == 'increment_value':
            return IncrementTraitValueSerializer
        if self.action == 'bulk_create':
            return SDKBulkCreateUpdateTraitSerializer

        return SDKCreateUpdateTraitSerializer

    def get_serializer_context(self):
        context = super(SDKTraits, self).get_serializer_context()
        context['environment'] = self.request.environment
        return context

    @swagger_auto_schema(request_body=SDKCreateUpdateTraitSerializer)
    def create(self, request, *args, **kwargs):
        response = super(SDKTraits, self).create(request, *args, **kwargs)
        response.status_code = status.HTTP_200_OK
        return response

    @swagger_auto_schema(responses={200: IncrementTraitValueSerializer}, request_body=IncrementTraitValueSerializer)
    @action(detail=False, methods=["POST"], url_path='increment-value')
    def increment_value(self, request):
        serializer = self.get_serializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        serializer.save()
        return Response(serializer.data, status=200)

    @swagger_auto_schema(request_body=SDKCreateUpdateTraitSerializer(many=True))
    @action(detail=False, methods=["PUT"], url_path='bulk')
    def bulk_create(self, request):
        try:
            # endpoint allows users to delete existing traits by sending null values
            # for the trait value so we need to filter those out here
            traits = []
            delete_filter_query = Q()

            for idx, trait in enumerate(request.data):
                if trait.get('trait_value') is None:
                    delete_filter_query = delete_filter_query | Q(
                        trait_key=trait.get('trait_key'),
                        identity__identifier=trait['identity']['identifier'],
                        identity__environment=request.environment
                    )
                else:
                    traits.append(trait)

            if delete_filter_query:
                Trait.objects.filter(delete_filter_query).delete()

            serializer = self.get_serializer(data=traits, many=True)
            serializer.is_valid(raise_exception=True)
            serializer.save()
            return Response(serializer.data, status=200)

        except (TypeError, AttributeError) as excinfo:
            logger.error('Invalid request data: %s' % str(excinfo))
            return Response({'detail': 'Invalid request data'}, status=status.HTTP_400_BAD_REQUEST)
