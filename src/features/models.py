# -*- coding: utf-8 -*-
from __future__ import unicode_literals

from django.core.exceptions import ObjectDoesNotExist
from django.db import models

from projects.models import Project


# Feature State Types
FLAG = 'FLAG'
CONFIG = 'CONFIG'

# Feature State Value Types
INTEGER = "int"
STRING = "unicode"
BOOLEAN = "bool"


class Feature(models.Model):
    name = models.CharField(max_length=2000)
    created_date = models.DateTimeField('DateCreated', auto_now_add=True)
    project = models.ForeignKey(Project, related_name='features')
    initial_value = models.CharField(max_length=2000, null=True, default=None)
    description = models.TextField(null=True)

    class Meta:
        ordering = ['id']
        # Note: uniqueness is changed to reference lowercase name in explicit SQL in the migrations
        unique_together = ("name", "project")

    def save(self, *args, **kwargs):
        """
        Override save method to initialise feature states for all environments
        """
        super(Feature, self).save(*args, **kwargs)

        # create feature states for all environments in the project
        environments = self.project.environments.all()
        for env in environments:
            FeatureState.objects.create(feature=self, environment=env, identity=None,
                                        enabled=False)

    def __str__(self):
        return "Project %s - Feature %s" % (self.project.name, self.name)

    def __unicode__(self):
        return "Project %s - Feature %s" % (self.project.name, self.name)


class FeatureState(models.Model):
    FEATURE_STATE_TYPES = (
        (FLAG, 'Feature Flag'),
        (CONFIG, 'Remote Config')
    )

    feature = models.ForeignKey(Feature, related_name='feature_states')
    environment = models.ForeignKey('environments.Environment', related_name='feature_states',
                                    null=True)
    identity = models.ForeignKey('environments.Identity', related_name='identity_features',
                                 null=True, default=None, blank=True)
    enabled = models.BooleanField(default=False)
    type = models.CharField(max_length=50, choices=FEATURE_STATE_TYPES, default=FLAG)

    class Meta:
        unique_together = ("feature", "environment", "identity")
        ordering = ['id']

    def get_feature_state_value(self):
        try:
            value_type = self.feature_state_value.type
        except ObjectDoesNotExist:
            return None

        if value_type == INTEGER:
            return self.feature_state_value.integer_value
        elif value_type == STRING:
            return self.feature_state_value.string_value
        elif value_type == BOOLEAN:
            return self.feature_state_value.boolean_value
        else:
            return None

    def save(self, *args, **kwargs):
        super(FeatureState, self).save(*args, **kwargs)

        # create default feature state value for feature state
        if not hasattr(self, 'feature_state_value'):
            FeatureStateValue.objects.create(feature_state=self,
                                             string_value=self.feature.initial_value)

    def generate_feature_state_value_data(self, value):
        """
        Takes the value of a feature state to generate a feature state value and returns dictionary
        to use for passing into feature state value serializer

        :param value: feature state value of variable type
        :return: dictionary to pass directly into feature state value serializer
        """
        fsv_type = type(value).__name__

        if fsv_type == INTEGER:
            fsv_dict = {"type": INTEGER, "integer_value": value}
        elif fsv_type == BOOLEAN:
            fsv_dict = {"type": BOOLEAN, "boolean_value": value}
        else:
            # default to type = string if we cannot handle the type correctly
            fsv_dict = {"type": STRING, "string_value": value}

        fsv_dict['feature_state'] = self.id

        return fsv_dict

    def __str__(self):
        if self.environment is not None:
            return "Project %s - Environment %s - Feature %s - Enabled: %r" % \
                   (self.environment.project.name,
                    self.environment.name, self.feature.name,
                    self.enabled)
        elif self.identity is not None:
            return "Identity %s - Feature %s - Enabled: %r" % (self.identity.identifier,
                                                               self.feature.name, self.enabled)
        else:
            return "Feature %s - Enabled: %r" % (self.feature.name, self.enabled)


class FeatureStateValue(models.Model):
    FEATURE_STATE_VALUE_TYPES = (
        (INTEGER, 'Integer'),
        (STRING, 'String'),
        (BOOLEAN, 'Boolean')
    )

    feature_state = models.OneToOneField(FeatureState, related_name='feature_state_value')
    type = models.CharField(max_length=10, choices=FEATURE_STATE_VALUE_TYPES, default=STRING,
                            null=True, blank=True)
    boolean_value = models.NullBooleanField(null=True, blank=True)
    integer_value = models.IntegerField(null=True, blank=True)
    string_value = models.CharField(null=True, max_length=2000, blank=True)
