"""Real HTTP/Redis/Celery/Docker smoke test; run against an isolated local stack.

Set BENCHCODER_ADMIN_USERNAME and BENCHCODER_ADMIN_PASSWORD in the environment.
Optionally set BENCHCODER_API_URL (default http://127.0.0.1:8000/api).
Creates uniquely named users and cleans its problems/cases/submissions via admin API.
User accounts require operator cleanup because no account-delete API exists.
"""
import json
import os
import secrets
import time
from urllib.error import HTTPError
from urllib.request import Request, urlopen

BASE = os.environ.get('BENCHCODER_API_URL', 'http://127.0.0.1:8000/api').rstrip('/')


def request(method, path, data=None, token=None, expected=200):
    headers = {'Content-Type': 'application/json'}
    if token:
        headers['Authorization'] = 'Bearer ' + token
    body = None if data is None else json.dumps(data).encode()
    req = Request(BASE + path, body, headers, method=method)
    try:
        response = urlopen(req, timeout=15)
    except HTTPError as exc:
        response = exc
    content = response.read()
    payload = json.loads(content) if content else None
    assert response.status == expected, f'{method} {path}: expected {expected}, got {response.status}'
    return payload


def wait_result(token, submission_id, verdict):
    deadline = time.monotonic() + 180
    while time.monotonic() < deadline:
        result = request('GET', f'/submissions/{submission_id}/', token=token)
        if result['status'] in ('completed', 'failed'):
            assert result['status'] == 'completed', f'Worker infrastructure failure: {result["error_message"]}'
            assert result['verdict'] == verdict, f'Expected {verdict}, got {result["verdict"]}: {result["error_message"]}'
            return result
        time.sleep(0.5)
    raise AssertionError('Execution did not finish within 180 seconds')


def main():
    admin = request('POST', '/auth/login/', {
        'username': os.environ['BENCHCODER_ADMIN_USERNAME'],
        'password': os.environ['BENCHCODER_ADMIN_PASSWORD'],
    })['access']
    suffix = secrets.token_hex(6)
    users = []
    problems = []
    try:
        for index in range(2):
            username = f'smoke_{suffix}_{index}'
            registered = request('POST', '/auth/register/', {
                'username': username, 'email': username + '@example.invalid',
                'password': secrets.token_urlsafe(32),
            }, expected=201)
            assert 'refresh' not in registered and not registered['user']['is_staff']
            users.append(registered['access'])
        user, other_user = users
        before = request('GET', '/auth/profile/', token=user)
        problem = request('POST', '/problems/create/', {
            'title': f'Integration smoke {suffix}', 'description': 'Read an integer and print twice its value.',
            'difficulty': 'easy', 'points': 17,
        }, admin, 201)
        pid = problem['id']
        problems.append(pid)
        detail_path = f'/problems/{pid}/'
        cases_path = detail_path + 'testcases/'
        request('PATCH', detail_path, {'description': 'Read one integer from stdin and print twice it.'}, admin)
        request('PATCH', detail_path, {'title': 'forbidden'}, user, 403)
        request('DELETE', detail_path, token=user, expected=403)
        case = request('POST', cases_path, {'input': '4', 'expected_output': '8', 'is_public': True}, admin, 201)
        case_path = cases_path + str(case['id']) + '/'
        request('PATCH', case_path, {'input': '5', 'expected_output': '10'}, admin)
        request('PATCH', case_path, {'input': 'forbidden'}, user, 403)
        request('DELETE', case_path, token=user, expected=403)
        # A deleted extra case verifies deletion without reducing coverage.
        extra = request('POST', cases_path, {'input': '', 'expected_output': ''}, admin, 201)
        request('DELETE', cases_path + str(extra['id']) + '/', token=admin, expected=204)
        for value in (6, 7, 8):
            request('POST', cases_path, {'input': str(value), 'expected_output': str(2 * value), 'is_public': True}, admin, 201)
        secret_input = '987654321'
        request('POST', cases_path, {'input': secret_input, 'expected_output': '1975308642', 'is_public': False}, admin, 201)
        detail = request('GET', detail_path, token=user)
        assert len(detail['sample_test_cases']) == 3
        assert 'test_cases' not in detail and secret_input not in json.dumps(detail)
        assert len(request('GET', cases_path, token=admin)) == 5
        request('GET', cases_path, token=user, expected=403)
        listing = request('GET', f'/problems/?page_size=1&search={suffix}', token=user)
        assert listing['total_count'] == 1 and listing['page_size'] == 1
        request('POST', '/submissions/create/', {'problem': pid, 'language': 'java', 'code': 'invalid'}, user, 400)
        py_ac = 'print(int(input()) * 2)'
        js_ac = "const fs = require('fs'); console.log(Number(fs.readFileSync(0, 'utf8').trim()) * 2);"
        def execute(code, language, verdict, kind='submit'):
            endpoint = '/submissions/run/' if kind == 'run' else '/submissions/create/'
            queued = request('POST', endpoint, {'problem': pid, 'language': language, 'code': code}, user, 202)
            request('GET', f'/submissions/{queued["id"]}/', token=other_user, expected=404)
            result = wait_result(user, queued['id'], verdict)
            assert secret_input not in json.dumps(result), 'Hidden test data leaked in results'
            print(f'PASS {language} {kind} {verdict}', flush=True)
            return result
        run = execute(py_ac, 'python', 'AC', 'run')
        assert run['total_tests'] == 3 and run['passed_tests'] == 3
        assert request('GET', '/auth/profile/', token=user)['score'] == before['score']
        accepted = execute(py_ac, 'python', 'AC')
        assert accepted['total_tests'] == 5 and accepted['passed_tests'] == 5
        execute(js_ac, 'javascript', 'AC')
        profile = request('GET', '/auth/profile/', token=user)
        assert profile['score'] == before['score'] + 17
        assert profile['problems_solved'] == before['problems_solved'] + 1
        execute('print(0)', 'python', 'WA')
        execute('raise RuntimeError("deliberate smoke failure")', 'python', 'RE')
        execute('def invalid syntax', 'python', 'CE')
        execute('while True: pass', 'python', 'TLE')
        execute('console.log(0)', 'javascript', 'WA')
        execute('throw new Error("deliberate smoke failure")', 'javascript', 'RE')
        execute('const = ;', 'javascript', 'CE')
        execute('while (true) {}', 'javascript', 'TLE')
        if os.environ.get('BENCHCODER_TEST_MLE') == '1':
            execute('import time\nx = bytearray(1024 * 1024 * 1024)\ntime.sleep(1)', 'python', 'MLE')
        history = request('GET', '/submissions/', token=user)
        assert any(item['id'] == accepted['id'] for item in history)
        assert all(item['kind'] == 'submit' for item in history)
        assert request('GET', '/submissions/', token=other_user) == []
        print('PASS auth, roles, admin CRUD, redaction, pagination, ownership, history, scoring idempotency', flush=True)
    finally:
        for pid in problems:
            request('DELETE', f'/problems/{pid}/', token=admin, expected=204)
        print(f'Cleanup complete; operator may remove accounts with prefix smoke_{suffix}_', flush=True)


if __name__ == '__main__':
    main()
