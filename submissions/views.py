from django.shortcuts import get_object_or_404
from django.utils import timezone
from rest_framework import permissions, status
from rest_framework.response import Response
from rest_framework.views import APIView
from judge.tasks import judge_submission, recover_stale_submissions
from .models import Submission
from .serializers import SubmissionSerializer, SubmissionCreateSerializer, SubmissionListSerializer


class SubmissionListView(APIView):
    permission_classes = [permissions.IsAuthenticated]

    def get(self, request):
        problem_id = request.query_params.get('problem')
        if problem_id is not None:
            try:
                problem_id = int(problem_id)
                if problem_id <= 0 or problem_id > 9223372036854775807:
                    raise ValueError
            except (TypeError, ValueError):
                return Response({'detail': "'problem' must be a positive integer."}, status=status.HTTP_400_BAD_REQUEST)
        recover_stale_submissions()
        submissions = Submission.objects.filter(user=request.user, kind='submit').select_related('problem', 'user').order_by('-submitted_at')
        if problem_id is not None:
            submissions = submissions.filter(problem_id=problem_id)
        return Response(SubmissionListSerializer(submissions, many=True).data)


class SubmissionDetailView(APIView):
    permission_classes = [permissions.IsAuthenticated]

    def get(self, request, submission_id):
        recover_stale_submissions()
        submission = get_object_or_404(Submission.objects.select_related('problem', 'user'), id=submission_id, user=request.user)
        return Response(SubmissionSerializer(submission).data)


class SubmissionCreateView(APIView):
    permission_classes = [permissions.IsAuthenticated]
    kind = 'submit'

    def post(self, request):
        serializer = SubmissionCreateSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        problem = serializer.validated_data['problem']
        cases = problem.test_cases.all()
        if self.kind == 'run':
            cases = cases.filter(is_public=True)
        if not cases.exists():
            return Response({'detail': 'No test cases are configured for this operation.'}, status=status.HTTP_400_BAD_REQUEST)
        submission = serializer.save(user=request.user, kind=self.kind)
        try:
            judge_submission.apply_async(args=[submission.id], retry=False)
        except Exception:
            # Never execute user code inside the HTTP request or fabricate success.
            Submission.objects.filter(pk=submission.id, status='queued').update(status='failed', verdict='OT', error_message='Execution queue is unavailable. Please try again.', finished_at=timezone.now())
            submission.refresh_from_db()
            return Response(SubmissionSerializer(submission).data, status=status.HTTP_503_SERVICE_UNAVAILABLE)
        return Response(SubmissionSerializer(submission).data, status=status.HTTP_202_ACCEPTED)


class SubmissionRunView(SubmissionCreateView):
    kind = 'run'
