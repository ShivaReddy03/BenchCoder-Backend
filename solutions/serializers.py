from rest_framework import serializers
from problems.models import Problem
from .models import SolutionRequest


class SolutionCreateSerializer(serializers.Serializer):
    problem = serializers.PrimaryKeyRelatedField(queryset=Problem.objects.all())
    code = serializers.CharField(max_length=12000, required=False, allow_blank=True, trim_whitespace=False, default='')
    language = serializers.ChoiceField(choices=['python', 'javascript'], default='python')


class SolutionSerializer(serializers.ModelSerializer):
    class Meta:
        model = SolutionRequest
        fields = ('id', 'problem', 'language', 'status', 'explanation', 'solution_code', 'time_complexity', 'space_complexity', 'error_message', 'created_at', 'started_at', 'finished_at')
        read_only_fields = fields
