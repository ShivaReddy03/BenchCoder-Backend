from django.core.management.base import BaseCommand, CommandError
from django.db import transaction
from hints.models import ProblemKnowledge
from problems.models import Problem, TestCase
from problems.catalog import CATALOG, MARKER


class Command(BaseCommand):
    help = 'Seed 15 original programming problems and reviewed knowledge; never submit solutions.'

    @transaction.atomic
    def handle(self, *args, **options):
        created_count = updated_count = 0
        medium = {'Nearest Warmer Reading', 'Whole Square Root', 'Nonadjacent Reward Trail', 'Connected Booking Blocks'}
        for entry in CATALOG:
            matches = Problem.objects.filter(title=entry['title'])
            if matches.count() > 1:
                raise CommandError('Ambiguous existing title; refusing to modify: ' + entry['title'])
            problem = matches.first()
            if problem and not problem.description.startswith(MARKER):
                raise CommandError('Refusing to overwrite an unrelated problem: ' + entry['title'])
            if problem is None:
                problem = Problem(title=entry['title'])
                created_count += 1
            else:
                updated_count += 1
            description_changed = problem.description != entry['description']
            problem.description = entry['description']
            problem.difficulty = 'medium' if entry['title'] in medium else 'easy'
            problem.points = 20 if problem.difficulty == 'medium' else 10
            problem.full_clean()
            problem.save()
            existing = list(problem.test_cases.order_by('id'))
            for index, (input_data, expected) in enumerate(entry['cases']):
                values = {'input': input_data, 'expected_output': expected, 'is_public': index < 3}
                if index < len(existing):
                    TestCase.objects.filter(pk=existing[index].pk).update(**values)
                else:
                    TestCase.objects.create(problem=problem, **values)
            for extra in existing[len(entry['cases']):]:
                extra.delete()
            knowledge, _ = ProblemKnowledge.objects.get_or_create(problem=problem)
            if description_changed or knowledge.concepts != entry['concepts'] or knowledge.approach_summary != entry['approach_summary']:
                knowledge.concepts = entry['concepts']
                knowledge.approach_summary = entry['approach_summary']
                knowledge.embedding = []
                knowledge.embedding_model = ''
                knowledge.content_hash = ''
                knowledge.pinecone_record_id = ''
                knowledge.pinecone_index_identity = ''
                knowledge.full_clean()
                knowledge.save()
        self.stdout.write(self.style.SUCCESS(f'Practice catalog: {created_count} added, {updated_count} updated (15 total). No submissions or solved histories created.'))
