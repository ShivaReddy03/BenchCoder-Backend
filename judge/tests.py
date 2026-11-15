from unittest.mock import MagicMock, patch
from django.test import SimpleTestCase
from .runner import execute, InfrastructureError


class RunnerIsolationTests(SimpleTestCase):
    @patch('judge.runner.docker.from_env')
    def test_runner_enforces_isolation_and_cleans_up(self, factory):
        client = factory.return_value
        container = client.containers.create.return_value
        client.containers.list.return_value = []
        client.volumes.list.return_value = []
        container.status = 'exited'
        container.attrs = {'State': {'ExitCode': 0, 'OOMKilled': False}}
        container.logs.side_effect = [b'answer\n', b'']
        result = execute('print(1)', 'python', '')
        options = client.containers.create.call_args.kwargs
        self.assertTrue(options['read_only'])
        self.assertEqual(options['network_mode'], 'none')
        self.assertEqual(options['cap_drop'], ['ALL'])
        self.assertEqual(options['user'], '65534:65534')
        self.assertEqual(options['pids_limit'], 32)
        self.assertEqual(result['output'], 'answer\n')
        self.assertEqual(container.remove.call_count, 2)

    @patch('judge.runner.docker.from_env')
    def test_docker_failure_never_executes_on_host(self, factory):
        import docker
        factory.side_effect = docker.errors.DockerException('offline')
        with self.assertRaises(InfrastructureError):
            execute('print(1)', 'python', '')

class FinisherReconnectTests(__import__('django.test', fromlist=['TransactionTestCase']).TransactionTestCase):
    def test_ambiguous_commit_retries_without_duplicate_award(self):
        from unittest.mock import patch
        from django.contrib.auth import get_user_model
        from django.db import OperationalError
        from problems.models import Problem
        from submissions.models import Submission, ProblemSolve
        from judge import tasks
        user = get_user_model().objects.create_user(username='reconnect_solver')
        problem = Problem.objects.create(title='Reconnect fixture',description='Fixture',difficulty='easy',points=10)
        sub = Submission.objects.create(user=user,problem=problem,code='print(1)',language='python',status='running',attempt=1)
        real_finish = tasks._finish_once
        calls = []
        def ambiguous_commit(*args):
            result = real_finish(*args)
            calls.append(1)
            if len(calls) == 1:
                raise OperationalError('Simulated connection loss after commit')
            return result
        with patch('judge.tasks._finish_once',side_effect=ambiguous_commit), patch('judge.tasks.time.sleep'):
            tasks.finish(sub.id,1,{'status':'completed','verdict':'AC','passed_tests':1,'total_tests':1})
        user.refresh_from_db()
        sub.refresh_from_db()
        self.assertEqual(len(calls),2)
        self.assertEqual((sub.status,sub.verdict),('completed','AC'))
        self.assertEqual((user.score,user.problems_solved),(10,1))
        self.assertEqual(ProblemSolve.objects.filter(user=user,problem=problem).count(),1)
