from django.contrib.auth import get_user_model
from django.urls import reverse
from rest_framework.test import APITestCase
from problems.models import Problem
from .models import Submission


class ProblemSubmissionFilterTests(APITestCase):
    def setUp(self):
        self.user = get_user_model().objects.create_user(username='filter_owner')
        self.other = get_user_model().objects.create_user(username='filter_other')
        self.first = Problem.objects.create(title='First filter problem',description='Fixture',difficulty='easy')
        self.second = Problem.objects.create(title='Second filter problem',description='Fixture',difficulty='easy')
        self.first_submit = self.submission(self.user,self.first)
        self.second_submit = self.submission(self.user,self.second)
        self.submission(self.other,self.first)
        self.submission(self.user,self.first,kind='run')
        self.client.force_authenticate(self.user)
        self.url = reverse('submission-list')

    def submission(self,user,problem,kind='submit'):
        return Submission.objects.create(user=user,problem=problem,code='print(1)',language='python',kind=kind,status='completed',verdict='AC')

    def test_problem_filter_keeps_owner_and_excludes_runs(self):
        response = self.client.get(self.url,{'problem':self.first.id})
        self.assertEqual(response.status_code,200)
        self.assertIsInstance(response.data,list)
        self.assertEqual([row['id'] for row in response.data],[self.first_submit.id])

    def test_default_history_preserves_array_and_all_owned_submits(self):
        response = self.client.get(self.url)
        self.assertEqual(response.status_code,200)
        self.assertEqual({row['id'] for row in response.data},{self.first_submit.id,self.second_submit.id})

    def test_invalid_problem_parameters_are_safe_client_errors(self):
        for value in ('','text','0','-1','1.5','99999999999999999999999999999999'):
            with self.subTest(value=value):
                response = self.client.get(self.url,{'problem':value})
                self.assertEqual(response.status_code,400)
                self.assertEqual(response.data['detail'],"'problem' must be a positive integer.")

    def test_missing_problem_has_empty_owned_history(self):
        response = self.client.get(self.url,{'problem':self.second.id+100000})
        self.assertEqual(response.status_code,200)
        self.assertEqual(response.data,[])

    def test_filter_still_requires_authentication(self):
        self.client.force_authenticate(None)
        self.assertEqual(self.client.get(self.url,{'problem':self.first.id}).status_code,401)
