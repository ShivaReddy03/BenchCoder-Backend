from unittest.mock import patch
from django.contrib.auth import get_user_model
from django.db import connection, OperationalError
from django.db.models.query import QuerySet
from django.test import TransactionTestCase, override_settings
from hints.models import HintRequest, ProblemKnowledge
from hints.retrieval import request_fingerprint
from hints.tasks import generate_request
from problems.models import Problem


@override_settings(AI_RETRIEVAL_BACKEND='local')
class CloudConnectionLifecycleTests(TransactionTestCase):
    def setUp(self):
        self.user = get_user_model().objects.create_user(username='cloud-learner')
        self.problem = Problem.objects.create(title='Cloud target', description='Public task', difficulty='easy')
        ProblemKnowledge.objects.create(problem=self.problem, concepts=['lookup'])
        self.job = HintRequest.objects.create(user=self.user, problem=self.problem, level='concept',
            fingerprint=request_fingerprint(self.user.id, self.problem, 'concept', '', 'python'))

    @patch('hints.tasks.retrieve', return_value=[])
    def test_paid_hint_is_generated_once_when_final_sql_socket_drops(self, retrieve):
        original = QuerySet.update
        failed = []
        def update(queryset, **values):
            if queryset.model is HintRequest and values.get('status') == 'completed' and not failed:
                failed.append(True)
                raise OperationalError('SSL connection has been closed unexpectedly')
            return original(queryset, **values)
        with patch.object(QuerySet, 'update', update), patch.object(connection, 'close', wraps=connection.close) as close:
            def provider(context):
                self.assertTrue(close.called, 'Database socket must be released before provider wait')
                return 'Consider a membership lookup.'
            with patch('hints.provider.generate_hint', side_effect=provider) as generate:
                generate_request.run(self.job.id)
                generate.assert_called_once()
        self.job.refresh_from_db()
        self.assertEqual(self.job.status, 'completed')
        self.assertEqual(self.job.hint, 'Consider a membership lookup.')
        self.assertEqual(len(failed), 1)

    @patch('hints.tasks.retrieve', return_value=[])
    @patch('hints.provider.generate_hint', side_effect=RuntimeError('provider transport failed'))
    def test_error_is_persisted_even_when_first_failure_write_uses_dead_socket(self, provider, retrieve):
        original = QuerySet.update
        failed = []
        def update(queryset, **values):
            if queryset.model is HintRequest and values.get('status') == 'failed' and not failed:
                failed.append(True)
                raise OperationalError('SSL EOF')
            return original(queryset, **values)
        with patch.object(QuerySet, 'update', update):
            generate_request.run(self.job.id)
        self.job.refresh_from_db()
        self.assertEqual(self.job.status, 'failed')
        self.assertNotIn('SSL', self.job.error_message)
        provider.assert_called_once()

    def test_explicit_transaction_connection_is_retained(self):
        from django.db import transaction
        from hints.db_lifecycle import release_connections
        with transaction.atomic(), patch.object(connection, 'close', wraps=connection.close) as close:
            release_connections()
            close.assert_not_called()
            self.assertTrue(Problem.objects.filter(pk=self.problem.id).exists())
