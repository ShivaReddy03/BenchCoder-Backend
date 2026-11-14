from django.urls import reverse
from rest_framework.test import APITestCase
from rest_framework import status
from django.contrib.auth import get_user_model  
from .models import Problem, TestCase

# Use get_user_model to avoid import issues
User = get_user_model()

class ProblemTests(APITestCase):
    def setUp(self):
        # Create a regular user and an admin user
        self.user = User.objects.create_user(username='testuser', password='testpass123')
        self.admin_user = User.objects.create_superuser(username='admin', password='adminpass123')
        
        # Create a sample problem
        self.problem = Problem.objects.create(
            title="Test Problem",
            description="Test Description",
            difficulty="easy",
            points=10
        )
        
        # URLs
        self.problem_list_url = reverse('problem-list')
        self.problem_detail_url = reverse('problem-detail', kwargs={'problem_id': self.problem.id})
        
    def test_get_problems_authenticated(self):
        # Login as regular user
        self.client.force_authenticate(user=self.user)
        
        response = self.client.get(self.problem_list_url)
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        
    def test_get_problems_unauthenticated(self):
        response = self.client.get(self.problem_list_url)
        self.assertEqual(response.status_code, status.HTTP_401_UNAUTHORIZED)
        
    def test_get_problem_detail(self):
        self.client.force_authenticate(user=self.user)
        
        response = self.client.get(self.problem_detail_url)
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response.data['title'], self.problem.title)
        
    def test_create_problem_as_admin(self):
        self.client.force_authenticate(user=self.admin_user)
        
        data = {
            "title": "New Problem",
            "description": "New Problem Description",
            "difficulty": "medium",
            "points": 15
        }
        
        response = self.client.post(reverse('problem-create'), data)
        self.assertEqual(response.status_code, status.HTTP_201_CREATED)
        self.assertEqual(Problem.objects.count(), 2)  # Should have 2 problems now
        
    def test_create_problem_as_regular_user(self):
        self.client.force_authenticate(user=self.user)
        
        data = {
            "title": "New Problem",
            "description": "New Problem Description",
            "difficulty": "medium",
            "points": 15
        }
        
        response = self.client.post(reverse('problem-create'), data)
        self.assertEqual(response.status_code, status.HTTP_403_FORBIDDEN)
    def test_detail_only_exposes_first_three_public_cases(self):
        TestCase.objects.create(problem=self.problem, input='secret-input', expected_output='secret-answer')
        public = [TestCase.objects.create(problem=self.problem, input=str(i), expected_output=str(i), is_public=True) for i in range(4)]
        self.client.force_authenticate(user=self.user)
        response = self.client.get(self.problem_detail_url)
        self.assertNotIn('test_cases', response.data)
        self.assertEqual([case['id'] for case in response.data['sample_test_cases']], [case.id for case in public[:3]])
        self.assertNotIn('secret-input', str(response.data))
        self.client.force_authenticate(user=self.admin_user)
        self.assertEqual(len(self.client.get(self.problem_detail_url).data['test_cases']), 5)

    def test_admin_problem_update_and_delete(self):
        self.client.force_authenticate(user=self.user)
        self.assertEqual(self.client.patch(self.problem_detail_url, {'title': 'Blocked'}).status_code, 403)
        self.assertEqual(self.client.delete(self.problem_detail_url).status_code, 403)
        self.client.force_authenticate(user=self.admin_user)
        self.assertEqual(self.client.patch(self.problem_detail_url, {'title': 'Updated'}).status_code, 200)
        self.problem.refresh_from_db()
        self.assertEqual(self.problem.title, 'Updated')
        self.assertEqual(self.client.delete(self.problem_detail_url).status_code, 204)
        self.assertFalse(Problem.objects.filter(id=self.problem.id).exists())

    def test_testcase_crud_permissions_and_nested_scope(self):
        other = Problem.objects.create(title='Other', description='Other', difficulty='easy')
        url = reverse('testcase-create', kwargs={'problem_id': self.problem.id})
        self.client.force_authenticate(user=self.user)
        self.assertEqual(self.client.get(url).status_code, 403)
        self.assertEqual(self.client.post(url, {'input': '', 'expected_output': ''}).status_code, 403)
        self.client.force_authenticate(user=self.admin_user)
        response = self.client.post(url, {'problem': other.id, 'input': '', 'expected_output': '', 'is_public': False})
        self.assertEqual(response.status_code, 201)
        case = TestCase.objects.get(id=response.data['id'])
        self.assertEqual(case.problem_id, self.problem.id)
        detail = reverse('testcase-detail', kwargs={'problem_id': self.problem.id, 'case_id': case.id})
        wrong = reverse('testcase-detail', kwargs={'problem_id': other.id, 'case_id': case.id})
        self.assertEqual(self.client.patch(wrong, {'input': 'bad'}).status_code, 404)
        self.assertEqual(self.client.delete(wrong).status_code, 404)
        self.assertEqual(self.client.patch(detail, {'problem': other.id, 'input': 'updated'}).status_code, 200)
        case.refresh_from_db()
        self.assertEqual(case.problem_id, self.problem.id)
        self.assertEqual(self.client.get(url).data[0]['input'], 'updated')
        self.client.force_authenticate(user=self.user)
        self.assertEqual(self.client.patch(detail, {'input': 'blocked'}).status_code, 403)
        self.assertEqual(self.client.delete(detail).status_code, 403)
        self.client.force_authenticate(user=self.admin_user)
        self.assertEqual(self.client.delete(detail).status_code, 204)

    def test_pagination_and_filters(self):
        for i in range(4):
            Problem.objects.create(title=f'Matching {i}', description='description', difficulty='hard')
        self.client.force_authenticate(user=self.user)
        response = self.client.get(self.problem_list_url, {'page_size': 2, 'page': 2, 'difficulty': 'hard', 'search': 'Matching'})
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.data['total_count'], 4)
        self.assertEqual(response.data['page_size'], 2)
        self.assertEqual([p['title'] for p in response.data['results']], ['Matching 2', 'Matching 3'])
