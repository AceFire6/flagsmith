import json
from unittest import TestCase

import pytest
from django.urls import reverse
from rest_framework import status
from rest_framework.test import APIClient, APITestCase

from audit.models import AuditLog, RelatedObjectType
from environments.models import Environment, Identity, Trait, INTEGER, STRING, Webhook, UserEnvironmentPermission, \
    EnvironmentPermissionModel, UserPermissionGroupEnvironmentPermission
from features.models import Feature, FeatureState, FeatureSegment
from organisations.models import Organisation, OrganisationRole
from projects.models import Project, UserProjectPermission, ProjectPermissionModel
from segments import models
from segments.models import Segment, SegmentRule, Condition
from users.models import FFAdminUser, UserPermissionGroup
from util.tests import Helper


@pytest.mark.django_db
class EnvironmentTestCase(TestCase):
    env_post_template = '{"name": "%s", "project": %d}'
    fs_put_template = '{ "id" : %d, "enabled" : "%r", "feature_state_value" : "%s" }'

    def setUp(self):
        self.client = APIClient()
        self.user = Helper.create_ffadminuser()
        self.client.force_authenticate(user=self.user)

        create_environment_permission = ProjectPermissionModel.objects.get(key="CREATE_ENVIRONMENT")
        read_project_permission = ProjectPermissionModel.objects.get(key="VIEW_PROJECT")

        self.organisation = Organisation.objects.create(name='ssg')
        self.user.add_organisation(self.organisation, OrganisationRole.ADMIN)  # admin to bypass perms

        self.project = Project.objects.create(name='Test project', organisation=self.organisation)

        user_project_permission = UserProjectPermission.objects.create(user=self.user, project=self.project)
        user_project_permission.permissions.add(create_environment_permission, read_project_permission)

    def tearDown(self) -> None:
        Environment.objects.all().delete()
        AuditLog.objects.all().delete()

    def test_should_create_environments(self):
        # Given
        url = reverse('api-v1:environments:environment-list')
        data = {
            'name': 'Test environment',
            'project': self.project.id
        }

        # When
        response = self.client.post(url, data=data)

        # Then
        assert response.status_code == status.HTTP_201_CREATED

        # and user is admin
        assert UserEnvironmentPermission.objects.filter(user=self.user, admin=True,
                                                        environment__id=response.json()['id']).exists()

    def test_should_return_identities_for_an_environment(self):
        # Given
        identifier_one = 'user1'
        identifier_two = 'user2'
        environment = Environment.objects.create(name='environment1', project=self.project)
        Identity.objects.create(identifier=identifier_one, environment=environment)
        Identity.objects.create(identifier=identifier_two, environment=environment)
        url = reverse('api-v1:environments:environment-identities-list', args=[environment.api_key])

        # When
        response = self.client.get(url)

        # Then
        assert response.data['results'][0]['identifier'] == identifier_one
        assert response.data['results'][1]['identifier'] == identifier_two

    def test_should_update_value_of_feature_state(self):
        # Given
        feature = Feature.objects.create(name="feature", project=self.project)
        environment = Environment.objects.create(name="test env", project=self.project)
        feature_state = FeatureState.objects.get(feature=feature, environment=environment)
        url = reverse('api-v1:environments:environment-featurestates-detail',
                      args=[environment.api_key, feature_state.id])

        # When
        response = self.client.put(url, data=self.fs_put_template % (feature_state.id, True, "This is a value"),
                                   content_type='application/json')

        # Then
        feature_state.refresh_from_db()

        assert response.status_code == status.HTTP_200_OK
        assert feature_state.get_feature_state_value() == "This is a value"
        assert feature_state.enabled

    def test_audit_log_entry_created_when_new_environment_created(self):
        # Given
        url = reverse('api-v1:environments:environment-list')
        data = {
            'project': self.project.id,
            'name': 'Test Environment'
        }

        # When
        self.client.post(url, data=data)

        # Then
        assert AuditLog.objects.filter(related_object_type=RelatedObjectType.ENVIRONMENT.name).count() == 1

    def test_audit_log_entry_created_when_environment_updated(self):
        # Given
        environment = Environment.objects.create(name='Test environment', project=self.project)
        url = reverse('api-v1:environments:environment-detail', args=[environment.api_key])
        data = {
            'project': self.project.id,
            'name': 'New name'
        }

        # When
        self.client.put(url, data=data)

        # Then
        assert AuditLog.objects.filter(related_object_type=RelatedObjectType.ENVIRONMENT.name).count() == 1

    def test_audit_log_created_when_feature_state_updated(self):
        # Given
        feature = Feature.objects.create(name="feature", project=self.project)
        environment = Environment.objects.create(name="test env", project=self.project)
        feature_state = FeatureState.objects.get(feature=feature, environment=environment)
        url = reverse('api-v1:environments:environment-featurestates-detail',
                      args=[environment.api_key, feature_state.id])
        data = {
            'id': feature.id,
            'enabled': True
        }

        # When
        self.client.put(url, data=data)

        # Then
        assert AuditLog.objects.filter(related_object_type=RelatedObjectType.FEATURE_STATE.name).count() == 1

        # and
        assert AuditLog.objects.first().author

    def test_get_all_trait_keys_for_environment_only_returns_distinct_keys(self):
        # Given
        trait_key_one = 'trait-key-one'
        trait_key_two = 'trait-key-two'

        environment = Environment.objects.create(project=self.project, name='Test Environment')

        identity_one = Identity.objects.create(environment=environment, identifier='identity-one')
        identity_two = Identity.objects.create(environment=environment, identifier='identity-two')

        Trait.objects.create(identity=identity_one, trait_key=trait_key_one, string_value='blah', value_type=STRING)
        Trait.objects.create(identity=identity_one, trait_key=trait_key_two, string_value='blah', value_type=STRING)
        Trait.objects.create(identity=identity_two, trait_key=trait_key_one, string_value='blah', value_type=STRING)

        url = reverse('api-v1:environments:environment-trait-keys', args=[environment.api_key])

        # When
        res = self.client.get(url)

        # Then
        assert res.status_code == status.HTTP_200_OK

        # and - only distinct keys are returned
        assert len(res.json().get('keys')) == 2

    def test_delete_trait_keys_deletes_trait_for_all_users_in_that_environment(self):
        # Given
        environment_one = Environment.objects.create(project=self.project, name='Test Environment 1')
        environment_two = Environment.objects.create(project=self.project, name='Test Environment 2')

        identity_one_environment_one = Identity.objects.create(environment=environment_one,
                                                               identifier='identity-one-env-one')
        identity_one_environment_two = Identity.objects.create(environment=environment_two,
                                                               identifier='identity-one-env-two')

        trait_key = 'trait-key'
        Trait.objects.create(identity=identity_one_environment_one, trait_key=trait_key, string_value='blah',
                             value_type=STRING)
        Trait.objects.create(identity=identity_one_environment_two, trait_key=trait_key, string_value='blah',
                             value_type=STRING)

        url = reverse('api-v1:environments:environment-delete-traits', args=[environment_one.api_key])

        # When
        self.client.post(url, data={'key': trait_key})

        # Then
        assert not Trait.objects.filter(identity=identity_one_environment_one, trait_key=trait_key).exists()

        # and
        assert Trait.objects.filter(identity=identity_one_environment_two, trait_key=trait_key).exists()

    def test_delete_trait_keys_deletes_traits_matching_provided_key_only(self):
        # Given
        environment = Environment.objects.create(project=self.project, name='Test Environment')

        identity = Identity.objects.create(identifier='test-identity', environment=environment)

        trait_to_delete = 'trait-key-to-delete'
        Trait.objects.create(identity=identity, trait_key=trait_to_delete, value_type=STRING, string_value='blah')

        trait_to_persist = 'trait-key-to-persist'
        Trait.objects.create(identity=identity, trait_key=trait_to_persist, value_type=STRING, string_value='blah')

        url = reverse('api-v1:environments:environment-delete-traits', args=[environment.api_key])

        # When
        self.client.post(url, data={'key': trait_to_delete})

        # Then
        assert not Trait.objects.filter(identity=identity, trait_key=trait_to_delete).exists()

        # and
        assert Trait.objects.filter(identity=identity, trait_key=trait_to_persist).exists()

    def test_user_can_list_environment_permission(self):
        # Given
        url = reverse('api-v1:environments:environment-permissions')

        # When
        response = self.client.get(url)

        # Then
        assert response.status_code == status.HTTP_200_OK
        assert len(response.json()) == 1  # hard code how many permissions we expect there to be

    def test_environment_user_can_get_their_permissions(self):
        # Given
        user = FFAdminUser.objects.create(email='new-test@test.com')
        user.add_organisation(self.organisation)
        environment = Environment.objects.create(name='Test environment', project=self.project)
        user_permission = UserEnvironmentPermission.objects.create(user=user, environment=environment)
        user_permission.add_permission('VIEW_ENVIRONMENT')
        url = reverse('api-v1:environments:environment-my-permissions', args=[environment.api_key])

        # When
        self.client.force_authenticate(user)
        response = self.client.get(url)

        # Then
        assert response.status_code == status.HTTP_200_OK
        assert not response.json()['admin']
        assert 'VIEW_ENVIRONMENT' in response.json()['permissions']


@pytest.mark.django_db
class IdentityTestCase(TestCase):
    identifier = 'user1'
    put_template = '{ "enabled" : "%r" }'
    post_template = '{ "feature" : "%s", "enabled" : "%r" }'
    feature_states_url = '/api/v1/environments/%s/identities/%s/featurestates/'
    feature_states_detail_url = feature_states_url + "%d/"
    identities_url = '/api/v1/environments/%s/identities/%s/'

    def setUp(self):
        self.client = APIClient()
        user = Helper.create_ffadminuser()
        self.client.force_authenticate(user=user)

        self.organisation = Organisation.objects.create(name='Test Org')
        user.add_organisation(self.organisation, OrganisationRole.ADMIN)  # admin to bypass perms

        self.project = Project.objects.create(name='Test project', organisation=self.organisation)
        self.environment = Environment.objects.create(name='Test Environment', project=self.project)
        self.identity = Identity.objects.create(identifier=self.identifier, environment=self.environment)

    def test_should_return_identities_list_when_requested(self):
        # Given - set up data

        # When
        response = self.client.get(self.identities_url % (self.identity.environment.api_key,
                                                          self.identity.id))

        # Then
        assert response.status_code == status.HTTP_200_OK

    def test_should_create_identity_feature_when_post(self):
        # Given
        feature = Feature.objects.create(name='feature1', project=self.project)

        # When
        response = self.client.post(self.feature_states_url % (self.identity.environment.api_key,
                                                               self.identity.id),
                                    data=self.post_template % (feature.id, True),
                                    content_type='application/json')

        # Then
        identity_features = self.identity.identity_features
        assert response.status_code == status.HTTP_201_CREATED
        assert identity_features.count() == 1

    def test_should_return_BadRequest_when_duplicate_identityFeature_is_posted(self):
        # Given
        feature = Feature.objects.create(name='feature2', project=self.project)

        # When
        initial_response = self.client.post(self.feature_states_url % (self.identity.environment.api_key,
                                                                       self.identity.id),
                                            data=self.post_template % (feature.id, True),
                                            content_type='application/json')
        second_response = self.client.post(self.feature_states_url % (self.identity.environment.api_key,
                                                                      self.identity.id),
                                           data=self.post_template % (feature.id, True),
                                           content_type='application/json')

        # Then
        identity_feature = self.identity.identity_features
        assert initial_response.status_code == status.HTTP_201_CREATED
        assert second_response.status_code == status.HTTP_400_BAD_REQUEST
        assert identity_feature.count() == 1

    def test_should_change_enabled_state_when_put(self):
        # Given
        feature = Feature.objects.create(name='feature1', project=self.project)
        feature_state = FeatureState.objects.create(feature=feature,
                                                    identity=self.identity,
                                                    enabled=False,
                                                    environment=self.environment)

        # When
        response = self.client.put(self.feature_states_detail_url % (self.identity.environment.api_key,
                                                                     self.identity.id,
                                                                     feature_state.id),
                                   data=self.put_template % True,
                                   content_type='application/json')
        feature_state.refresh_from_db()

        # Then
        assert response.status_code == status.HTTP_200_OK
        assert feature_state.enabled == True

    def test_should_remove_identity_feature_when_delete(self):
        # Given
        feature_one = Feature.objects.create(name='feature1', project=self.project)
        feature_two = Feature.objects.create(name='feature2', project=self.project)
        identity_feature_one = FeatureState.objects.create(feature=feature_one,
                                                           identity=self.identity,
                                                           enabled=False,
                                                           environment=self.environment)
        identity_feature_two = FeatureState.objects.create(feature=feature_two,
                                                           identity=self.identity,
                                                           enabled=True,
                                                           environment=self.environment)

        # When
        self.client.delete(self.feature_states_detail_url % (self.identity.environment.api_key,
                                                             self.identity.id,
                                                             identity_feature_one.id),
                           content_type='application/json')

        # Then
        identity_features = FeatureState.objects.filter(identity=self.identity)
        assert identity_features.count() == 1

    def test_can_search_for_identities(self):
        # Given
        Identity.objects.create(identifier='user2', environment=self.environment)
        base_url = reverse('api-v1:environments:environment-identities-list', args=[self.environment.api_key])
        url = '%s?q=%s' % (base_url, self.identifier)

        # When
        res = self.client.get(url)

        # Then
        assert res.status_code == status.HTTP_200_OK

        # and - only identity matching search appears
        assert res.json().get('count') == 1

    def test_search_is_case_insensitive(self):
        # Given
        Identity.objects.create(identifier='user2', environment=self.environment)
        base_url = reverse('api-v1:environments:environment-identities-list', args=[self.environment.api_key])
        url = '%s?q=%s' % (base_url, self.identifier.upper())

        # When
        res = self.client.get(url)

        # Then
        assert res.status_code == status.HTTP_200_OK

        # and - identity matching search appears
        assert res.json().get('count') == 1

    def test_no_identities_returned_if_search_matches_none(self):
        # Given
        base_url = reverse('api-v1:environments:environment-identities-list', args=[self.environment.api_key])
        url = '%s?q=%s' % (base_url, 'some invalid search string')

        # When
        res = self.client.get(url)

        # Then
        assert res.status_code == status.HTTP_200_OK

        # and
        assert res.json().get('count') == 0

    def test_search_identities_still_allows_paging(self):
        # Given
        self._create_n_identities(10)
        base_url = reverse('api-v1:environments:environment-identities-list', args=[self.environment.api_key])
        url = '%s?q=%s' % (base_url, 'user')

        res1 = self.client.get(url)
        second_page = res1.json().get('next')

        # When
        res2 = self.client.get(second_page)

        # Then
        assert res2.status_code == status.HTTP_200_OK

        # and
        assert res2.json().get('results')

    def _create_n_identities(self, n):
        for i in range(2, n + 2):
            identifier = 'user%d' % i
            Identity.objects.create(identifier=identifier, environment=self.environment)

    def test_can_delete_identity(self):
        # Given
        url = reverse('api-v1:environments:environment-identities-detail', args=[self.environment.api_key,
                                                                                 self.identity.id])

        # When
        res = self.client.delete(url)

        # Then
        assert res.status_code == status.HTTP_204_NO_CONTENT

        # and
        assert not Identity.objects.filter(id=self.identity.id).exists()


@pytest.mark.django_db
class SDKIdentitiesTestCase(APITestCase):
    def setUp(self) -> None:
        self.organisation = Organisation.objects.create(name='Test Org')
        self.project = Project.objects.create(organisation=self.organisation, name='Test Project')
        self.environment = Environment.objects.create(project=self.project, name='Test Environment')
        self.feature_1 = Feature.objects.create(project=self.project, name='Test Feature 1')
        self.feature_2 = Feature.objects.create(project=self.project, name='Test Feature 2')
        self.identity = Identity.objects.create(environment=self.environment, identifier='test-identity')
        self.client.credentials(HTTP_X_ENVIRONMENT_KEY=self.environment.api_key)

    def tearDown(self) -> None:
        Segment.objects.all().delete()

    def test_identities_endpoint_returns_all_feature_states_for_identity_if_feature_not_provided(self):
        # Given
        base_url = reverse('api-v1:sdk-identities')
        url = base_url + '?identifier=' + self.identity.identifier

        # When
        response = self.client.get(url)

        # Then
        assert response.status_code == status.HTTP_200_OK

        # and
        assert len(response.json().get('flags')) == 2

    def test_identities_endpoint_returns_traits(self):
        # Given
        base_url = reverse('api-v1:sdk-identities')
        url = base_url + '?identifier=' + self.identity.identifier
        trait = Trait.objects.create(identity=self.identity, trait_key='trait_key', value_type='STRING',
                                     string_value='trait_value')

        # When
        response = self.client.get(url)

        # Then
        assert response.json().get('traits') is not None

        # and
        assert response.json().get('traits')[0].get('trait_value') == trait.get_trait_value()

    def test_identities_endpoint_returns_single_feature_state_if_feature_provided(self):
        # Given
        base_url = reverse('api-v1:sdk-identities')
        url = base_url + '?identifier=' + self.identity.identifier + '&feature=' + self.feature_1.name

        # When
        response = self.client.get(url)

        # Then
        assert response.status_code == status.HTTP_200_OK

        # and
        assert response.json().get('feature').get('name') == self.feature_1.name

    def test_identities_endpoint_returns_value_for_segment_if_identity_in_segment(self):
        # Given
        base_url = reverse('api-v1:sdk-identities')
        url = base_url + '?identifier=' + self.identity.identifier

        trait_key = 'trait_key'
        trait_value = 'trait_value'
        Trait.objects.create(identity=self.identity, trait_key=trait_key, value_type='STRING', string_value=trait_value)
        segment = Segment.objects.create(name='Test Segment', project=self.project)
        segment_rule = SegmentRule.objects.create(segment=segment, type=SegmentRule.ALL_RULE)
        Condition.objects.create(operator='EQUAL', property=trait_key, value=trait_value, rule=segment_rule)
        FeatureSegment.objects.create(segment=segment, feature=self.feature_2, enabled=True, priority=1)

        # When
        response = self.client.get(url)

        # Then
        assert response.status_code == status.HTTP_200_OK

        # and
        assert response.json().get('flags')[1].get('enabled')

    def test_identities_endpoint_returns_value_for_segment_if_identity_in_segment_and_feature_specified(self):
        # Given
        base_url = reverse('api-v1:sdk-identities')
        url = base_url + '?identifier=' + self.identity.identifier + '&feature=' + self.feature_1.name

        trait_key = 'trait_key'
        trait_value = 'trait_value'
        Trait.objects.create(identity=self.identity, trait_key=trait_key, value_type='STRING',
                             string_value=trait_value)
        segment = Segment.objects.create(name='Test Segment', project=self.project)
        segment_rule = SegmentRule.objects.create(segment=segment, type=SegmentRule.ALL_RULE)
        Condition.objects.create(operator='EQUAL', property=trait_key, value=trait_value, rule=segment_rule)
        FeatureSegment.objects.create(segment=segment, feature=self.feature_1, enabled=True, priority=1)

        # When
        response = self.client.get(url)

        # Then
        assert response.status_code == status.HTTP_200_OK

        # and
        assert response.json().get('enabled')

    def test_identities_endpoint_returns_value_for_segment_if_rule_type_percentage_split_and_identity_in_segment(self):
        # Given
        base_url = reverse('api-v1:sdk-identities')
        url = base_url + '?identifier=' + self.identity.identifier

        segment = Segment.objects.create(name='Test Segment', project=self.project)
        segment_rule = SegmentRule.objects.create(segment=segment, type=SegmentRule.ALL_RULE)

        identity_percentage_value = segment.get_identity_percentage_value(self.identity)
        Condition.objects.create(operator=models.PERCENTAGE_SPLIT,
                                 value=(identity_percentage_value + (1 - identity_percentage_value) / 2) * 100.0,
                                 rule=segment_rule)
        FeatureSegment.objects.create(segment=segment, feature=self.feature_1, enabled=True, priority=1)

        # When
        self.client.credentials(HTTP_X_ENVIRONMENT_KEY=self.environment.api_key)
        response = self.client.get(url)

        # Then
        for flag in response.json()['flags']:
            if flag['feature']['name'] == self.feature_1.name:
                assert flag['enabled']

    def test_identities_endpoint_returns_default_value_if_rule_type_percentage_split_and_identity_not_in_segment(self):
        # Given
        base_url = reverse('api-v1:sdk-identities')
        url = base_url + '?identifier=' + self.identity.identifier

        segment = Segment.objects.create(name='Test Segment', project=self.project)
        segment_rule = SegmentRule.objects.create(segment=segment, type=SegmentRule.ALL_RULE)

        identity_percentage_value = segment.get_identity_percentage_value(self.identity)
        Condition.objects.create(operator=models.PERCENTAGE_SPLIT,
                                 value=identity_percentage_value / 2,
                                 rule=segment_rule)
        FeatureSegment.objects.create(segment=segment, feature=self.feature_1, enabled=True, priority=1)

        # When
        self.client.credentials(HTTP_X_ENVIRONMENT_KEY=self.environment.api_key)
        response = self.client.get(url)

        # Then
        assert not response.json().get('flags')[0].get('enabled')


class SDKTraitsTest(APITestCase):
    JSON = 'application/json'

    def setUp(self) -> None:
        organisation = Organisation.objects.create(name='Test organisation')
        project = Project.objects.create(name='Test project', organisation=organisation)
        self.environment = Environment.objects.create(name='Test environment', project=project)
        self.identity = Identity.objects.create(identifier='test-user', environment=self.environment)
        self.client.credentials(HTTP_X_ENVIRONMENT_KEY=self.environment.api_key)
        self.trait_key = 'trait_key'
        self.trait_value = 'trait_value'

    def tearDown(self) -> None:
        Trait.objects.all().delete()
        Identity.objects.all().delete()

    def test_can_set_trait_for_an_identity(self):
        # Given
        url = reverse('api-v1:sdk-traits-list')

        # When
        res = self.client.post(url, data=self._generate_json_trait_data(), content_type=self.JSON)

        # Then
        assert res.status_code == status.HTTP_200_OK

        # and
        assert Trait.objects.filter(identity=self.identity, trait_key=self.trait_key).exists()

    def test_can_set_trait_with_boolean_value_for_an_identity(self):
        # Given
        url = reverse('api-v1:sdk-traits-list')
        trait_value = True

        # When
        res = self.client.post(url, data=self._generate_json_trait_data(trait_value=trait_value),
                               content_type=self.JSON)

        # Then
        assert res.status_code == status.HTTP_200_OK

        # and
        assert Trait.objects.get(identity=self.identity, trait_key=self.trait_key).get_trait_value() == trait_value

    def test_can_set_trait_with_identity_value_for_an_identity(self):
        # Given
        url = reverse('api-v1:sdk-traits-list')
        trait_value = 12

        # When
        res = self.client.post(url, data=self._generate_json_trait_data(trait_value=trait_value),
                               content_type=self.JSON)

        # Then
        assert res.status_code == status.HTTP_200_OK

        # and
        assert Trait.objects.get(identity=self.identity, trait_key=self.trait_key).get_trait_value() == trait_value

    def test_add_trait_creates_identity_if_it_doesnt_exist(self):
        # Given
        url = reverse('api-v1:sdk-traits-list')
        identifier = 'new-identity'

        # When
        res = self.client.post(url, data=self._generate_json_trait_data(identifier=identifier), content_type=self.JSON)

        # Then
        assert res.status_code == status.HTTP_200_OK

        # and
        assert Identity.objects.filter(identifier=identifier, environment=self.environment).exists()

        # and
        assert Trait.objects.filter(identity__identifier=identifier, trait_key=self.trait_key).exists()

    def test_trait_is_updated_if_already_exists(self):
        # Given
        url = reverse('api-v1:sdk-traits-list')
        trait = Trait.objects.create(trait_key=self.trait_key, value_type=STRING, string_value=self.trait_value,
                                     identity=self.identity)
        new_value = 'Some new value'

        # When
        self.client.post(url, data=self._generate_json_trait_data(trait_value=new_value), content_type=self.JSON)

        # Then
        trait.refresh_from_db()
        assert trait.get_trait_value() == new_value

    def test_increment_value_increments_trait_value_if_value_positive_integer(self):
        # Given
        initial_value = 2
        increment_by = 2

        url = reverse('api-v1:sdk-traits-increment-value')
        trait = Trait.objects.create(identity=self.identity, trait_key=self.trait_key, value_type=INTEGER,
                                     integer_value=initial_value)
        data = {
            'trait_key': self.trait_key,
            'identifier': self.identity.identifier,
            'increment_by': increment_by
        }

        # When
        self.client.post(url, data=data)

        # Then
        trait.refresh_from_db()
        assert trait.get_trait_value() == initial_value + increment_by

    def test_increment_value_decrements_trait_value_if_value_negative_integer(self):
        # Given
        initial_value = 2
        increment_by = -2

        url = reverse('api-v1:sdk-traits-increment-value')
        trait = Trait.objects.create(identity=self.identity, trait_key=self.trait_key, value_type=INTEGER,
                                     integer_value=initial_value)
        data = {
            'trait_key': self.trait_key,
            'identifier': self.identity.identifier,
            'increment_by': increment_by
        }

        # When
        self.client.post(url, data=data)

        # Then
        trait.refresh_from_db()
        assert trait.get_trait_value() == initial_value + increment_by

    def test_increment_value_initialises_trait_with_a_value_of_zero_if_it_doesnt_exist(self):
        # Given
        increment_by = 1

        url = reverse('api-v1:sdk-traits-increment-value')
        data = {
            'trait_key': self.trait_key,
            'identifier': self.identity.identifier,
            'increment_by': increment_by
        }

        # When
        self.client.post(url, data=data)

        # Then
        trait = Trait.objects.get(trait_key=self.trait_key, identity=self.identity)
        assert trait.get_trait_value() == increment_by

    def test_increment_value_returns_400_if_trait_value_not_integer(self):
        # Given
        url = reverse('api-v1:sdk-traits-increment-value')
        Trait.objects.create(identity=self.identity, trait_key=self.trait_key, value_type=STRING, string_value='str')
        data = {
            'trait_key': self.trait_key,
            'identifier': self.identity.identifier,
            'increment_by': 2
        }

        # When
        res = self.client.post(url, data=data)

        # Then
        assert res.status_code == status.HTTP_400_BAD_REQUEST

    def test_bulk_create_traits(self):
        # Given
        num_traits = 20
        url = reverse('api-v1:sdk-traits-bulk-create')
        traits = [self._generate_trait_data(trait_key=f'trait_{i}') for i in range(num_traits)]

        # When
        response = self.client.put(url, data=json.dumps(traits), content_type='application/json')

        # Then
        assert response.status_code == status.HTTP_200_OK
        assert Trait.objects.filter(identity=self.identity).count() == num_traits

    def test_sending_null_value_in_bulk_create_deletes_trait_for_identity(self):
        # Given
        url = reverse('api-v1:sdk-traits-bulk-create')
        trait = Trait.objects.create(trait_key=self.trait_key, value_type=STRING, string_value=self.trait_value,
                                     identity=self.identity)
        data = [{
            'identity': {
                'identifier': self.identity.identifier
            },
            'trait_key': self.trait_key,
            'trait_value': None
        }]

        # When
        response = self.client.put(url, data=json.dumps(data), content_type='application/json')

        # Then
        assert response.status_code == status.HTTP_200_OK
        assert not Trait.objects.filter(id=trait.id).exists()

    def _generate_trait_data(self, identifier=None, trait_key=None, trait_value=None):
        identifier = identifier or self.identity.identifier
        trait_key = trait_key or self.trait_key
        trait_value = trait_value or self.trait_value

        return {
            'identity': {
                'identifier': identifier
            },
            'trait_key': trait_key,
            'trait_value': trait_value
        }

    def _generate_json_trait_data(self, identifier=None, trait_key=None, trait_value=None):
        return json.dumps(self._generate_trait_data(identifier, trait_key, trait_value))


@pytest.mark.django_db
class TraitViewSetTestCase(TestCase):
    def setUp(self) -> None:
        self.client = APIClient()
        user = Helper.create_ffadminuser()
        self.client.force_authenticate(user=user)

        organisation = Organisation.objects.create(name='Test org')
        user.add_organisation(organisation, OrganisationRole.ADMIN)

        self.project = Project.objects.create(name='Test project', organisation=organisation)
        self.environment = Environment.objects.create(name='Test environment', project=self.project)
        self.identity = Identity.objects.create(identifier='test-user', environment=self.environment)

    def test_can_delete_trait(self):
        # Given
        trait_key = 'trait_key'
        trait_value = 'trait_value'
        trait = Trait.objects.create(identity=self.identity, trait_key=trait_key, value_type=STRING,
                                     string_value=trait_value)
        url = reverse('api-v1:environments:identities-traits-detail',
                      args=[self.environment.api_key, self.identity.id, trait.id])

        # When
        res = self.client.delete(url)

        # Then
        assert res.status_code == status.HTTP_204_NO_CONTENT

        # and
        assert not Trait.objects.filter(pk=trait.id).exists()

    def test_delete_trait_only_deletes_single_trait_if_query_param_not_provided(self):
        # Given
        trait_key = 'trait_key'
        trait_value = 'trait_value'
        identity_2 = Identity.objects.create(identifier='test-user-2', environment=self.environment)

        trait = Trait.objects.create(identity=self.identity, trait_key=trait_key, value_type=STRING,
                                     string_value=trait_value)
        trait_2 = Trait.objects.create(identity=identity_2, trait_key=trait_key, value_type=STRING,
                                       string_value=trait_value)

        url = reverse('api-v1:environments:identities-traits-detail',
                      args=[self.environment.api_key, self.identity.id, trait.id])

        # When
        self.client.delete(url)

        # Then
        assert not Trait.objects.filter(pk=trait.id).exists()

        # and
        assert Trait.objects.filter(pk=trait_2.id).exists()

    def test_delete_trait_deletes_all_traits_if_query_param_provided(self):
        # Given
        trait_key = 'trait_key'
        trait_value = 'trait_value'
        identity_2 = Identity.objects.create(identifier='test-user-2', environment=self.environment)

        trait = Trait.objects.create(identity=self.identity, trait_key=trait_key, value_type=STRING,
                                     string_value=trait_value)
        trait_2 = Trait.objects.create(identity=identity_2, trait_key=trait_key, value_type=STRING,
                                       string_value=trait_value)

        base_url = reverse('api-v1:environments:identities-traits-detail',
                           args=[self.environment.api_key, self.identity.id, trait.id])
        url = base_url + '?deleteAllMatchingTraits=true'

        # When
        self.client.delete(url)

        # Then
        assert not Trait.objects.filter(pk=trait.id).exists()

        # and
        assert not Trait.objects.filter(pk=trait_2.id).exists()

    def test_delete_trait_only_deletes_traits_in_current_environment(self):
        # Given
        environment_2 = Environment.objects.create(name='Test environment', project=self.project)
        trait_key = 'trait_key'
        trait_value = 'trait_value'
        identity_2 = Identity.objects.create(identifier='test-user-2', environment=environment_2)

        trait = Trait.objects.create(identity=self.identity, trait_key=trait_key, value_type=STRING,
                                     string_value=trait_value)
        trait_2 = Trait.objects.create(identity=identity_2, trait_key=trait_key, value_type=STRING,
                                       string_value=trait_value)

        base_url = reverse('api-v1:environments:identities-traits-detail',
                           args=[self.environment.api_key, self.identity.id, trait.id])
        url = base_url + '?deleteAllMatchingTraits=true'

        # When
        self.client.delete(url)

        # Then
        assert not Trait.objects.filter(pk=trait.id).exists()

        # and
        assert Trait.objects.filter(pk=trait_2.id).exists()


@pytest.mark.django_db
class WebhookViewSetTestCase(TestCase):
    def setUp(self) -> None:
        self.client = APIClient()
        user = Helper.create_ffadminuser()
        self.client.force_authenticate(user=user)

        organisation = Organisation.objects.create(name='Test organisation')
        user.add_organisation(organisation, OrganisationRole.ADMIN)

        project = Project.objects.create(name='Test project', organisation=organisation)
        self.environment = Environment.objects.create(name='Test environment', project=project)

        self.valid_webhook_url = 'http://my.webhook.com/webhooks'

    def test_can_create_webhook_for_an_environment(self):
        # Given
        url = reverse('api-v1:environments:environment-webhooks-list', args=[self.environment.api_key])
        data = {
            'url': self.valid_webhook_url,
            'enabled': True
        }

        # When
        res = self.client.post(url, data)

        # Then
        assert res.status_code == status.HTTP_201_CREATED

        # and
        assert Webhook.objects.filter(environment=self.environment, **data).exists()

    def test_can_update_webhook_for_an_environment(self):
        # Given
        webhook = Webhook.objects.create(url=self.valid_webhook_url, environment=self.environment)
        url = reverse('api-v1:environments:environment-webhooks-detail', args=[self.environment.api_key, webhook.id])
        data = {
            'url': 'http://my.new.url.com/wehbooks',
            'enabled': False
        }

        # When
        res = self.client.put(url, data=json.dumps(data), content_type='application/json')

        # Then
        assert res.status_code == status.HTTP_200_OK

        # and
        webhook.refresh_from_db()
        assert webhook.url == data['url'] and not webhook.enabled

    def test_can_delete_webhook_for_an_environment(self):
        # Given
        webhook = Webhook.objects.create(url=self.valid_webhook_url, environment=self.environment)
        url = reverse('api-v1:environments:environment-webhooks-detail', args=[self.environment.api_key, webhook.id])

        # When
        res = self.client.delete(url)

        # Then
        assert res.status_code == status.HTTP_204_NO_CONTENT

        # and
        assert not Webhook.objects.filter(id=webhook.id).exists()

    def test_can_list_webhooks_for_an_environment(self):
        # Given
        webhook = Webhook.objects.create(url=self.valid_webhook_url, environment=self.environment)
        url = reverse('api-v1:environments:environment-webhooks-list', args=[self.environment.api_key])

        # When
        res = self.client.get(url)

        # Then
        assert res.status_code == status.HTTP_200_OK

        # and
        assert res.json()[0]['id'] == webhook.id

    def test_cannot_delete_webhooks_for_environment_user_does_not_belong_to(self):
        # Given
        new_organisation = Organisation.objects.create(name='New organisation')
        new_project = Project.objects.create(name='New project', organisation=new_organisation)
        new_environment = Environment.objects.create(name='New Environment', project=new_project)
        webhook = Webhook.objects.create(url=self.valid_webhook_url, environment=new_environment)
        url = reverse('api-v1:environments:environment-webhooks-detail', args=[self.environment.api_key, webhook.id])

        # When
        res = self.client.delete(url)

        # Then
        assert res.status_code == status.HTTP_404_NOT_FOUND

        # and
        assert Webhook.objects.filter(id=webhook.id).exists()


@pytest.mark.django_db
class UserEnvironmentPermissionsViewSetTestCase(TestCase):
    def setUp(self) -> None:
        self.organisation = Organisation.objects.create(name='Test')
        self.project = Project.objects.create(name='Test', organisation=self.organisation)
        self.environment = Environment.objects.create(name='Test', project=self.project)

        # Admin to bypass permission checks
        self.org_admin = FFAdminUser.objects.create(email='admin@test.com')
        self.org_admin.add_organisation(self.organisation, OrganisationRole.ADMIN)

        # create a project user
        user = FFAdminUser.objects.create(email='user@test.com')
        user.add_organisation(self.organisation, OrganisationRole.USER)
        read_permission = EnvironmentPermissionModel.objects.get(key="VIEW_ENVIRONMENT")
        self.user_environment_permission = UserEnvironmentPermission.objects.create(user=user,
                                                                                    environment=self.environment)
        self.user_environment_permission.permissions.set([read_permission])

        self.client = APIClient()
        self.client.force_authenticate(self.org_admin)

        self.list_url = reverse('api-v1:environments:environment-user-permissions-list',
                                args=[self.environment.api_key])
        self.detail_url = reverse('api-v1:environments:environment-user-permissions-detail',
                                  args=[self.environment.api_key, self.user_environment_permission.id])

    def test_user_can_list_all_user_permissions_for_an_environment(self):
        # Given - set up data

        # When
        response = self.client.get(self.list_url)

        # Then
        assert response.status_code == status.HTTP_200_OK
        assert len(response.json()) == 1

    def test_user_can_create_new_user_permission_for_an_environment(self):
        # Given
        new_user = FFAdminUser.objects.create(email='new_user@test.com')
        new_user.add_organisation(self.organisation, OrganisationRole.USER)
        data = {
            'user': new_user.id,
            'permissions': [
                "VIEW_ENVIRONMENT",
            ],
            'admin': False
        }

        # When
        response = self.client.post(self.list_url, data=json.dumps(data), content_type='application/json')

        # Then
        assert response.status_code == status.HTTP_201_CREATED
        assert response.json()['permissions'] == data['permissions']

        assert UserEnvironmentPermission.objects.filter(user=new_user, environment=self.environment).exists()
        user_environment_permission = UserEnvironmentPermission.objects.get(user=new_user, environment=self.environment)
        assert user_environment_permission.permissions.count() == 1

    def test_user_can_update_user_permission_for_a_project(self):
        # Given - empty user environment permission
        another_user = FFAdminUser.objects.create(email='anotheruser@test.com')
        empty_permission = UserEnvironmentPermission.objects.create(user=another_user, environment=self.environment)
        data = {
            'permissions': [
                'VIEW_ENVIRONMENT'
            ]
        }
        url = reverse('api-v1:environments:environment-user-permissions-detail', args=[self.environment.api_key,
                                                                                       empty_permission.id])

        # When
        response = self.client.patch(url, data=json.dumps(data), content_type='application/json')

        # Then
        assert response.status_code == status.HTTP_200_OK

        self.user_environment_permission.refresh_from_db()
        assert 'VIEW_ENVIRONMENT' in self.user_environment_permission.permissions.values_list('key', flat=True)

    def test_user_can_delete_user_permission_for_a_project(self):
        # Given - set up data

        # When
        response = self.client.delete(self.detail_url)

        # Then
        assert response.status_code == status.HTTP_204_NO_CONTENT
        assert not UserProjectPermission.objects.filter(id=self.user_environment_permission.id).exists()


@pytest.mark.django_db
class UserPermissionGroupProjectPermissionsViewSetTestCase(TestCase):
    def setUp(self) -> None:
        self.organisation = Organisation.objects.create(name='Test')
        self.project = Project.objects.create(name='Test', organisation=self.organisation)
        self.environment = Environment.objects.create(name='Test', project=self.project)

        # Admin to bypass permission checks
        self.org_admin = FFAdminUser.objects.create(email='admin@test.com')
        self.org_admin.add_organisation(self.organisation, OrganisationRole.ADMIN)

        # create a project user
        self.user = FFAdminUser.objects.create(email='user@test.com')
        self.user.add_organisation(self.organisation, OrganisationRole.USER)
        read_permission = EnvironmentPermissionModel.objects.get(key="VIEW_ENVIRONMENT")

        self.user_permission_group = UserPermissionGroup.objects.create(name='Test group',
                                                                        organisation=self.organisation)
        self.user_permission_group.users.add(self.user)

        self.user_group_environment_permission = UserPermissionGroupEnvironmentPermission.objects.create(
            group=self.user_permission_group,
            environment=self.environment
        )
        self.user_group_environment_permission.permissions.set([read_permission])

        self.client = APIClient()
        self.client.force_authenticate(self.org_admin)

        self.list_url = reverse('api-v1:environments:environment-user-group-permissions-list',
                                args=[self.environment.api_key])
        self.detail_url = reverse('api-v1:environments:environment-user-group-permissions-detail',
                                  args=[self.environment.api_key, self.user_group_environment_permission.id])

    def test_user_can_list_all_user_group_permissions_for_an_environment(self):
        # Given - set up data

        # When
        response = self.client.get(self.list_url)

        # Then
        assert response.status_code == status.HTTP_200_OK
        assert len(response.json()) == 1

    def test_user_can_create_new_user_group_permission_for_an_environment(self):
        # Given
        new_group = UserPermissionGroup.objects.create(name='New group', organisation=self.organisation)
        new_group.users.add(self.user)
        data = {
            'group': new_group.id,
            'permissions': [
                "VIEW_ENVIRONMENT",
            ],
            'admin': False
        }

        # When
        response = self.client.post(self.list_url, data=json.dumps(data), content_type='application/json')

        # Then
        assert response.status_code == status.HTTP_201_CREATED
        assert sorted(response.json()['permissions']) == sorted(data['permissions'])

        assert UserPermissionGroupEnvironmentPermission.objects.filter(group=new_group,
                                                                       environment=self.environment).exists()
        user_group_environment_permission = UserPermissionGroupEnvironmentPermission.objects.get(group=new_group,
                                                                                                 environment=self.environment)
        assert user_group_environment_permission.permissions.count() == 1

    def test_user_can_update_user_group_permission_for_an_environment(self):
        # Given
        data = {
            'permissions': []
        }

        # When
        response = self.client.patch(self.detail_url, data=json.dumps(data), content_type='application/json')

        # Then
        assert response.status_code == status.HTTP_200_OK

        self.user_group_environment_permission.refresh_from_db()
        assert self.user_group_environment_permission.permissions.count() == 0

    def test_user_can_delete_user_permission_for_a_project(self):
        # Given - set up data

        # When
        response = self.client.delete(self.detail_url)

        # Then
        assert response.status_code == status.HTTP_204_NO_CONTENT
        assert not UserPermissionGroupEnvironmentPermission.objects.filter(
            id=self.user_group_environment_permission.id).exists()
