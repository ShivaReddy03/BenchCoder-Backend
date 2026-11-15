"""Index reviewed public problem knowledge; never upload attempts or teaching notes."""
from django.core.management.base import BaseCommand, CommandError

from hints.models import ProblemKnowledge
from hints.pinecone_store import index_identity, record_id, upsert_sources
from hints.provider import ProviderError


class Command(BaseCommand):
    help = 'Synchronize reviewed public problem knowledge into the configured Pinecone index.'

    def add_arguments(self, parser):
        parser.add_argument('--force', action='store_true', help='Re-upsert records even when local sync markers match.')

    def handle(self, *args, **options):
        try:
            identity = index_identity()
            count = 0
            batch = []
            for knowledge in ProblemKnowledge.objects.select_related('problem').order_by('id').iterator():
                if (options['force'] or knowledge.pinecone_index_identity != identity
                        or knowledge.pinecone_record_id != record_id(knowledge)):
                    batch.append(knowledge)
                if len(batch) == 40:
                    self.sync_batch(batch, identity)
                    count += len(batch)
                    batch = []
            if batch:
                self.sync_batch(batch, identity)
                count += len(batch)
            self.stdout.write(self.style.SUCCESS(f'Synchronized {count} public knowledge records to Pinecone. Search visibility may take a moment.'))
        except ProviderError as error:
            raise CommandError(error.safe_message) from None

    @staticmethod
    def sync_batch(batch, identity):
        upsert_sources(batch)
        for source in batch:
            ProblemKnowledge.objects.filter(pk=source.pk, updated_at=source.updated_at).update(
                pinecone_record_id=record_id(source), pinecone_index_identity=identity,
            )
