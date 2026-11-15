"""Opt-in live full-solution smoke using the provider, cache, and Docker sample run.

Requires BENCHCODER_ALLOW_PROVIDER_CALLS=1 and
BENCHCODER_SOLUTION_USERNAME / BENCHCODER_SOLUTION_PASSWORD.
Optional BENCHCODER_ADMIN_USERNAME / BENCHCODER_ADMIN_PASSWORD checks ownership.
The generated solution stays cached for the learner. Only a sample run is created;
this script never submits it for credit or changes the learner's solved history.
"""
import json
import os
import time
from urllib.error import HTTPError
from urllib.parse import urlencode
from urllib.request import Request, urlopen

BASE = os.environ.get('BENCHCODER_API_URL','http://127.0.0.1:8000/api').rstrip('/')


def api(method,path,data=None,token=None,expected=(200,)):
    headers = {'Content-Type':'application/json'}
    if token:
        headers['Authorization'] = 'Bearer ' + token
    request = Request(BASE + path,None if data is None else json.dumps(data).encode(),headers,method=method)
    try:
        response = urlopen(request,timeout=30)
    except HTTPError as error:
        response = error
    body = response.read()
    payload = json.loads(body) if body else None
    assert response.status in expected, f'{method} {path}: HTTP {response.status}'
    return response.status,payload


def login(username,password):
    return api('POST','/auth/login/',{'username':username,'password':password})[1]['access']


def wait_job(path,job,token,timeout=180):
    deadline = time.monotonic()+timeout
    while job['status'] in ('queued','running') and time.monotonic()<deadline:
        time.sleep(.75)
        job = api('GET',path.format(id=job['id']),token=token)[1]
    assert job['status']=='completed', 'Asynchronous operation did not complete: ' + job.get('error_message','timeout')
    return job


def main():
    if os.environ.get('BENCHCODER_ALLOW_PROVIDER_CALLS') != '1':
        raise SystemExit('Set BENCHCODER_ALLOW_PROVIDER_CALLS=1 for this real billed-provider smoke.')
    username = os.environ['BENCHCODER_SOLUTION_USERNAME']
    token = login(username,os.environ['BENCHCODER_SOLUTION_PASSWORD'])
    config = api('GET','/solutions/config/',token=token)[1]
    assert config['enabled'], 'Solution provider is not configured.'
    query = urlencode({'search':'Add Two Integers','page_size':50})
    problems = api('GET','/problems/?'+query,token=token)[1]['results']
    target = next((problem for problem in problems if problem['title']=='Add Two Integers'),None)
    assert target, 'Seed the maintained practice catalog before this smoke.'
    payload = {'problem':target['id'],'code':'','language':'python'}
    first_status,job = api('POST','/solutions/',payload,token,expected=(200,202))
    job = wait_job('/solutions/{id}/',job,token)
    for field in ('explanation','solution_code','time_complexity','space_complexity'):
        assert isinstance(job.get(field),str) and job[field].strip(), f'Missing generated field: {field}'
    if 'verified' in job:
        assert job['verified'] is False, 'Generated solution must not claim automatic verification.'
    cached_status,cached = api('POST','/solutions/',payload,token,expected=(200,))
    assert cached_status==200 and cached['id']==job['id'] and cached['status']=='completed', 'Identical request did not reuse the completed cache.'
    print(f'Solution {job["id"]}: real structured response completed; repeated request returned the same cached job.',flush=True)

    admin_username = os.environ.get('BENCHCODER_ADMIN_USERNAME')
    admin_password = os.environ.get('BENCHCODER_ADMIN_PASSWORD')
    if admin_username and admin_password and admin_username != username:
        other_token = login(admin_username,admin_password)
        api('GET',f'/solutions/{job["id"]}/',token=other_token,expected=(404,))
        print('Owner-only solution access verified against the separate admin account.',flush=True)
    else:
        print('Separate-account ownership smoke skipped; provide optional admin credentials to include it.',flush=True)

    _,run = api('POST','/submissions/run/',{'problem':target['id'],'code':job['solution_code'],'language':'python'},token,expected=(202,))
    run = wait_job('/submissions/{id}/',run,token)
    assert run['kind']=='run' and run['verdict']=='AC', f'Generated code failed public samples: {run["verdict"]}'
    assert run['total_tests']>0 and run['passed_tests']==run['total_tests'], 'Not every available sample passed.'
    print(f'Generated Python code passed {run["passed_tests"]}/{run["total_tests"]} public samples through Celery/Docker. This does not verify hidden tests or award a solve.',flush=True)
    filtered = api('GET',f'/submissions/?problem={target["id"]}',token=token)[1]
    assert all(row['problem']==target['id'] and row['kind']=='submit' for row in filtered)
    assert all(row['id']!=run['id'] for row in filtered), 'Public sample run leaked into submission history.'
    print('PASS generated solution, owner-only access when configured, cache reuse, problem-specific history, and real Docker public-sample execution.',flush=True)


if __name__=='__main__':
    main()
