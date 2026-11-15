"""Real provider smoke. Explicit opt-in; never substitutes mock model responses."""
import json
import os
import time
from urllib.error import HTTPError
from urllib.request import Request, urlopen

BASE = os.environ.get('BENCHCODER_API_URL', 'http://127.0.0.1:8000/api').rstrip('/')


def api(method, path, data=None, token=None, expected=(200,)):
    headers = {'Content-Type': 'application/json'}
    if token:
        headers['Authorization'] = 'Bearer ' + token
    req = Request(BASE + path, None if data is None else json.dumps(data).encode(), headers, method=method)
    try:
        response = urlopen(req, timeout=30)
    except HTTPError as exc:
        response = exc
    payload = json.loads(response.read())
    assert response.status in expected, f'{method} {path}: HTTP{response.status}'
    return payload


def main():
    if os.environ.get('BENCHCODER_ALLOW_PROVIDER_CALLS') != '1':
        raise SystemExit('Set BENCHCODER_ALLOW_PROVIDER_CALLS=1 to authorize real billed provider requests.')
    password = os.environ['HINT_DEMO_PASSWORD']
    results = []
    for username in ('demo_arrays', 'demo_strings'):
        token = api('POST', '/auth/login/', {'username': username, 'password': password})['access']
        config = api('GET', '/hints/config/', token=token)
        assert config['enabled'], 'Provider is not configured; no fake hint will be generated'
        expected_backend = os.environ.get('BENCHCODER_EXPECT_RETRIEVAL_BACKEND')
        if expected_backend:
            assert config.get('retrieval_backend') == expected_backend, 'Unexpected retrieval backend'
        print(username + ' retrieval backend: ' + config.get('retrieval_backend', 'local'), flush=True)
        listing = api('GET', '/problems/?search=%5BHint%20Demo%5D%20Two%20Sum&page_size=50', token=token)
        target = next(problem for problem in listing['results'] if problem['title'] == '[Hint Demo] Two Sum')
        history = api('GET', '/submissions/', token=token)
        solved = {row['problem'] for row in history if row['kind'] == 'submit' and row['status'] == 'completed' and row['verdict'] == 'AC'}
        assert len(solved) >= 2, 'Run actual demo solution evaluation before requesting hints'
        job = api('POST', '/hints/', {'problem': target['id'], 'level': 'concept', 'language': 'python'}, token, (200, 202))
        deadline = time.monotonic() + 180
        while job['status'] in ('queued', 'running') and time.monotonic() < deadline:
            time.sleep(0.5)
            job = api('GET', f'/hints/{job["id"]}/', token=token)
        assert job['status'] == 'completed', 'Real hint failed: ' + job.get('error_message', 'timeout')
        assert job['hint'].strip() and '```' not in job['hint']
        source_ids = {source['problem_id'] for source in job['retrieved_sources']}
        assert source_ids and source_ids <= solved and target['id'] not in source_ids
        results.append((token, job, source_ids))
        print(username + ' sources: ' + ', '.join(source['title'] for source in job['retrieved_sources']), flush=True)
        print(username + ' hint: ' + job['hint'], flush=True)
    assert results[0][2] != results[1][2], 'Personalized sources must differ for distinct solved histories'
    api('GET', f'/hints/{results[0][1]["id"]}/', token=results[1][0], expected=(404,))
    print('PASS real provider hints, differing learner sources, own solved-history restriction, owner-only access')


if __name__ == '__main__':
    main()
