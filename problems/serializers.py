from rest_framework import serializers
from .models import Problem, TestCase


class TestCaseSerializer(serializers.ModelSerializer):
    class Meta:
        model = TestCase
        fields = ('id', 'problem', 'input', 'expected_output', 'is_public')
        read_only_fields = ('id', 'problem')
        extra_kwargs = {'input': {'allow_blank': True}, 'expected_output': {'allow_blank': True}}


class ProblemSerializer(serializers.ModelSerializer):
    sample_test_cases = serializers.SerializerMethodField()
    supported_languages = serializers.SerializerMethodField()
    points = serializers.IntegerField(min_value=1)

    class Meta:
        model = Problem
        fields = ('id', 'title', 'description', 'difficulty', 'points',
                  'created_at', 'updated_at', 'sample_test_cases', 'supported_languages')
        read_only_fields = ('id', 'created_at', 'updated_at')

    def get_sample_test_cases(self, obj):
        return TestCaseSerializer(obj.test_cases.filter(is_public=True).order_by('id')[:3], many=True).data

    def get_supported_languages(self, obj):
        return ['python', 'javascript']

    def to_representation(self, instance):
        data = super().to_representation(instance)
        request = self.context.get('request')
        if request and request.user.is_staff:
            data['test_cases'] = TestCaseSerializer(instance.test_cases.order_by('id'), many=True).data
        return data


class ProblemListSerializer(serializers.ModelSerializer):
    class Meta:
        model = Problem
        fields = ('id', 'title', 'difficulty', 'points', 'description')
