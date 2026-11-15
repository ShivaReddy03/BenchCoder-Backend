from datetime import timedelta
from django.conf import settings
from django.contrib.auth import get_user_model
from django.db import transaction
from django.shortcuts import get_object_or_404
from django.utils import timezone
from rest_framework.response import Response
from rest_framework.views import APIView
from .models import HintRequest, HintQuota
from .serializers import HintCreateSerializer, HintSerializer
from .retrieval import request_fingerprint
from .tasks import generate_request, recover_stale


def hints_configured():
    from .provider import is_configured
    backend = settings.AI_RETRIEVAL_BACKEND
    vector_ready = backend == 'local' or (
        backend == 'pinecone' and bool(settings.PINECONE_API_KEY.strip())
        and bool(settings.PINECONE_INDEX_HOST.strip())
    )
    return is_configured() and vector_ready


class HintConfigView(APIView):
    def get(self,request):
        from .provider import is_configured
        return Response({'enabled':hints_configured(),'retrieval_backend':settings.AI_RETRIEVAL_BACKEND,'hint_model':settings.AI_HINT_MODEL,'embedding_model':settings.PINECONE_EMBEDDING_MODEL if settings.AI_RETRIEVAL_BACKEND == 'pinecone' else settings.AI_EMBEDDING_MODEL,'daily_limit':settings.AI_HINTS_DAILY_LIMIT,'global_daily_limit':settings.AI_HINTS_GLOBAL_DAILY_LIMIT,'active_limit':1})


class HintCreateView(APIView):
    def post(self,request):
        from .provider import is_configured
        serializer = HintCreateSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        values = serializer.validated_data
        recover_stale()
        fingerprint = request_fingerprint(request.user.id,**values)
        now = timezone.now()
        # Consistent lock order: global admission row, then learner account.
        HintQuota.objects.get_or_create(name='global')
        with transaction.atomic():
            HintQuota.objects.select_for_update().get(name='global')
            get_user_model().objects.select_for_update().get(pk=request.user.id)
            cached = HintRequest.objects.filter(user=request.user,fingerprint=fingerprint,status='completed',created_at__gte=now-timedelta(hours=24)).order_by('-created_at').first()
            if cached:
                return Response(HintSerializer(cached).data)
            if not hints_configured():
                job = HintRequest.objects.create(user=request.user,fingerprint=fingerprint,status='failed',error_message='AI hints are not configured. Ask the administrator to configure the provider.',finished_at=now,**values)
                return Response(HintSerializer(job).data,status=503)
            if HintRequest.objects.filter(user=request.user,status__in=['queued','running']).exists():
                return Response({'detail':'A hint is already being generated. Wait for it to finish.'},status=429)
            today = now.replace(hour=0,minute=0,second=0,microsecond=0)
            # Failed attempts count too: retries cannot bypass cost controls.
            admitted = HintRequest.objects.filter(created_at__gte=today).exclude(error_message__startswith='AI hints are not configured')
            if admitted.filter(user=request.user).count() >= settings.AI_HINTS_DAILY_LIMIT or admitted.count() >= settings.AI_HINTS_GLOBAL_DAILY_LIMIT:
                return Response({'detail':'Daily hint limit reached. Try again tomorrow (UTC).'},status=429)
            job = HintRequest.objects.create(user=request.user,fingerprint=fingerprint,**values)
        try:
            generate_request.apply_async(args=[job.id],retry=False)
        except Exception:
            HintRequest.objects.filter(pk=job.id,status='queued').update(status='failed',error_message='Hint queue is unavailable. Please try again.',finished_at=timezone.now())
            job.refresh_from_db()
            return Response(HintSerializer(job).data,status=503)
        return Response(HintSerializer(job).data,status=202)


class HintDetailView(APIView):
    def get(self,request,request_id):
        recover_stale()
        job = get_object_or_404(HintRequest,id=request_id,user=request.user)
        return Response(HintSerializer(job).data)
