from io import StringIO
from unittest.mock import patch
from django.contrib.auth import get_user_model
from django.core.management import call_command
from django.core.management.base import CommandError
from django.test import TestCase
from hints.models import ProblemKnowledge
from problems.models import Problem
from submissions.models import Submission, ProblemSolve


class HintDemoSeedTests(TestCase):
    def seed(self, **kwargs):
        call_command('seed_hint_demo', stdout=StringIO(), **kwargs)

    def test_idempotent_reviewed_seed_does_not_fabricate_history(self):
        self.seed(create_users=True)
        knowledge = ProblemKnowledge.objects.first()
        knowledge.embedding = [1.0, 2.0]
        knowledge.embedding_model = 'test'
        knowledge.content_hash = 'test'
        knowledge.save()
        self.seed(create_users=True)
        self.assertEqual(Problem.objects.count(), 8)
        self.assertEqual(ProblemKnowledge.objects.count(), 8)
        self.assertEqual(sum(problem.test_cases.count() for problem in Problem.objects.all()), 32)
        self.assertEqual(get_user_model().objects.count(), 2)
        self.assertFalse(Submission.objects.exists())
        self.assertFalse(ProblemSolve.objects.exists())
        knowledge.refresh_from_db()
        self.assertEqual(knowledge.embedding, [1.0, 2.0])
        knowledge.approach_summary = 'outdated'
        knowledge.save()
        self.seed()
        knowledge.refresh_from_db()
        self.assertEqual(knowledge.embedding, [])
        self.assertEqual(knowledge.content_hash, '')

    def test_reserved_account_cannot_be_unrelated_or_privileged(self):
        user = get_user_model().objects.create_user(username='demo_arrays', email='someone@example.com')
        with self.assertRaises(CommandError):
            self.seed(submit_solutions=True)
        user.email = 'demo_arrays@example.invalid'
        user.is_staff = True
        user.save()
        with self.assertRaises(CommandError):
            self.seed(submit_solutions=True)
        self.assertFalse(Submission.objects.exists())

    @patch('judge.tasks.judge_submission.apply_async')
    def test_histories_are_queued_for_actual_evaluation_once(self, dispatch):
        self.seed(create_users=True, submit_solutions=True)
        self.assertEqual(dispatch.call_count, 4)
        self.assertEqual(Submission.objects.count(), 4)
        self.assertFalse(Submission.objects.exclude(status='queued', verdict='P').exists())
        self.assertFalse(ProblemSolve.objects.exists())
        self.seed(submit_solutions=True)
        self.assertEqual(dispatch.call_count, 4)

    def test_unrelated_problem_with_reserved_title_is_preserved(self):
        problem = Problem.objects.create(title='[Hint Demo] Array Sum', description='Unrelated', difficulty='easy')
        with self.assertRaises(CommandError):
            self.seed()
        problem.refresh_from_db()
        self.assertEqual(problem.description, 'Unrelated')
