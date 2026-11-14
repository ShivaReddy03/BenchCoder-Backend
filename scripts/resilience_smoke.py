"""Opt-in local Compose resilience smoke; temporarily stops worker and Redis.

Run manually only when other UI/integration testing is idle. Requires admin
credentials via BENCHCODER_ADMIN_USERNAME/PASSWORD and a running Compose stack.
Uses the same API URL override as integration_smoke.py. Services are restored in
finally. Never run against a shared production stack.
"""
import os
from pathlib import Path
import secrets
import subprocess
import time

from integration_smoke import request, wait_result

ROOT = Path(__file__).resolve().parents[1]


def compose(*args):
    result = subprocess.run(['docker', 'compose', *args], cwd=ROOT,
                            stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                            text=True, timeout=90)
    if result.returncode:
        raise RuntimeError('Compose operation failed: ' + ' '.join(args[:2]))
    return result.stdout.strip()


def wait_service(service, command):
    deadline = time.monotonic() + 60
    while time.monotonic() < deadline:
        try:
            compose('exec', '-T', service, *command)
            return
        except RuntimeError:
            time.sleep(1)
    raise AssertionError(service + ' failed to become ready')


def main():
    if os.environ.get('BENCHCODER_ALLOW_SERVICE_RESTART') != '1':
        raise SystemExit('Set BENCHCODER_ALLOW_SERVICE_RESTART=1 to explicitly run this service-restart smoke.')
    admin = request('POST', '/auth/login/', {
        'username': os.environ['BENCHCODER_ADMIN_USERNAME'],
        'password': os.environ['BENCHCODER_ADMIN_PASSWORD'],
    })['access']
    suffix = secrets.token_hex(6)
    username = 'resilience_' + suffix
    registered = request('POST', '/auth/register/', {
        'username': username, 'email': username + '@example.invalid',
        'password': secrets.token_urlsafe(32),
    }, expected=201)
    token = registered['access']
    problem_id = None
    redis_stopped = worker_stopped = False
    try:
        problem = request('POST', '/problems/create/', {
            'title': 'Resilience smoke ' + suffix, 'description': 'Echo stdin.',
            'difficulty': 'easy', 'points': 13,
        }, admin, 201)
        problem_id = problem['id']
        request('POST', f'/problems/{problem_id}/testcases/', {
            'input': 'reliable', 'expected_output': 'reliable', 'is_public': True,
        }, admin, 201)
        payload = {'problem': problem_id, 'language': 'python', 'code': 'print(input())'}
        # Queue real duplicate deliveries before restarting the worker. All three
        # messages address the same row; compare-and-set must allow one execution.
        worker_stopped = True
        compose('stop', 'celery')
        queued = request('POST', '/submissions/create/', payload, token, 202)
        submission_id = int(queued['id'])
        assert queued['status'] == 'queued'
        compose('exec', '-T', 'web', 'python', 'manage.py', 'shell', '-c',
                'from judge.tasks import judge_submission; '
                f'judge_submission.delay({submission_id}); judge_submission.delay({submission_id})')
        assert request('GET', f'/submissions/{submission_id}/', token=token)['status'] == 'queued'
        compose('start', 'celery')
        worker_stopped = False
        accepted = wait_result(token, submission_id, 'AC')
        # A final delivery after completion must leave timestamps, metrics and
        # attempt counter untouched as well as preserving the unique solve award.
        compose('exec', '-T', 'celery', 'python', 'manage.py', 'shell', '-c',
                f'from judge.tasks import judge_submission; judge_submission.delay({submission_id})')
        time.sleep(2)
        final = request('GET', f'/submissions/{submission_id}/', token=token)
        assert final == accepted, 'Duplicate delivery changed a terminal result'
        row = compose('exec', '-T', 'web', 'python', 'manage.py', 'shell', '-c',
                      f'from submissions.models import Submission; print(Submission.objects.get(pk={submission_id}).attempt)')
        assert row.splitlines()[-1] == '1', 'Duplicate queue deliveries executed the submission more than once'
        profile = request('GET', '/auth/profile/', token=token)
        assert (profile['score'], profile['problems_solved']) == (13, 1)
        print('PASS queued job survives worker stop/start; concurrent and terminal duplicates execute once', flush=True)
        # Broker outage must return a truthful failed row promptly, never execute
        # user code inside the API request or return fabricated acceptance.
        redis_stopped = True
        compose('stop', 'redis')
        started = time.monotonic()
        failed = request('POST', '/submissions/create/', payload, token, 503)
        elapsed = time.monotonic() - started
        assert elapsed < 10, f'Broker failure took {elapsed:.1f}s, expected under10s'
        assert failed['status'] == 'failed' and failed['verdict'] == 'OT'
        stored = request('GET', f'/submissions/{failed["id"]}/', token=token)
        assert stored['status'] == 'failed' and stored['finished_at']
        assert request('GET', '/auth/profile/', token=token)['score'] == 13
        print(f'PASS broker outage503 in {elapsed:.2f}s; failure persisted without synchronous execution', flush=True)
        compose('start', 'redis')
        redis_stopped = False
        wait_service('redis', ['redis-cli', 'ping'])
        # Restart Celery to establish a clean broker connection and prove recovery.
        compose('restart', 'celery')
        resumed = request('POST', '/submissions/create/', payload, token, 202)
        wait_result(token, resumed['id'], 'AC')
        assert request('GET', '/auth/profile/', token=token)['score'] == 13
        print('PASS broker/worker recovery accepts new asynchronous work', flush=True)
    finally:
        if redis_stopped:
            compose('start', 'redis')
        if worker_stopped or redis_stopped:
            compose('start', 'celery')
        if problem_id is not None:
            request('DELETE', f'/problems/{problem_id}/', token=admin, expected=204)
        print('Cleanup complete; operator may remove account ' + username, flush=True)


if __name__ == '__main__':
    main()
