from rest_framework import serializers
from .models import Submission


class SubmissionSerializer(serializers.ModelSerializer):
    problem_title = serializers.CharField(source='problem.title', read_only=True)
    problem_difficulty = serializers.CharField(source='problem.difficulty', read_only=True)
    user_username = serializers.CharField(source='user.username', read_only=True)

    def to_representation(self, instance):
        data = super().to_representation(instance)
        # History omits sample_results, but its diagnostic needs the same visibility checks.
        original_samples = instance.sample_results or []
        public = {
            case.id: case for case in instance.problem.test_cases.filter(is_public=True).order_by('id')[:3]
        }
        visible_samples = [
            result for result in original_samples
            if result.get('testcase_id') in public
            and result.get('input') == public[result['testcase_id']].input
            and result.get('expected') == public[result['testcase_id']].expected_output
        ]
        if 'sample_results' in data:
            data['sample_results'] = visible_samples
        if len(visible_samples) != len(original_samples) and instance.verdict in ('RE', 'CE'):
            data['error_message'] = 'Execution failed. Test case visibility has changed.'
        return data

    class Meta:
        model = Submission
        fields = ('id', 'problem', 'problem_title', 'problem_difficulty', 'user_username', 'code', 'language', 'kind', 'status', 'verdict', 'execution_time', 'memory_used', 'passed_tests', 'total_tests', 'error_message', 'sample_results', 'submitted_at', 'started_at', 'finished_at')
        read_only_fields = fields


class SubmissionCreateSerializer(serializers.ModelSerializer):
    code = serializers.CharField(max_length=100000, trim_whitespace=False)

    class Meta:
        model = Submission
        fields = ('problem', 'code', 'language')

    def validate_code(self, value):
        if not value.strip():
            raise serializers.ValidationError('Code cannot be empty.')
        return value


class SubmissionListSerializer(SubmissionSerializer):
    class Meta(SubmissionSerializer.Meta):
        fields = tuple(f for f in SubmissionSerializer.Meta.fields if f not in ('code', 'sample_results'))
        read_only_fields = fields
