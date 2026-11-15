from io import StringIO
from django.core.management import call_command
from django.core.management.base import CommandError
from django.test import TestCase
from hints.models import ProblemKnowledge
from problems.catalog import CATALOG, MARKER
from problems.models import Problem
from problems.serializers import ProblemSerializer
from submissions.models import Submission, ProblemSolve


class CatalogSeedTests(TestCase):
    def seed(self):
        call_command('seed_catalog', stdout=StringIO())

    def test_fifteen_complete_questions_and_private_cases(self):
        self.seed()
        self.assertEqual(Problem.objects.count(), 15)
        self.assertEqual(ProblemKnowledge.objects.count(), 15)
        for problem in Problem.objects.all():
            self.assertTrue(problem.description.startswith(MARKER))
            for label in ('Input format', 'Output format', 'Constraints', 'Example 1', 'Example 2', 'Example 3'):
                self.assertIn(label, problem.description)
            self.assertEqual(problem.test_cases.filter(is_public=True).count(), 3)
            self.assertGreaterEqual(problem.test_cases.filter(is_public=False).count(), 4)
            self.assertTrue(problem.knowledge.concepts)
            self.assertTrue(problem.knowledge.approach_summary)
            payload = ProblemSerializer(problem).data
            self.assertNotIn('python', payload)
            self.assertNotIn('javascript', payload)
            self.assertNotIn('approach_summary', payload)
        self.assertFalse(Submission.objects.exists())
        self.assertFalse(ProblemSolve.objects.exists())

    def test_idempotent_and_preserves_unrelated_data(self):
        other = Problem.objects.create(title='Unrelated user question', description='Keep this', difficulty='hard')
        self.seed()
        ids = list(Problem.objects.filter(description__startswith=MARKER).order_by('id').values_list('id', flat=True))
        case_ids = list(Problem.objects.get(title=CATALOG[0]['title']).test_cases.values_list('id', flat=True))
        self.seed()
        self.assertEqual(Problem.objects.count(), 16)
        self.assertEqual(ids, list(Problem.objects.filter(description__startswith=MARKER).order_by('id').values_list('id', flat=True)))
        self.assertEqual(case_ids, list(Problem.objects.get(title=CATALOG[0]['title']).test_cases.values_list('id', flat=True)))
        other.refresh_from_db()
        self.assertEqual(other.description, 'Keep this')

    def test_reserved_title_collision_rolls_back_without_overwriting(self):
        other = Problem.objects.create(title=CATALOG[-1]['title'], description='Unrelated existing question', difficulty='hard')
        with self.assertRaises(CommandError):
            self.seed()
        self.assertEqual(Problem.objects.count(), 1)
        other.refresh_from_db()
        self.assertEqual(other.description, 'Unrelated existing question')

    def test_changed_reviewed_knowledge_invalidates_indexes(self):
        self.seed()
        knowledge = ProblemKnowledge.objects.first()
        knowledge.approach_summary = 'outdated'
        knowledge.embedding = [1.0]
        knowledge.pinecone_record_id = 'old-remote-id'
        knowledge.save()
        self.seed()
        knowledge.refresh_from_db()
        self.assertEqual(knowledge.embedding, [])
        self.assertEqual(knowledge.pinecone_record_id, '')
