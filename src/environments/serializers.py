from rest_framework import serializers, exceptions

from features.serializers import FeatureStateSerializerFull
from environments.models import Environment, Identity, Trait, INTEGER
from projects.serializers import ProjectSerializer
from segments.serializers import SegmentSerializerBasic


class EnvironmentSerializerFull(serializers.ModelSerializer):
    feature_states = FeatureStateSerializerFull(many=True)
    project = ProjectSerializer()

    class Meta:
        model = Environment
        fields = ('id', 'name', 'feature_states', 'project', 'api_key')


class EnvironmentSerializerLight(serializers.ModelSerializer):

    class Meta:
        model = Environment
        fields = ('id', 'name', 'api_key', 'project', 'webhooks_enabled', 'webhook_url')
        read_only_fields = ('api_key',)


class IdentitySerializerFull(serializers.ModelSerializer):
    identity_features = FeatureStateSerializerFull(many=True)
    environment = EnvironmentSerializerFull()

    class Meta:
        model = Identity
        fields = ('id', 'identifier', 'identity_features', 'environment')


class IdentitySerializer(serializers.ModelSerializer):

    class Meta:
        model = Identity
        fields = ('id', 'identifier', 'environment')


class TraitSerializerFull(serializers.ModelSerializer):
    identity = IdentitySerializer()
    trait_value = serializers.SerializerMethodField()

    class Meta:
        model = Trait
        fields = "__all__"

    @staticmethod
    def get_trait_value(obj):
        return obj.get_trait_value()


class TraitSerializerBasic(serializers.ModelSerializer):
    trait_value = serializers.SerializerMethodField()

    class Meta:
        model = Trait
        fields = ('trait_key', 'trait_value')

    @staticmethod
    def get_trait_value(obj):
        return obj.get_trait_value()


class CreateTraitSerializer(serializers.Serializer):
    class _IdentitySerializer(serializers.ModelSerializer):
        class Meta:
            model = Identity
            fields = ('identifier',)

    trait_key = serializers.CharField()
    trait_value = serializers.CharField()
    identity = _IdentitySerializer()

    trait_value_data = {}

    def to_representation(self, instance):
        return {
            'trait_value': instance.get_trait_value(),
            'trait_key': instance.trait_key
        }

    def create(self, validated_data):
        identity = self._get_identity(validated_data)

        trait_data = {
            'trait_key': validated_data['trait_key'],
            'identity': identity
        }

        self.trait_value_data = Trait.generate_trait_value_data(validated_data['trait_value'])

        trait, created = Trait.objects.get_or_create(**trait_data, defaults=self.trait_value_data)

        return trait if created else self.update(trait, validated_data)

    def _get_identity(self, validated_data):
        identity_data = {
            **validated_data['identity'],
            'environment': self.context.get('request').environment
        }
        identity, _ = Identity.objects.get_or_create(**identity_data)
        return identity

    def update(self, instance, validated_data):
        if not self.trait_value_data:
            self.trait_value_data = Trait.generate_trait_value_data(validated_data['trait_value'])

        for key, value in self.trait_value_data.items():
            setattr(instance, key, value)

        instance.save()
        return instance


class IncrementTraitValueSerializer(serializers.Serializer):
    trait_key = serializers.CharField()
    increment_by = serializers.IntegerField(write_only=True)
    identifier = serializers.CharField()
    trait_value = serializers.IntegerField(read_only=True)

    def to_representation(self, instance):
        return {
            'trait_key': instance.trait_key,
            'trait_value': instance.integer_value,
            'identifier': instance.identity.identifier
        }

    def create(self, validated_data):
        trait, _ = Trait.objects.get_or_create(**self._build_query_data(validated_data),
                                               defaults=self._build_default_data())

        if trait.value_type != INTEGER:
            raise exceptions.ValidationError('Trait is not an integer.')

        trait.integer_value += validated_data.get('increment_by')
        trait.save()
        return trait

    def _build_query_data(self, validated_data):
        identity_data = {
            'identifier': validated_data.get('identifier'),
            'environment': self.context.get('request').environment
        }
        identity, _ = Identity.objects.get_or_create(**identity_data)

        return {
            'trait_key': validated_data.get('trait_key'),
            'identity': identity
        }

    def _build_default_data(self):
        return {
            'value_type': INTEGER,
            'integer_value': 0
        }

# Serializer for returning both Feature Flags and User Traits
class IdentitySerializerTraitFlags(serializers.Serializer):
    flags = FeatureStateSerializerFull(many=True)
    traits = TraitSerializerBasic(many=True)


class IdentitySerializerWithTraitsAndSegments(serializers.Serializer):
    def update(self, instance, validated_data):
        pass

    def create(self, validated_data):
        pass

    flags = FeatureStateSerializerFull(many=True)
    traits = TraitSerializerBasic(many=True)
    segments = SegmentSerializerBasic(many=True)
