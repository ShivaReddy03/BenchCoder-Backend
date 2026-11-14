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
