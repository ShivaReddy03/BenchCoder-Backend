import io
import json
from unittest.mock import patch
from urllib.error import HTTPError

from django.test import SimpleTestCase, override_settings

from .provider import ProviderError, embed_texts, generate_hint


@override_settings(AI_API_KEY='test-key', AI_HINT_MODEL='gpt-4.1-mini', AI_EMBEDDING_MODEL='text-embedding-3-small')
class ProviderTests(SimpleTestCase):
    @patch('hints.provider._post')
    def test_generation_only_sends_allowlisted_user_context(self, post):
        post.return_value = {'status': 'completed', 'output': [
            {'type': 'message', 'content': [{'type': 'output_text', 'text': json.dumps({'hint': 'Think about values you have already seen.'})}]}]}
        result = generate_hint({
            'level': 'concept', 'code': 'my attempt', 'language': 'python',
            'problem': {'title': 'Current', 'description': 'Public statement', 'reference_solution': 'NEVER_SEND_SOLUTION',
                        'test_cases': [{'input': 'NEVER_SEND_HIDDEN'}]},
            'other_user_code': 'NEVER_SEND_OTHER_USER',
            'solved_sources': [{'title': 'Already solved', 'concepts': ['sets'], 'approach_summary': 'Remember previous values.',
                                'code': 'NEVER_SEND_ACCEPTED_CODE'}],
        })
        request = post.call_args.args[1]
        payload = json.loads(request['input'])
        self.assertEqual(payload['retrieved_solved_history'][0]['title'], 'Already solved')
        self.assertEqual(payload['user_code'], 'my attempt')
        self.assertNotIn('NEVER_SEND', json.dumps(request))
        self.assertFalse(request['store'])
        self.assertEqual(result, 'Think about values you have already seen.')

    @patch('hints.provider._post')
    def test_refusal_incomplete_and_code_are_not_displayed(self, post):
        for response in [
            {'status': 'incomplete'},
            {'status': 'completed', 'output': [{'type': 'message', 'content': [{'type': 'refusal', 'refusal': 'No'}]}]},
            {'status': 'completed', 'output': [{'type': 'message', 'content': [{'type': 'output_text', 'text': '{"hint":"```python\\nprint(1)\\n```"}'}]}]},
        ]:
            with self.subTest(response=response):
                post.return_value = response
                with self.assertRaises(ProviderError):
                    generate_hint({'problem': {}, 'solved_sources': []})

    @patch('hints.provider._post')
    def test_embeddings_reorder_by_index_and_reject_invalid_vectors(self, post):
        post.return_value = {'data': [{'index': 1, 'embedding': [0.0, 1.0]}, {'index': 0, 'embedding': [1.0, 0.0]}]}
        self.assertEqual(embed_texts(['one', 'two']), [[1.0, 0.0], [0.0, 1.0]])
        for rows in [
            [{'index': 0, 'embedding': [float('nan')]}],
            [{'index': 0, 'embedding': [0.0]}],
            [{'index': 0, 'embedding': [True]}],
            [{'index': 1, 'embedding': [1.0]}],
        ]:
            post.return_value = {'data': rows}
            with self.assertRaises(ProviderError):
                embed_texts(['one'])

    @patch('hints.provider.urlopen')
    def test_authentication_error_does_not_expose_provider_body_or_key(self, open_url):
        open_url.side_effect = HTTPError('https://api.openai.com/v1/embeddings', 401, 'secret-key', {}, io.BytesIO(b'sensitive provider error'))
        with self.assertRaises(ProviderError) as error:
            embed_texts(['hello'])
        self.assertNotIn('secret', str(error.exception))
        self.assertNotIn('sensitive', str(error.exception))

    @override_settings(AI_API_KEY='')
    @patch('hints.provider.urlopen')
    def test_missing_key_never_calls_network(self, open_url):
        with self.assertRaises(ProviderError):
            embed_texts(['hello'])
        open_url.assert_not_called()
