from django.conf import settings
from django.contrib.auth import get_user_model
from django.db import transaction
from django.shortcuts import get_object_or_404
from django.utils import timezone
from rest_framework.views import APIView
from rest_framework.response import Response
from hints.provider import is_configured
from hints.db_lifecycle import release_connections, database_retry
from .models import SolutionRequest, SolutionQuota
from .context import request_fingerprint
from .serializers import SolutionCreateSerializer, SolutionSerializer
from .tasks import generate_request, recover_stale


class SolutionConfigView(APIView):
    def get(self, request):
        return Response({'enabled': is_configured(), 'model': settings.AI_SOLUTION_MODEL,
                         'daily_limit': settings.AI_SOLUTIONS_DAILY_LIMIT,
                         'global_daily_limit': settings.AI_SOLUTIONS_GLOBAL_DAILY_LIMIT, 'active_limit': 1})


class SolutionCreateView(APIView):
    def post(self, request):
        serializer = SolutionCreateSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        values = serializer.validated_data
        recover_stale()
        fingerprint = request_fingerprint(request.user.id, **values)
        now = timezone.now()
        SolutionQuota.objects.get_or_create(name='global')
        with transaction.atomic():
            SolutionQuota.objects.select_for_update().get(name='global')
            get_user_model().objects.select_for_update().get(pk=request.user.id)
            cached = SolutionRequest.objects.filter(user=request.user, fingerprint=fingerprint, status='completed').order_by('-id').first()
            if cached:
                return Response(SolutionSerializer(cached).data)
            identical = SolutionRequest.objects.filter(user=request.user, fingerprint=fingerprint, status__in=['queued', 'running']).order_by('-id').first()
            if identical:
                return Response(SolutionSerializer(identical).data, status=202)
            if not is_configured():
                job = SolutionRequest.objects.create(user=request.user, fingerprint=fingerprint, status='failed',
                    error_message='AI solutions are not configured. Ask the administrator to configure the provider.', finished_at=now, **values)
                return Response(SolutionSerializer(job).data, status=503)
            if SolutionRequest.objects.filter(user=request.user, status__in=['queued', 'running']).exists():
                return Response({'detail': 'A solution is already being generated. Wait for it to finish.'}, status=429)
            today = now.replace(hour=0, minute=0, second=0, microsecond=0)
            admitted = SolutionRequest.objects.filter(created_at__gte=today).exclude(error_message__startswith='AI solutions are not configured')
            if admitted.filter(user=request.user).count() >= settings.AI_SOLUTIONS_DAILY_LIMIT or admitted.count() >= settings.AI_SOLUTIONS_GLOBAL_DAILY_LIMIT:
                return Response({'detail': 'Daily solution limit reached. Try again tomorrow (UTC).'}, status=429)
            job = SolutionRequest.objects.create(user=request.user, fingerprint=fingerprint, **values)
        try:
            generate_request.apply_async(args=[job.id], retry=False)
        except Exception:
            release_connections()
            database_retry(lambda: SolutionRequest.objects.filter(pk=job.id, status='queued').update(status='failed', error_message='Solution queue is unavailable. Please try again.', finished_at=timezone.now()))
            job.refresh_from_db()
            return Response(SolutionSerializer(job).data, status=503)
        return Response(SolutionSerializer(job).data, status=202)


class SolutionDetailView(APIView):
    def get(self, request, request_id):
        recover_stale()
        job = get_object_or_404(SolutionRequest, id=request_id, user=request.user)
        return Response(SolutionSerializer(job).data)
