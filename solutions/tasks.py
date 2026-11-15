from datetime import timedelta
from celery import shared_task
from django.utils import timezone
from hints.db_lifecycle import release_connections, database_retry
from hints.provider import ProviderError
from .context import request_fingerprint, public_context
from .models import SolutionRequest


def update_running(request_id, **values):
    return database_retry(lambda: SolutionRequest.objects.filter(pk=request_id, status='running').update(**values))


def recover_stale():
    cutoff = timezone.now() - timedelta(minutes=5)
    SolutionRequest.objects.filter(status__in=['queued', 'running'], created_at__lt=cutoff).update(
        status='failed', error_message='Solution request timed out. Please try again.', finished_at=timezone.now())


@shared_task(max_retries=0, soft_time_limit=110, time_limit=120)
def generate_request(request_id):
    from .provider import generate_solution
    try:
        if not database_retry(lambda: SolutionRequest.objects.filter(pk=request_id, status='queued').update(status='running', started_at=timezone.now())):
            return
        job = database_retry(lambda: SolutionRequest.objects.select_related('problem').get(pk=request_id))
        if job.fingerprint != request_fingerprint(job.user_id, job.problem, job.code, job.language):
            raise ProviderError('Problem changed. Request a new solution.')
        context = {'problem': public_context(job.problem), 'code': job.code, 'language': job.language}
        release_connections()
        values = generate_solution(context)
        # Retry SQL alone after paid generation; never repeat a provider request to
        # recover an expired database socket. Recheck problem privacy/version first.
        def persist():
            job.problem.refresh_from_db()
            if job.fingerprint != request_fingerprint(job.user_id, job.problem, job.code, job.language):
                raise ProviderError('Problem changed during generation. Request a new solution.')
            return SolutionRequest.objects.filter(pk=job.id, status='running').update(status='completed', finished_at=timezone.now(), **values)
        release_connections()
        database_retry(persist)
    except ProviderError as exc:
        release_connections()
        update_running(request_id, status='failed', error_message=exc.safe_message, finished_at=timezone.now())
    except Exception:
        release_connections()
        update_running(request_id, status='failed', error_message='Solution service failed. Please try again.', finished_at=timezone.now())
