from rest_framework import serializers
from problems.models import Problem
from .models import HintRequest


class HintCreateSerializer(serializers.Serializer):
    problem = serializers.PrimaryKeyRelatedField(queryset=Problem.objects.all())
    level = serializers.ChoiceField(choices=['concept', 'approach', 'debugging'])
    code = serializers.CharField(max_length=12000, required=False, allow_blank=True, trim_whitespace=False, default='')
    language = serializers.ChoiceField(choices=['python', 'javascript', 'java', 'cpp'], default='python')

    def validate(self, attrs):
        if attrs['level'] == 'debugging' and not attrs['code'].strip():
            raise serializers.ValidationError({'code': 'Include your code when requesting debugging help.'})
        return attrs


class HintSerializer(serializers.ModelSerializer):
    class Meta:
        model = HintRequest
        fields = ('id', 'problem', 'level', 'language', 'status', 'hint', 'retrieved_sources', 'error_message', 'created_at', 'started_at', 'finished_at')
        read_only_fields = fields
