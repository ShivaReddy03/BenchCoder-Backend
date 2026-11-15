from unittest.mock import patch
from django.contrib.auth import get_user_model
from django.test import TestCase, override_settings
from problems.models import Problem
from submissions.models import ProblemSolve
from .models import ProblemKnowledge
from .provider import ProviderError
from .retrieval import retrieve, request_fingerprint
from .pinecone_store import record_id, index_identity, upsert_sources


@override_settings(AI_RETRIEVAL_BACKEND='pinecone',PINECONE_API_KEY='test',PINECONE_INDEX_HOST='https://test.svc.us.pinecone.io',PINECONE_NAMESPACE='test-namespace',PINECONE_EMBEDDING_FIELD='chunk_text',PINECONE_EMBEDDING_MODEL='text-embedding-3-small',AI_HINTS_SIMILARITY_THRESHOLD=.25)
class PineconeStoreTests(TestCase):
    def setUp(self):
        self.user = get_user_model().objects.create_user(username='pine-user')
        self.target = Problem.objects.create(title='Pair sums',description='Find matching sum pairs',difficulty='easy')
        self.solved = Problem.objects.create(title='Seen keys',description='Look up seen keys',difficulty='easy')
        self.source = ProblemKnowledge.objects.create(problem=self.solved,concepts=['hash map'],approach_summary='Reviewed private-to-provider notes')
        ProblemSolve.objects.create(user=self.user,problem=self.solved)

    def match(self):
        self.source.refresh_from_db()
        key = record_id(self.source)
        return {'_id':key,'_score':.85,'record_key':key,'problem_id':str(self.solved.id),'content_hash':self.source.digest(),'embedding_model':'text-embedding-3-small'}

    @patch('hints.pinecone_store.search_sources')
    @patch('hints.pinecone_store.upsert_sources')
    @patch('hints.provider.embed_texts')
    def test_sync_markers_avoid_repeated_writes_and_local_embedding(self,embed,upsert,search):
        search.side_effect = lambda *args:[self.match()]
        first = retrieve(self.user.id,self.target)
        self.assertEqual(first[0]['problem_id'],self.solved.id)
        self.source.refresh_from_db()
        self.assertEqual(self.source.pinecone_record_id,record_id(self.source))
        self.assertEqual(self.source.pinecone_index_identity,index_identity())
        retrieve(self.user.id,self.target)
        self.assertEqual(len(upsert.call_args.args[0]),0)
        embed.assert_not_called()

    @patch('hints.pinecone_store.search_sources')
    @patch('hints.pinecone_store.upsert_sources')
    def test_version_changes_reindex_and_namespace_changes_reindex(self,upsert,search):
        search.side_effect = lambda *args:[self.match()]
        retrieve(self.user.id,self.target)
        previous = self.source.pinecone_record_id
        self.source.concepts = ['dictionary']
        self.source.save()
        retrieve(self.user.id,self.target)
        self.source.refresh_from_db()
        self.assertNotEqual(self.source.pinecone_record_id,previous)
        self.assertEqual(len(upsert.call_args.args[0]),1)
        with override_settings(PINECONE_NAMESPACE='new-namespace'):
            retrieve(self.user.id,self.target)
            self.assertEqual(len(upsert.call_args.args[0]),1)

    @patch('hints.pinecone_store.upsert_sources',side_effect=ProviderError('Offline',retryable=True))
    @patch('hints.provider.embed_texts')
    def test_remote_failure_has_no_local_fallback_or_sync_marker(self,embed,upsert):
        with self.assertRaises(ProviderError):
            retrieve(self.user.id,self.target)
        self.source.refresh_from_db()
        self.assertEqual(self.source.pinecone_record_id,'')
        embed.assert_not_called()

    @patch('hints.pinecone_store.time.sleep')
    @patch('hints.pinecone_store.search_sources',return_value=[])
    @patch('hints.pinecone_store.upsert_sources')
    def test_eventual_consistency_pending_fails_truthfully(self,upsert,search,sleep):
        with self.assertRaises(ProviderError) as raised:
            retrieve(self.user.id,self.target)
        self.assertTrue(raised.exception.retryable)
        self.assertEqual(search.call_count,3)

    @patch('hints.pinecone_store._post',return_value={'upserted_count':0})
    def test_incomplete_upsert_is_not_accepted(self,post):
        with self.assertRaises(ProviderError):
            upsert_sources([self.source])

    def test_cache_key_changes_with_backend_and_remote_index_identity(self):
        args = (self.user.id,self.target,'concept','','python')
        remote = request_fingerprint(*args)
        with override_settings(AI_RETRIEVAL_BACKEND='local'):
            self.assertNotEqual(remote,request_fingerprint(*args))
        with override_settings(PINECONE_NAMESPACE='elsewhere'):
            self.assertNotEqual(remote,request_fingerprint(*args))
