"""Independent privacy regression tests for remote Pinecone retrieval."""
import json
from unittest.mock import patch
from django.contrib.auth import get_user_model
from django.test import TestCase, SimpleTestCase, override_settings
from problems.models import Problem, TestCase as ProblemCase
from submissions.models import ProblemSolve, Submission
from hints.models import ProblemKnowledge
from hints.provider import ProviderError
from hints.retrieval import retrieve


@override_settings(AI_RETRIEVAL_BACKEND='pinecone',
                   PINECONE_INDEX_HOST='privacy-test.svc.pinecone.io',
                   PINECONE_API_KEY='secret-key-never-in-errors',
                   PINECONE_EMBEDDING_FIELD='chunk_text',
                   PINECONE_EMBEDDING_MODEL='text-embedding-3-small', AI_API_KEY='unused-provider-key',
                   AI_EMBEDDING_MODEL='text-embedding-3-small',
                   AI_HINTS_SIMILARITY_THRESHOLD=0.25)
class PineconeRetrievalPrivacyTests(TestCase):
    def setUp(self):
        self.user = get_user_model().objects.create_user(username='vector-learner')
        self.other = get_user_model().objects.create_user(username='vector-other')
        self.target = Problem.objects.create(title='Target', description='Public pair lookup task', difficulty='easy')
        self.solved = Problem.objects.create(title='Owned solved', description='Public membership task', difficulty='easy')
        self.unseen = Problem.objects.create(title='Other learner solved', description='UNRELATED_RECORD_DESCRIPTION', difficulty='easy')
        self.target_knowledge = ProblemKnowledge.objects.create(problem=self.target, concepts=['lookup'], approach_summary='TARGET_SOLUTION_NOT_FOR_VECTOR_DB')
        self.source = ProblemKnowledge.objects.create(problem=self.solved, concepts=['membership'], approach_summary='REVIEWED_SUMMARY_NOT_FOR_VECTOR_DB')
        self.foreign = ProblemKnowledge.objects.create(problem=self.unseen, concepts=['private learner source'], approach_summary='FOREIGN_NOT_FOR_VECTOR_DB')
        ProblemSolve.objects.create(user=self.user, problem=self.solved)
        ProblemSolve.objects.create(user=self.other, problem=self.unseen)
        ProblemCase.objects.create(problem=self.solved, input='HIDDEN_INPUT_NOT_FOR_VECTOR_DB', expected_output='HIDDEN_OUTPUT_NOT_FOR_VECTOR_DB')
        Submission.objects.create(user=self.user, problem=self.solved, code='USER_CODE_NOT_FOR_VECTOR_DB', language='python')

    def match(self, source, score=0.9):
        from hints.pinecone_store import record_id
        key = record_id(source)
        return {'_id': key, '_score': score, 'fields': {
            'record_key': key, 'problem_id': str(source.problem_id),
            'content_hash': source.digest(), 'embedding_model': 'text-embedding-3-small',
            'title': 'UNTRUSTED_REMOTE_TITLE', 'approach_summary': 'REMOTE_INJECTED_NOTES',
        }}

    @patch('hints.provider.embed_texts')
    @patch('hints.pinecone_store._post')
    def test_exact_own_current_keys_only_and_no_sensitive_upsert(self, post, local_embed):
        def remote(operation, payload):
            if operation == 'upsert':
                return {'upserted_count': len(payload['documents'])}
            return {'matches': [self.match(self.foreign), self.match(self.target_knowledge), self.match(self.source)]}
        post.side_effect = remote
        results = retrieve(self.user.id, self.target)
        self.assertEqual([row['problem_id'] for row in results], [self.solved.id])
        self.assertEqual(results[0]['title'], self.solved.title)
        self.assertEqual(results[0]['approach_summary'], self.source.approach_summary)
        calls = {call.args[0]: call.args[1] for call in post.call_args_list}
        from hints.pinecone_store import record_id
        self.assertEqual(calls['search']['filter'], {'record_key': {'$in': [record_id(self.source)]}})
        self.assertEqual(len(calls['upsert']['documents']), 1)
        sent = json.dumps(calls)
        for forbidden in ('TARGET_SOLUTION_NOT_FOR_VECTOR_DB', 'REVIEWED_SUMMARY_NOT_FOR_VECTOR_DB',
                          'FOREIGN_NOT_FOR_VECTOR_DB', 'UNRELATED_RECORD_DESCRIPTION',
                          'HIDDEN_INPUT_NOT_FOR_VECTOR_DB', 'HIDDEN_OUTPUT_NOT_FOR_VECTOR_DB', 'USER_CODE_NOT_FOR_VECTOR_DB'):
            self.assertNotIn(forbidden, sent)
        self.assertNotIn('UNTRUSTED_REMOTE_TITLE', str(results))
        local_embed.assert_not_called()

    @patch('hints.pinecone_store.time.sleep')
    @patch('hints.pinecone_store._post')
    def test_stale_forged_duplicate_nonfinite_matches_are_rejected(self, post, sleep):
        stale = self.match(self.source)
        stale['fields']['content_hash'] = 'stale-hash'
        wrong_id = self.match(self.source)
        wrong_id['fields']['problem_id'] = str(self.unseen.id)
        post.side_effect = lambda op, payload: {'upserted_count': len(payload['documents'])} if op == 'upsert' else {
            'matches': [stale, wrong_id, self.match(self.foreign), self.match(self.source, float('nan')),
                        self.match(self.source, float('inf')), self.match(self.source, True), None]}
        with self.assertRaises(ProviderError):
            retrieve(self.user.id, self.target)

    @patch('hints.pinecone_store._post')
    def test_duplicate_valid_match_cannot_duplicate_source(self, post):
        post.side_effect = lambda op, payload: {'upserted_count': len(payload['documents'])} if op == 'upsert' else {
            'matches': [self.match(self.source), self.match(self.source)]}
        self.assertEqual(len(retrieve(self.user.id, self.target)), 1)

    @patch('hints.provider.embed_texts')
    @patch('hints.pinecone_store._post', side_effect=ProviderError('Remote unavailable.', retryable=True))
    def test_remote_failure_never_falls_back_to_local_embedding(self, post, embed):
        with self.assertRaises(ProviderError):
            retrieve(self.user.id, self.target)
        embed.assert_not_called()
        self.source.refresh_from_db()
        self.assertFalse(self.source.pinecone_record_id)

    @patch('hints.pinecone_store._post')
    def test_no_personal_solved_sources_means_no_remote_request(self, post):
        ProblemSolve.objects.filter(user=self.user).delete()
        self.assertEqual(retrieve(self.user.id, self.target), [])
        post.assert_not_called()

    @patch('hints.pinecone_store.time.sleep')
    @patch('hints.pinecone_store._post')
    def test_incomplete_upsert_does_not_mark_source_indexed(self, post, sleep):
        post.return_value = {'upserted_count': 0}
        with self.assertRaises(ProviderError):
            retrieve(self.user.id, self.target)
        self.source.refresh_from_db()
        self.assertFalse(self.source.pinecone_record_id)

    @patch('hints.pinecone_store.time.sleep')
    @patch('hints.pinecone_store._post')
    def test_source_revoked_during_remote_roundtrip_is_not_returned(self, post, sleep):
        def remote(operation, payload):
            if operation == 'upsert':
                return {'upserted_count': len(payload['documents'])}
            ProblemSolve.objects.filter(user=self.user, problem=self.solved).delete()
            return {'matches': [self.match(self.source)]}
        post.side_effect = remote
        try:
            result = retrieve(self.user.id, self.target)
        except ProviderError:
            return
        self.assertEqual(result, [])

    @patch('hints.pinecone_store.time.sleep')
    @patch('hints.pinecone_store._post')
    def test_reviewed_knowledge_changed_during_roundtrip_is_not_returned(self, post, sleep):
        def remote(operation, payload):
            if operation == 'upsert':
                return {'upserted_count': len(payload['documents'])}
            ProblemKnowledge.objects.filter(pk=self.source.pk).update(concepts=['changed-after-upload'])
            return {'matches': [self.match(self.source)]}
        post.side_effect = remote
        with self.assertRaises(ProviderError):
            retrieve(self.user.id, self.target)


@override_settings(PINECONE_INDEX_HOST='privacy-test.svc.pinecone.io',
                   PINECONE_API_KEY='secret-key-never-in-errors')
class PineconeTransportPrivacyTests(SimpleTestCase):
    @patch('hints.pinecone_store.build_opener')
    def test_untrusted_hosts_rejected_before_credentials_are_attached(self, opener):
        from hints.pinecone_store import _post
        for host in ('https://example.com', 'http://index.pinecone.io',
                     'https://index.pinecone.io.evil.test', 'https://user:pass@index.pinecone.io',
                     'https://index.pinecone.io:8443', 'https://index.pinecone.io/path',
                     'https://index.pinecone.io?next=evil', 'https://index.pinecone.io:bad'):
            with self.subTest(host=host), override_settings(PINECONE_INDEX_HOST=host):
                with self.assertRaises(ProviderError):
                    _post('search', {})
        opener.assert_not_called()

    @patch('hints.pinecone_store.build_opener')
    def test_redirects_denied_without_exposing_provider_secrets(self, opener):
        from urllib.error import HTTPError
        from hints.pinecone_store import _post, NoRedirect
        opener.return_value.open.side_effect = HTTPError('https://evil.test', 302, 'secret-key-never-in-errors', {}, None)
        with self.assertRaises(ProviderError) as caught:
            _post('search', {})
        self.assertNotIn('secret-key-never-in-errors', str(caught.exception))
        handler = opener.call_args.args[0]
        self.assertIsInstance(handler, NoRedirect)
        self.assertIsNone(handler.redirect_request(None, None, 302, '', {}, 'https://evil.test'))
        self.assertEqual(opener.return_value.open.call_count, 1)
