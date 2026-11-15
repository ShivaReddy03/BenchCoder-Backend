from datetime import timedelta
from celery import shared_task
from django.utils import timezone
from .models import HintRequest, ProblemKnowledge
from .retrieval import retrieve, request_fingerprint
from .db_lifecycle import release_connections, database_retry


def update_running(request_id, **values):
    return database_retry(lambda: HintRequest.objects.filter(pk=request_id, status='running').update(**values))


def recover_stale():
    cutoff = timezone.now()-timedelta(minutes=3)
    HintRequest.objects.filter(status__in=['queued','running'], created_at__lt=cutoff).update(status='failed', error_message='Hint request timed out. Please try again.', finished_at=timezone.now())


@shared_task(bind=True, max_retries=1, soft_time_limit=90, time_limit=100)
def generate_request(self, request_id):
    from .provider import generate_hint, ProviderError
    if not HintRequest.objects.filter(pk=request_id,status='queued').update(status='running',started_at=timezone.now()):
        return
    request = HintRequest.objects.select_related('problem').get(pk=request_id)
    try:
        # Changes between enqueue and execution invalidate the request instead of serving stale context.
        if request.fingerprint != request_fingerprint(request.user_id,request.problem,request.level,request.code,request.language):
            update_running(request.id,status='failed',error_message='Problem or learning history changed. Request a new hint.',finished_at=timezone.now())
            return
        sources = retrieve(request.user_id,request.problem)
        knowledge = ProblemKnowledge.objects.filter(problem=request.problem).first()
        context = {
            'level':request.level, 'language':request.language, 'code':request.code,
            'problem': {'id':request.problem_id,'title':request.problem.title,'description':request.problem.description,'concepts':knowledge.concepts if knowledge else [],'examples':list(request.problem.test_cases.filter(is_public=True).order_by('id').values('input','expected_output')[:3])},
            'solved_sources': sources,
        }
        release_connections()
        hint = generate_hint(context)
        if not isinstance(hint,str) or not hint.strip():
            raise ProviderError('The provider returned an empty hint.',retryable=False)
        # Retry persistence independently of paid generation; refresh privacy state
        # on each SQL attempt so a stale cloud socket never repeats the model call.
        snapshots = [{key:value for key,value in source.items() if key != 'approach_summary'} for source in sources]
        def persist_generated_hint():
            request.problem.refresh_from_db()
            if request.fingerprint != request_fingerprint(request.user_id,request.problem,request.level,request.code,request.language):
                raise ProviderError('Problem or learning history changed. Request a new hint.',retryable=False)
            return HintRequest.objects.filter(pk=request.id,status='running').update(status='completed',hint=hint,retrieved_sources=snapshots,finished_at=timezone.now())
        release_connections()
        database_retry(persist_generated_hint)
    except ProviderError as exc:
        if exc.retryable and self.request.retries < self.max_retries:
            update_running(request.id,status='queued',started_at=None)
            raise self.retry(countdown=5)
        release_connections()
        update_running(request.id,status='failed',error_message=exc.safe_message,finished_at=timezone.now())
    except Exception:
        release_connections()
        update_running(request.id,status='failed',error_message='Hint service failed. Please try again.',finished_at=timezone.now())
