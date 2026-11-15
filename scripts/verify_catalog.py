"""Verify the maintained catalog using trusted fixtures and real asynchronous judging.

Host fixture check (requires Python + Node):
    python scripts/verify_catalog.py --fixtures-only
Container verification after database migration/seeding and worker readiness:
    python scripts/verify_catalog.py --skip-fixtures

Only repository-authored reference solutions execute in the optional host checks.
The real verification path always uses Celery and the Docker-only judge. It creates
one disposable non-admin user; it deletes only that user after all its jobs finish.
No demo learner history or unrelated records are modified.
"""
import argparse
import os
import re
from pathlib import Path
import secrets
import shutil
import subprocess
import sys
import time
import uuid

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'BenchCoder.settings')
import django
django.setup()


def load_catalog():
    from problems.catalog import CATALOG
    return CATALOG


def verify_fixtures(catalog, languages):
    commands = {'python': [sys.executable, '-I', '-c']}
    if 'javascript' in languages:
        node = shutil.which('node')
        if not node:
            raise RuntimeError('Node.js is required for trusted JavaScript fixture checks. Run --fixtures-only on the host, then --skip-fixtures in the web container.')
        commands['javascript'] = [node, '-e']
    count = 0
    child_env = {key: value for key, value in os.environ.items() if key in ('PATH', 'Path', 'SYSTEMROOT', 'SystemRoot', 'WINDIR', 'TEMP', 'TMP')}
    child_env['PYTHONIOENCODING'] = 'utf-8'
    for entry in catalog:
        for language in languages:
            code = entry[language]
            for case_number, (input_data, expected) in enumerate(entry['cases'], start=1):
                result = subprocess.run(commands[language] + [code], input=input_data, text=True, encoding='utf-8', capture_output=True, timeout=5, env=child_env)
                if result.returncode or result.stdout.strip() != expected.strip():
                    raise AssertionError(f'Trusted fixture failed: {entry["title"]}, {language}, case {case_number}: {result.stderr[:300]}')
                count += 1
    print(f'Trusted reference fixture checks passed: {count}', flush=True)


def database_read(operation):
    """Mirror request boundaries and reconnect once after transient database loss."""
    from django.db import close_old_connections, connections, OperationalError, InterfaceError
    for attempt in range(2):
        close_old_connections()
        try:
            return operation()
        except (OperationalError, InterfaceError):
            connections.close_all()
            if attempt:
                raise
            time.sleep(.5)


def verify_async(catalog, languages, timeout, resume_user=None):
    from django.contrib.auth import get_user_model
    from problems.models import Problem
    from submissions.models import Submission
    from submissions.views import SubmissionCreateView
    from rest_framework.test import APIRequestFactory, force_authenticate
    from django.db import close_old_connections, connections, OperationalError
    from judge.tasks import judge_submission
    from django.utils import timezone
    from datetime import timedelta

    # Confirm every database fixture matches the maintained catalog before creating jobs.
    problems = {}
    for entry in catalog:
        matches = database_read(lambda: list(Problem.objects.filter(title=entry['title'])))
        if len(matches) != 1:
            raise AssertionError(f'Expected exactly one seeded catalog problem named {entry["title"]!r}; found {len(matches)}.')
        problem = matches[0]
        if problem.description != entry['description']:
            raise AssertionError(f'Database statement differs from maintained catalog for {entry["title"]}. Run the catalog seed first.')
        expected_cases = list(entry['cases'])
        actual_cases = database_read(lambda: list(problem.test_cases.order_by('id').values_list('input', 'expected_output')))
        if actual_cases != expected_cases:
            raise AssertionError(f'Database test cases differ from maintained catalog for {entry["title"]}. Run the catalog seed first.')
        problems[entry['title']] = problem

    if resume_user:
        if not re.fullmatch(r'catalog_verify_[0-9a-f]{20}',resume_user):
            raise ValueError('Resume is restricted to a generated catalog verification username.')
        username = resume_user
        user = database_read(lambda: get_user_model().objects.get(username=username,is_staff=False,is_superuser=False))
    else:
        username = 'catalog_verify_' + uuid.uuid4().hex[:20]
        close_old_connections()
        user = get_user_model().objects.create_user(username=username, password=secrets.token_urlsafe(40), email='')
    user_id = user.id
    if resume_user:
        # Use the product's ten-minute stale policy, restricted to this owned verifier.
        cutoff = timezone.now() - timedelta(minutes=10)
        close_old_connections()
        Submission.objects.filter(user_id=user_id,status='running',started_at__lt=cutoff).update(status='failed',verdict='OT',error_message='Previous verification worker did not finish.',finished_at=timezone.now())
        Submission.objects.filter(user_id=user_id,status='queued',submitted_at__lt=cutoff).update(status='failed',verdict='OT',error_message='Previous verification job did not start.',finished_at=timezone.now())
    factory = APIRequestFactory()
    job_info = {}
    deadline = time.monotonic() + timeout
    completed = set()
    last_progress = 0.0
    try:
        for entry in catalog:
            for language in languages:
                payload = {'problem': problems[entry['title']].id, 'code': entry[language], 'language': language}
                # Resume only this exact maintained reference, never arbitrary or unrelated jobs.
                def find_reusable():
                    owned = Submission.objects.filter(user_id=user_id,problem_id=payload['problem'],language=language,code=payload['code'],kind='submit')
                    accepted = owned.filter(status='completed',verdict='AC',passed_tests=len(entry['cases']),total_tests=len(entry['cases'])).order_by('-id').first()
                    return accepted or owned.filter(status__in=('queued','running')).order_by('-id').first()
                reusable = database_read(find_reusable) if resume_user else None
                if reusable:
                    job_info[reusable.id] = (entry['title'],language,len(entry['cases']))
                    continue
                response = None
                existing = None
                for attempt in range(2):
                    # APIRequestFactory bypasses Django's request-start connection signal.
                    close_old_connections()
                    request = factory.post('/api/submissions/create/', payload, format='json')
                    force_authenticate(request, user=user)
                    try:
                        response = SubmissionCreateView.as_view()(request)
                        break
                    except OperationalError:
                        connections.close_all()
                        # A lost response can follow a committed INSERT or dispatched task.
                        # Recover that exact owned record; never create a duplicate submission.
                        existing = database_read(lambda: Submission.objects.filter(
                            user_id=user_id, problem_id=payload['problem'], language=language,
                            code=payload['code'], kind='submit',
                        ).order_by('-id').first())
                        if existing:
                            if existing.status == 'queued':
                                # Enqueue may have been interrupted; atomic worker claims make redelivery safe.
                                judge_submission.apply_async(args=[existing.id], retry=False)
                            break
                        if attempt:
                            raise
                        time.sleep(.5)
                    finally:
                        connections.close_all()
                if existing:
                    submission_id = existing.id
                else:
                    if response.status_code != 202:
                        raise AssertionError(f'Queue rejected {entry["title"]}/{language}: HTTP {response.status_code}. Check worker/broker configuration.')
                    submission_id = response.data['id']
                job_info[submission_id] = (entry['title'], language, len(entry['cases']))
        print(f'Tracking {len(job_info)} real Docker evaluations under disposable verifier {username} (accepted or active matching jobs reused on resume).', flush=True)
        failures = []
        while len(completed) < len(job_info):
            results = database_read(lambda: list(Submission.objects.filter(user_id=user_id, id__in=job_info).exclude(id__in=completed)))
            for result in results:
                if result.status not in ('completed', 'failed'):
                    continue
                title, language, expected_count = job_info[result.id]
                completed.add(result.id)
                print(f'{language:10} {result.verdict:3} {result.passed_tests}/{result.total_tests} {title}', flush=True)
                if result.status != 'completed' or result.verdict != 'AC' or result.passed_tests != expected_count or result.total_tests != expected_count:
                    failures.append(f'{title}/{language}: {result.status} {result.verdict} ({result.error_message[:200]})')
            if len(completed) == len(job_info):
                break
            now = time.monotonic()
            if now >= deadline:
                raise TimeoutError(f'Catalog evaluations exceeded {timeout}s; completed {len(completed)}/{len(job_info)}. Remaining jobs retain their verifier account for safe follow-up.')
            if now - last_progress >= 20:
                print(f'Evaluation progress: {len(completed)}/{len(job_info)} terminal jobs.', flush=True)
                last_progress = now
            time.sleep(1)
        if failures:
            raise AssertionError('Catalog verification failures:\n' + '\n'.join(failures))
        print(f'All {len(job_info)} catalog evaluations accepted through Celery/Docker.', flush=True)
    finally:
        connections.close_all()
        try:
            active = database_read(lambda: Submission.objects.filter(user_id=user_id,status__in=('queued','running')).exists())
            if active:
                print(f'Cleanup deferred: active jobs still belong to disposable verifier {username} (user ID {user_id}). No unrelated accounts were touched.', flush=True)
            else:
                # Guard both identity components: never delete a preexisting or unrelated user.
                close_old_connections()
                get_user_model().objects.filter(pk=user_id, username=username).delete()
                print('Removed disposable verifier and its completed verification records.', flush=True)
        except Exception as cleanup_error:
            # Cleanup must not mask the original evaluation failure or delete active records.
            connections.close_all()
            print(f'Cleanup deferred after {type(cleanup_error).__name__}: disposable verifier {username} (user ID {user_id}) remains for follow-up.',flush=True)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    mode = parser.add_mutually_exclusive_group()
    mode.add_argument('--fixtures-only', action='store_true')
    mode.add_argument('--skip-fixtures', action='store_true')
    parser.add_argument('--languages', choices=('both', 'python', 'javascript'), default='both')
    parser.add_argument('--timeout', type=int, default=600)
    parser.add_argument('--resume-user', help='Resume a generated catalog_verify_<20 hex characters> account; reuse accepted or active reference jobs.')
    args = parser.parse_args()
    if args.timeout <= 0 or args.timeout > 1800:
        parser.error('--timeout must be between 1 and 1800 seconds')
    catalog = load_catalog()
    if len(catalog) != 15:
        raise AssertionError(f'Expected the maintained 15-problem catalog; found {len(catalog)}.')
    languages = ['python', 'javascript'] if args.languages == 'both' else [args.languages]
    if not args.skip_fixtures:
        verify_fixtures(catalog, languages)
    if not args.fixtures_only:
        verify_async(catalog, languages, args.timeout, args.resume_user)


if __name__ == '__main__':
    main()
