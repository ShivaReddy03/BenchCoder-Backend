import hashlib
import json
from django.conf import settings

PROMPT_VERSION = 1


def public_context(problem):
    return {'title': problem.title, 'description': problem.description,
            'sample_test_cases': list(problem.test_cases.filter(is_public=True).order_by('id').values('input', 'expected_output')[:3])}


def request_fingerprint(user_id, problem, code='', language='python'):
    payload = {'user': user_id, 'problem_id': problem.id, 'problem': public_context(problem),
               'code': code, 'language': language, 'model': settings.AI_SOLUTION_MODEL,
               'prompt_version': PROMPT_VERSION}
    return hashlib.sha256(json.dumps(payload, sort_keys=True).encode()).hexdigest()
