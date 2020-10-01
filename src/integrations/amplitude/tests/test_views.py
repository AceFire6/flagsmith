from unittest.case import TestCase

import pytest
from rest_framework import status
from rest_framework.test import APIClient

from environments.models import Environment
from integrations.amplitude.models import AmplitudeConfiguration
from organisations.models import Organisation, OrganisationRole
from projects.models import Project
from util.tests import Helper


@pytest.mark.django_db
class AmplitudeConfigurationTestCase(TestCase):
    post_put_template = '{ "api_key" : "%s" }'
    amplitude_config_url = "/api/v1/environments/%s/integrations/amplitude/"
    amplitude_config_detail_url = amplitude_config_url + "%d/"

    def setUp(self):
        self.client = APIClient()
        user = Helper.create_ffadminuser()
        self.client.force_authenticate(user=user)

        self.organisation = Organisation.objects.create(name="Test Org")
        user.add_organisation(
            self.organisation, OrganisationRole.ADMIN
        )  # admin to bypass perms

        self.project = Project.objects.create(
            name="Test project", organisation=self.organisation
        )
        self.environment = Environment.objects.create(
            name="Test Environment", project=self.project
        )

    def test_should_create_amplitude_config_when_post(self):
        # Given
        api_key = "abc-123"

        # When
        response = self.client.post(
            self.amplitude_config_url % self.environment.api_key,
            data=self.post_put_template % api_key,
            content_type="application/json",
        )

        # Then
        assert response.status_code == status.HTTP_201_CREATED
        assert AmplitudeConfiguration.objects.filter(environment=self.environment).count() == 1

    def test_should_return_BadRequest_when_duplicate_amplitude_config_is_posted(self):
        # Given
        config = AmplitudeConfiguration.objects.create(api_key="api_123", environment=self.environment)

        # When
        response = self.client.post(
            self.amplitude_config_url % self.environment.api_key,
            data=self.post_put_template % config.api_key,
            content_type="application/json",
        )

        # Then
        assert response.status_code == status.HTTP_400_BAD_REQUEST
        assert AmplitudeConfiguration.objects.filter(environment=self.environment).count() == 1

    #
    def test_should_update_configuration_when_put(self):
        # Given
        config = AmplitudeConfiguration.objects.create(api_key="api_123", environment=self.environment)

        api_key_updated = "new api"

        # When
        response = self.client.put(
            self.amplitude_config_detail_url % (self.environment.api_key, config.id),
            data=self.post_put_template % api_key_updated,
            content_type="application/json",
        )
        config.refresh_from_db()

        # Then
        assert response.status_code == status.HTTP_200_OK
        assert config.api_key == api_key_updated

    def test_should_return_amplitude_config_list_when_requested(self):
        # Given - set up data

        # When
        response = self.client.get(
            self.amplitude_config_url % self.environment.api_key
        )

        # Then
        assert response.status_code == status.HTTP_200_OK

    def test_should_remove_configuration_when_delete(self):
        # Given
        config = AmplitudeConfiguration.objects.create(api_key="api_123", environment=self.environment)

        # When
        res = self.client.delete(
            self.amplitude_config_detail_url % (self.environment.api_key, config.id),
            content_type="application/json",
        )

        # Then
        assert res.status_code == status.HTTP_204_NO_CONTENT
        #  and
        assert not AmplitudeConfiguration.objects.filter(environment=self.environment).exists()
