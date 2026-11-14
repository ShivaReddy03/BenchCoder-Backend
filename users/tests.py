from django.urls import reverse
from rest_framework.test import APITestCase
from rest_framework import status
from .models import User

class UserAuthenticationTests(APITestCase):
    def setUp(self):
        self.register_url = reverse('register')
        self.login_url = reverse('login')
        self.profile_url = reverse('profile')
        
    def test_user_registration(self):
        data = {
            'username': 'testuser',
            'email': 'test@example.com',
            'password': 'testpass123',
            'password2': 'testpass123'
        }
        response = self.client.post(self.register_url, data, format='json')
        self.assertEqual(response.status_code, status.HTTP_201_CREATED)
        self.assertTrue('access' in response.data)
        self.assertNotIn('refresh', response.data)
        
    def test_user_login(self):
        # First create a user
        User.objects.create_user(username='testuser', password='testpass123')
        
        # Then try to login
        data = {
            'username': 'testuser',
            'password': 'testpass123'
        }
        response = self.client.post(self.login_url, data, format='json')
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertTrue('access' in response.data)
        self.assertNotIn('refresh', response.data)
    def test_token_lifetime_and_expiration(self):
        from datetime import timedelta
        from rest_framework_simplejwt.tokens import AccessToken
        user = User.objects.create_user(username='tokenuser', password='strong-secret-284')
        token = AccessToken.for_user(user)
        self.assertEqual(token['exp'] - token['iat'], 7 * 24 * 60 * 60)
        self.client.credentials(HTTP_AUTHORIZATION=f'Bearer {token}')
        self.assertEqual(self.client.get(self.profile_url).status_code, 200)
        token.set_exp(lifetime=timedelta(seconds=-1))
        self.client.credentials(HTTP_AUTHORIZATION=f'Bearer {token}')
        self.assertEqual(self.client.get(self.profile_url).status_code, 401)

    def test_refresh_endpoint_removed(self):
        self.assertEqual(self.client.post('/api/auth/token/refresh/', {}).status_code, 404)

    def test_weak_password_rejected(self):
        response = self.client.post(self.register_url, {
            'username': 'weakuser', 'email': 'weak@example.com', 'password': '12345678'
        })
        self.assertEqual(response.status_code, 400)
        self.assertIn('password', response.data)
        self.assertFalse(User.objects.filter(username='weakuser').exists())

    def test_registration_cannot_grant_staff_privileges(self):
        response = self.client.post(self.register_url, {
            'username': 'newmember', 'email': 'member@example.com',
            'password': 'Unique-secret-8735', 'is_staff': True, 'is_superuser': True,
        })
        self.assertEqual(response.status_code, 201)
        self.assertFalse(response.data['user']['is_staff'])
        self.assertFalse(User.objects.get(username='newmember').is_superuser)

    def test_inactive_user_token_is_rejected(self):
        from rest_framework_simplejwt.tokens import AccessToken
        user = User.objects.create_user(username='inactive', password='strong-secret-284')
        token = AccessToken.for_user(user)
        user.is_active = False
        user.save(update_fields=['is_active'])
        self.client.credentials(HTTP_AUTHORIZATION=f'Bearer {token}')
        self.assertEqual(self.client.get(self.profile_url).status_code, 401)

    def test_profile_uses_current_solve_ledger_after_admin_changes(self):
        from problems.models import Problem
        from submissions.models import ProblemSolve
        user = User.objects.create_user(username='ledger', password='strong-secret-284', score=999, problems_solved=99)
        problem = Problem.objects.create(title='Ledger', description='Test', difficulty='easy', points=10)
        ProblemSolve.objects.create(user=user, problem=problem)
        self.client.force_authenticate(user)
        self.assertEqual(self.client.get(self.profile_url).data['score'], 10)
        self.assertEqual(self.client.get(self.profile_url).data['problems_solved'], 1)
        problem.points = 25
        problem.save(update_fields=['points'])
        self.assertEqual(self.client.get(self.profile_url).data['score'], 25)
        problem.delete()
        self.assertEqual(self.client.get(self.profile_url).data['score'], 0)
        self.assertEqual(self.client.get(self.profile_url).data['problems_solved'], 0)
