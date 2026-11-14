from datetime import timedelta
import time
from celery import shared_task
from django.db import transaction
from django.db.models import F
from django.utils import timezone
from submissions.models import Submission, ProblemSolve
from .runner import execute, InfrastructureError


def finish(submission_id, attempt, values):
    with transaction.atomic():
        sub = Submission.objects.select_for_update().select_related('problem').get(pk=submission_id)
        if sub.status != 'running' or sub.attempt != attempt:
            return
        for field, value in values.items():
            setattr(sub, field, value)
        sub.finished_at = timezone.now()
        sub.save()
        if sub.kind == 'submit' and sub.verdict == 'AC':
            _, created = ProblemSolve.objects.get_or_create(user_id=sub.user_id, problem_id=sub.problem_id)
            if created:
                type(sub.user).objects.filter(pk=sub.user_id).update(score=F('score') + sub.problem.points, problems_solved=F('problems_solved') + 1)


@shared_task(bind=True, max_retries=2, acks_late=True, reject_on_worker_lost=True)
def judge_submission(self, submission_id):
    # Compare-and-set: duplicate deliveries cannot concurrently claim the same job.
    claimed = Submission.objects.filter(pk=submission_id, status='queued').update(status='running', started_at=timezone.now(), attempt=F('attempt') + 1)
    if not claimed:
        return
    sub = Submission.objects.select_related('problem').get(pk=submission_id)
    attempt = sub.attempt
    cases = sub.problem.test_cases.order_by('id')
    if sub.kind == 'run':
        cases = cases.filter(is_public=True)[:3]
    cases = list(cases)
    if not cases:
        finish(sub.id, attempt, {'status': 'failed', 'verdict': 'OT', 'error_message': 'No test cases are configured for this operation.'})
        return
    passed, elapsed, memory = 0, 0.0, None
    sample_results = []
    verdict, message = 'AC', ''
    try:
        deadline = time.monotonic() + 120
        public_ids = set(sub.problem.test_cases.filter(is_public=True).order_by('id').values_list('id', flat=True)[:3])
        for case in cases:
            if time.monotonic() >= deadline:
                verdict, message = 'TLE', 'Total execution time limit exceeded.'
                break
            result = execute(sub.code, sub.language, case.input)
            elapsed += result['time']
            if result['memory'] is not None:
                memory = max(memory or 0, result['memory'])
            case_verdict = result['verdict']
            if case_verdict == 'AC' and result['output'].strip() != case.expected_output.strip():
                case_verdict = 'WA'
            if case_verdict == 'AC':
                passed += 1
            elif verdict == 'AC':
                verdict = case_verdict
                message = result['error'] if case.id in public_ids or case_verdict == 'CE' else 'Execution failed on a private test case.'
            if case.id in public_ids:
                sample_results.append({'testcase_id': case.id, 'input': case.input, 'expected': case.expected_output, 'output': result['output'], 'passed': case_verdict == 'AC', 'verdict': case_verdict})
        finish(sub.id, attempt, {'status': 'completed', 'verdict': verdict, 'passed_tests': passed, 'total_tests': len(cases), 'execution_time': elapsed, 'memory_used': memory, 'error_message': message, 'sample_results': sample_results})
    except InfrastructureError:
        if self.request.retries < self.max_retries:
            Submission.objects.filter(pk=sub.id, status='running', attempt=attempt).update(status='queued', started_at=None)
            raise self.retry(countdown=5)
        finish(sub.id, attempt, {'status': 'failed', 'verdict': 'OT', 'error_message': 'Execution service unavailable after retries.', 'total_tests': len(cases)})
    except Exception:
        finish(sub.id, attempt, {'status': 'failed', 'verdict': 'OT', 'error_message': 'Execution worker failed. Please try again.', 'total_tests': len(cases)})
        raise


def recover_stale_submissions():
    # Called when reading results: jobs abandoned by terminated workers become truthful failures.
    cutoff = timezone.now() - timedelta(minutes=10)
    Submission.objects.filter(status='running', started_at__lt=cutoff).update(status='failed', verdict='OT', error_message='Execution worker stopped before completing this job. Please resubmit.', finished_at=timezone.now())
    Submission.objects.filter(status='queued', submitted_at__lt=cutoff).update(status='failed', verdict='OT', error_message='Execution did not start. Please check worker availability and resubmit.', finished_at=timezone.now())
