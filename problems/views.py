from rest_framework import status, permissions
from rest_framework.response import Response
from rest_framework.views import APIView
from django.shortcuts import get_object_or_404
from .models import Problem, TestCase
from .serializers import ProblemSerializer, ProblemListSerializer, TestCaseSerializer
from utils.pagination import CustomPagination


class ProblemListView(APIView):
    permission_classes = [permissions.IsAuthenticated]

    def get(self, request):
        problems = Problem.objects.all().order_by('id')
        search = request.query_params.get('search', '').strip()
        difficulty = request.query_params.get('difficulty', '')
        if search:
            problems = problems.filter(title__icontains=search)
        if difficulty:
            problems = problems.filter(difficulty=difficulty)
        paginator = CustomPagination()
        page = paginator.paginate_queryset(problems, request)
        return paginator.get_paginated_response(ProblemListSerializer(page, many=True).data)


class ProblemDetailView(APIView):
    def get_permissions(self):
        permission = permissions.IsAuthenticated if self.request.method == 'GET' else permissions.IsAdminUser
        return [permission()]

    def get(self, request, problem_id):
        problem = get_object_or_404(Problem, id=problem_id)
        return Response(ProblemSerializer(problem, context={'request': request}).data)

    def patch(self, request, problem_id):
        problem = get_object_or_404(Problem, id=problem_id)
        serializer = ProblemSerializer(problem, data=request.data, partial=True, context={'request': request})
        serializer.is_valid(raise_exception=True)
        serializer.save()
        return Response(serializer.data)

    def delete(self, request, problem_id):
        get_object_or_404(Problem, id=problem_id).delete()
        return Response(status=status.HTTP_204_NO_CONTENT)


class ProblemCreateView(APIView):
    permission_classes = [permissions.IsAdminUser]

    def post(self, request):
        serializer = ProblemSerializer(data=request.data, context={'request': request})
        serializer.is_valid(raise_exception=True)
        serializer.save()
        return Response(serializer.data, status=status.HTTP_201_CREATED)


class TestCaseCreateView(APIView):
    permission_classes = [permissions.IsAdminUser]

    def get(self, request, problem_id):
        problem = get_object_or_404(Problem, id=problem_id)
        return Response(TestCaseSerializer(problem.test_cases.order_by('id'), many=True).data)

    def post(self, request, problem_id):
        problem = get_object_or_404(Problem, id=problem_id)
        serializer = TestCaseSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        serializer.save(problem=problem)
        return Response(serializer.data, status=status.HTTP_201_CREATED)


class TestCaseDetailView(APIView):
    permission_classes = [permissions.IsAdminUser]

    def patch(self, request, problem_id, case_id):
        case = get_object_or_404(TestCase, id=case_id, problem_id=problem_id)
        serializer = TestCaseSerializer(case, data=request.data, partial=True)
        serializer.is_valid(raise_exception=True)
        serializer.save()
        return Response(serializer.data)

    def delete(self, request, problem_id, case_id):
        get_object_or_404(TestCase, id=case_id, problem_id=problem_id).delete()
        return Response(status=status.HTTP_204_NO_CONTENT)
