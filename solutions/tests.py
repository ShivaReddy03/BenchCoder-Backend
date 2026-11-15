import json
from datetime import timedelta
from unittest.mock import patch
from django.contrib.auth import get_user_model
from django.db import OperationalError
from django.db.models.query import QuerySet
from django.test import SimpleTestCase, TransactionTestCase, override_settings
from django.urls import reverse
from django.utils import timezone
from rest_framework.test import APITestCase
from problems.models import Problem, TestCase as Case
from hints.provider import ProviderError
from .models import SolutionRequest
from .context import request_fingerprint
from .tasks import generate_request
from .provider import generate_solution

VALUES = {'explanation': 'Accumulate the readings.', 'solution_code': 'print(sum(map(int, input().split())))', 'time_complexity': 'O(n)', 'space_complexity': 'O(n)'}
SETTINGS = dict(AI_API_KEY='test-provider-key', AI_SOLUTION_MODEL='gpt-4.1-mini', AI_SOLUTIONS_DAILY_LIMIT=10, AI_SOLUTIONS_GLOBAL_DAILY_LIMIT=100)


@override_settings(**SETTINGS)
class SolutionWorkflowTests(APITestCase):
    def setUp(self):
        self.user = get_user_model().objects.create_user(username='solution-user')
        self.other = get_user_model().objects.create_user(username='solution-other')
        self.problem = Problem.objects.create(title='Sum readings', description='Print sum of stdin integers.', difficulty='easy')
        self.public = Case.objects.create(problem=self.problem, input='1 2', expected_output='3', is_public=True)
        Case.objects.create(problem=self.problem, input='PRIVATE_TEST_INPUT', expected_output='PRIVATE_TEST_OUTPUT')
        self.payload = {'problem': self.problem.id, 'code': '', 'language': 'python'}
        self.client.force_authenticate(self.user)

    def job(self, **values):
        data = dict(user=self.user, problem=self.problem, code='', language='python', fingerprint=request_fingerprint(self.user.id, self.problem))
        data.update(values)
        return SolutionRequest.objects.create(**data)

    @patch('solutions.views.generate_request.apply_async')
    def test_async_pending_reused_and_other_active_rejected(self, dispatch):
        first = self.client.post(reverse('solution-create'), self.payload)
        self.assertEqual(first.status_code, 202)
        repeat = self.client.post(reverse('solution-create'), self.payload)
        self.assertEqual(repeat.status_code, 202)
        self.assertEqual(first.data['id'], repeat.data['id'])
        dispatch.assert_called_once()
        self.assertEqual(self.client.post(reverse('solution-create'), {**self.payload, 'code': 'attempt'}).status_code, 429)

    @override_settings(AI_SOLUTIONS_DAILY_LIMIT=0)
    @patch('solutions.views.generate_request.apply_async')
    def test_completed_cache_has_no_age_limit_and_precedes_quota(self, dispatch):
        cached = self.job(status='completed', **VALUES)
        SolutionRequest.objects.filter(pk=cached.id).update(created_at=timezone.now()-timedelta(days=100))
        response = self.client.post(reverse('solution-create'), self.payload)
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.data['id'], cached.id)
        dispatch.assert_not_called()

    def test_fingerprint_is_scoped_to_user_code_language_model_and_problem_version(self):
        baseline = request_fingerprint(self.user.id, self.problem)
        self.assertNotEqual(baseline, request_fingerprint(self.other.id, self.problem))
        self.assertNotEqual(baseline, request_fingerprint(self.user.id, self.problem, 'attempt'))
        self.assertNotEqual(baseline, request_fingerprint(self.user.id, self.problem, language='javascript'))
        with override_settings(AI_SOLUTION_MODEL='another-model'):
            self.assertNotEqual(baseline, request_fingerprint(self.user.id, self.problem))
        self.public.expected_output = '4'; self.public.save()
        self.assertNotEqual(baseline, request_fingerprint(self.user.id, self.problem))
        baseline = request_fingerprint(self.user.id, self.problem)
        self.problem.description = 'Changed statement'; self.problem.save()
        self.assertNotEqual(baseline, request_fingerprint(self.user.id, self.problem))

    @patch('solutions.views.generate_request.apply_async')
    def test_changed_input_cannot_reuse_completed_cache(self, dispatch):
        cached = self.job(status='completed', **VALUES)
        response = self.client.post(reverse('solution-create'), {**self.payload, 'code': 'different attempt'})
        self.assertEqual(response.status_code, 202)
        self.assertNotEqual(response.data['id'], cached.id)
        dispatch.assert_called_once()

    def test_owner_only_and_auth_validation(self):
        job = self.job()
        self.client.force_authenticate(self.other)
        self.assertEqual(self.client.get(reverse('solution-detail', args=[job.id])).status_code, 404)
        self.assertEqual(self.client.post(reverse('solution-create'), {**self.payload, 'language': 'ruby'}).status_code, 400)
        self.assertEqual(self.client.post(reverse('solution-create'), {**self.payload, 'code': 'x'*12001}).status_code, 400)
        self.client.force_authenticate(None)
        self.assertEqual(self.client.get(reverse('solution-config')).status_code, 401)

    @override_settings(AI_API_KEY='')
    @patch('solutions.views.generate_request.apply_async')
    def test_unconfigured_failure_is_persisted_without_dispatch(self, dispatch):
        self.assertFalse(self.client.get(reverse('solution-config')).data['enabled'])
        response = self.client.post(reverse('solution-create'), self.payload)
        self.assertEqual(response.status_code, 503)
        self.assertEqual(response.data['status'], 'failed')
        self.assertTrue(SolutionRequest.objects.get().finished_at)
        dispatch.assert_not_called()

    @patch('solutions.views.generate_request.apply_async', side_effect=ConnectionError('broker offline'))
    def test_broker_failure_never_calls_provider_synchronously(self, dispatch):
        with patch('solutions.provider.generate_solution') as provider:
            response = self.client.post(reverse('solution-create'), self.payload)
        self.assertEqual(response.status_code, 503)
        self.assertEqual(response.data['status'], 'failed')
        provider.assert_not_called()

    @override_settings(AI_SOLUTIONS_DAILY_LIMIT=1)
    def test_failed_attempt_counts_toward_daily_quota(self):
        self.job(status='failed', error_message='Provider failed')
        self.assertEqual(self.client.post(reverse('solution-create'), self.payload).status_code, 429)

    @override_settings(AI_SOLUTIONS_GLOBAL_DAILY_LIMIT=1)
    def test_global_quota_counts_other_users(self):
        self.job(status='failed')
        self.client.force_authenticate(self.other)
        self.assertEqual(self.client.post(reverse('solution-create'), self.payload).status_code, 429)

    @patch('solutions.provider.generate_solution', return_value=VALUES)
    def test_task_public_context_only_and_duplicate_delivery_noop(self, provider):
        job = self.job()
        generate_request.run(job.id)
        job.refresh_from_db()
        self.assertEqual(job.status, 'completed')
        context = provider.call_args.args[0]
        self.assertNotIn('PRIVATE_TEST', str(context))
        self.assertEqual(context['problem']['sample_test_cases'], [{'input': '1 2', 'expected_output': '3'}])
        generate_request.run(job.id)
        provider.assert_called_once()

    @patch('solutions.provider.generate_solution')
    def test_problem_change_before_generation_rejected(self, provider):
        job = self.job()
        self.problem.description = 'Changed'; self.problem.save()
        generate_request.run(job.id)
        job.refresh_from_db()
        self.assertEqual(job.status, 'failed')
        provider.assert_not_called()

    def test_problem_change_during_generation_does_not_cache_stale_solution(self):
        job = self.job()
        def generate(context):
            Problem.objects.filter(pk=self.problem.id).update(description='New statement')
            return VALUES
        with patch('solutions.provider.generate_solution', side_effect=generate):
            generate_request.run(job.id)
        job.refresh_from_db()
        self.assertEqual(job.status, 'failed')
        self.assertEqual(job.solution_code, '')

    @patch('solutions.provider.generate_solution', side_effect=ProviderError('Credentials need attention.'))
    def test_provider_errors_are_truthful_terminal_failures(self, provider):
        job = self.job()
        generate_request.run(job.id)
        job.refresh_from_db()
        self.assertEqual(job.status, 'failed')
        self.assertEqual(job.error_message, 'Credentials need attention.')

    def test_stale_running_is_failed_on_read(self):
        job = self.job(status='running')
        SolutionRequest.objects.filter(pk=job.id).update(created_at=timezone.now()-timedelta(minutes=6))
        response = self.client.get(reverse('solution-detail', args=[job.id]))
        self.assertEqual(response.data['status'], 'failed')


@override_settings(**SETTINGS)
class SolutionProviderTests(SimpleTestCase):
    @patch('solutions.provider._post')
    def test_structured_request_allowlist_and_complete_result(self, post):
        post.return_value = {'status': 'completed', 'output': [{'type': 'message', 'content': [{'type': 'output_text', 'text': json.dumps(VALUES)}]}]}
        output = generate_solution({'problem': {'title': 'Sum', 'description': 'Sum input', 'sample_test_cases': [{'input': '1', 'expected_output': '1'}], 'hidden_tests': 'NEVER_SEND'}, 'language': 'python', 'code': 'my attempt', 'other_user': 'NEVER_SEND'})
        self.assertEqual(output, VALUES)
        payload = post.call_args.args[1]
        self.assertFalse(payload['store'])
        self.assertLessEqual(payload['max_output_tokens'], 2500)
        self.assertNotIn('NEVER_SEND', payload['input'])
        self.assertEqual(set(payload['text']['format']['schema']['required']), set(VALUES))

    @patch('solutions.provider._post', return_value={'status': 'incomplete', 'output': []})
    def test_incomplete_generation_is_not_presented_as_solution(self, post):
        with self.assertRaises(ProviderError):
            generate_solution({'problem': {'title': 'x', 'description': 'x'}, 'language': 'python'})


@override_settings(**SETTINGS)
class SolutionCloudPersistenceTests(TransactionTestCase):
    def test_final_database_failure_retries_sql_without_repeating_generation(self):
        user = get_user_model().objects.create_user(username='cloud-solution')
        problem = Problem.objects.create(title='Sum', description='Sum stdin', difficulty='easy')
        job = SolutionRequest.objects.create(user=user, problem=problem, language='python', fingerprint=request_fingerprint(user.id, problem))
        original = QuerySet.update; failures = []
        def update(queryset, **values):
            if queryset.model is SolutionRequest and values.get('status') == 'completed' and not failures:
                failures.append(True)
                raise OperationalError('SSL EOF')
            return original(queryset, **values)
        with patch.object(QuerySet, 'update', update), patch('solutions.provider.generate_solution', return_value=VALUES) as provider:
            generate_request.run(job.id)
            provider.assert_called_once()
        job.refresh_from_db()
        self.assertEqual(job.status, 'completed')
        self.assertEqual(job.solution_code, VALUES['solution_code'])
