from unittest.mock import patch
from datetime import timedelta
from django.contrib.auth import get_user_model
from django.test import TestCase
from django.urls import reverse
from django.utils import timezone
from rest_framework.test import APITestCase
from problems.models import Problem, TestCase as Case
from submissions.models import Submission, ProblemSolve
from judge.tasks import judge_submission, recover_stale_submissions
from judge.runner import InfrastructureError


class SubmissionWorkflowTests(APITestCase):
    def setUp(self):
        self.user = get_user_model().objects.create_user(username='solver', password='password123')
        self.other = get_user_model().objects.create_user(username='other', password='password123')
        self.problem = Problem.objects.create(title='Echo', description='Echo input', difficulty='easy', points=10)
        self.public = Case.objects.create(problem=self.problem, input='hello', expected_output='hello', is_public=True)
        self.private = Case.objects.create(problem=self.problem, input='secret', expected_output='secret', is_public=False)
        self.client.force_authenticate(self.user)
        self.payload = {'problem': self.problem.id, 'code': 'print(input())', 'language': 'python'}

    @patch('submissions.views.judge_submission.apply_async')
    def test_queue_is_async_and_run_not_history(self, dispatch):
        response = self.client.post(reverse('submission-run'), self.payload)
        self.assertEqual(response.status_code, 202)
        self.assertEqual(response.data['status'], 'queued')
        dispatch.assert_called_once()
        self.assertEqual(self.client.get(reverse('submission-list')).data, [])

    @patch('submissions.views.judge_submission.apply_async', side_effect=ConnectionError)
    def test_queue_failure_is_persisted(self, dispatch):
        response = self.client.post(reverse('submission-create'), self.payload)
        self.assertEqual(response.status_code, 503)
        self.assertEqual(Submission.objects.get().status, 'failed')
        self.assertEqual(Submission.objects.get().verdict, 'OT')

    def test_ownership_and_language_validation(self):
        sub = Submission.objects.create(user=self.other, problem=self.problem, code='x', language='python')
        self.assertEqual(self.client.get(reverse('submission-detail', args=[sub.id])).status_code, 404)
        self.assertEqual(self.client.post(reverse('submission-create'), {**self.payload, 'language': 'ruby'}).status_code, 400)
        self.client.force_authenticate(None)
        self.assertEqual(self.client.post(reverse('submission-create'), self.payload).status_code, 401)

    @patch('submissions.views.judge_submission.apply_async')
    def test_compiled_languages_are_queued(self, dispatch):
        for language in ('java', 'cpp'):
            with self.subTest(language=language):
                response = self.client.post(reverse('submission-create'), {**self.payload, 'language': language})
                self.assertEqual(response.status_code, 202)
                self.assertEqual(Submission.objects.get(pk=response.data['id']).language, language)
        self.assertEqual(dispatch.call_count, 2)

    @patch('judge.tasks.execute')
    def test_acceptance_scores_once_duplicate_delivery_is_noop(self, execute):
        execute.side_effect = lambda code, lang, data: {'verdict': 'AC', 'output': data, 'error': '', 'time': .1, 'memory': 12}
        for _ in range(2):
            sub = Submission.objects.create(user=self.user, problem=self.problem, **{k:v for k,v in self.payload.items() if k != 'problem'})
            judge_submission.run(sub.id)
            calls = execute.call_count
            judge_submission.run(sub.id)
            self.assertEqual(execute.call_count, calls)
            sub.refresh_from_db()
            self.assertEqual((sub.status, sub.verdict, sub.passed_tests, sub.total_tests), ('completed', 'AC', 2, 2))
            self.assertNotIn('secret', str(sub.sample_results))
        self.user.refresh_from_db()
        self.assertEqual((self.user.score, self.user.problems_solved), (10, 1))
        self.assertEqual(ProblemSolve.objects.count(), 1)

    @patch('judge.tasks.execute')
    def test_run_uses_only_first_three_public_cases_and_does_not_score(self, execute):
        for number in range(4):
            Case.objects.create(problem=self.problem, input=str(number), expected_output=str(number), is_public=True)
        execute.side_effect = lambda code, lang, data: {'verdict': 'AC', 'output': data, 'error': '', 'time': .1, 'memory': None}
        sub = Submission.objects.create(user=self.user, problem=self.problem, code='x', language='python', kind='run')
        judge_submission.run(sub.id)
        sub.refresh_from_db()
        self.assertEqual(sub.total_tests, 3)
        self.assertEqual(len(sub.sample_results), 3)
        self.assertEqual(ProblemSolve.objects.count(), 0)

    @patch('judge.tasks.execute')
    def test_hidden_runtime_error_does_not_disclose_input(self, execute):
        execute.side_effect = [{'verdict':'AC', 'output':'hello', 'error':'', 'time':.1, 'memory':None}, {'verdict':'RE', 'output':'secret', 'error':'secret', 'time':.1, 'memory':None}]
        sub = Submission.objects.create(user=self.user, problem=self.problem, code='x', language='python')
        judge_submission.run(sub.id)
        sub.refresh_from_db()
        self.assertEqual(sub.verdict, 'RE')
        self.assertNotIn('secret', sub.error_message + str(sub.sample_results))

    def test_stale_worker_is_reported_as_failed(self):
        sub = Submission.objects.create(user=self.user, problem=self.problem, code='x', language='python', status='running', started_at=timezone.now()-timedelta(minutes=11))
        recover_stale_submissions()
        sub.refresh_from_db()
        self.assertEqual((sub.status, sub.verdict), ('failed', 'OT'))

    def test_empty_test_suite_is_rejected(self):
        Case.objects.all().delete()
        self.assertEqual(self.client.post(reverse('submission-create'), self.payload).status_code, 400)

    @patch('judge.tasks.execute', side_effect=InfrastructureError)
    def test_infrastructure_failure_retries_and_exhaustion_is_terminal(self, execute):
        from celery.exceptions import Retry
        sub = Submission.objects.create(user=self.user, problem=self.problem, code='x', language='python')
        with patch.object(judge_submission, 'retry', side_effect=Retry) as retry:
            with self.assertRaises(Retry):
                judge_submission.run(sub.id)
            retry.assert_called_once_with(countdown=5)
        sub.refresh_from_db()
        self.assertEqual(sub.status, 'queued')
        with patch.object(type(judge_submission.request), 'retries', 2, create=True):
            judge_submission.run(sub.id)
        sub.refresh_from_db()
        self.assertEqual((sub.status, sub.verdict), ('failed', 'OT'))

    def test_visibility_change_redacts_stored_results_and_errors(self):
        sub = Submission.objects.create(user=self.user, problem=self.problem, code='x', language='python', status='completed', verdict='RE', error_message='hello secret diagnostic', sample_results=[{'testcase_id':self.public.id, 'input':'hello', 'expected':'hello', 'output':'hello secret diagnostic', 'passed':False}])
        self.public.is_public = False
        self.public.save()
        response = self.client.get(reverse('submission-detail', args=[sub.id]))
        self.assertEqual(response.data['sample_results'], [])
        self.assertNotIn('secret diagnostic', response.data['error_message'])

    def test_history_redacts_diagnostic_after_sample_becomes_private(self):
        Submission.objects.create(
            user=self.user, problem=self.problem, code='x', language='python',
            status='completed', verdict='RE', error_message='formerly public private-input',
            sample_results=[{'testcase_id': self.public.id, 'input': 'hello', 'expected': 'hello', 'output': 'private-input', 'passed': False}],
        )
        self.public.is_public = False
        self.public.save()
        response = self.client.get(reverse('submission-list'))
        self.assertEqual(response.status_code, 200)
        self.assertNotIn('private-input', str(response.data))
        self.assertNotIn('sample_results', response.data[0])

    def test_changed_expected_output_redacts_historical_diagnostic(self):
        sub = Submission.objects.create(
            user=self.user, problem=self.problem, code='x', language='python',
            status='completed', verdict='RE', error_message='old expected output',
            sample_results=[{'testcase_id': self.public.id, 'input': 'hello', 'expected': 'hello', 'output': '', 'passed': False}],
        )
        self.public.expected_output = 'updated'
        self.public.save()
        response = self.client.get(reverse('submission-detail', args=[sub.id]))
        self.assertEqual(response.data['sample_results'], [])
        self.assertNotIn('old expected output', response.data['error_message'])
