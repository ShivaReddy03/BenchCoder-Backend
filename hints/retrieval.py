"""Bounded learner-specific retrieval, with local or Pinecone integrated embeddings."""
import hashlib
import json
import math
from django.conf import settings
from submissions.models import ProblemSolve
from .models import ProblemKnowledge
from .db_lifecycle import release_connections, database_retry


def eligible_knowledge(user_id, current_problem_id):
    solved_ids = ProblemSolve.objects.filter(user_id=user_id).exclude(problem_id=current_problem_id).order_by('-created_at').values_list('problem_id', flat=True)[:40]
    return list(ProblemKnowledge.objects.filter(problem_id__in=solved_ids).select_related('problem').order_by('problem_id'))


def request_fingerprint(user_id, problem, level, code, language):
    current = ProblemKnowledge.objects.filter(problem=problem).select_related('problem').first()
    sources = eligible_knowledge(user_id, problem.id)
    data = {
        'user': user_id, 'problem': [problem.id, problem.title, problem.description],
        'concepts': current.concepts if current else [],
        'examples': list(problem.test_cases.filter(is_public=True).order_by('id').values_list('id','input','expected_output')[:3]),
        'level': level, 'code': code, 'language': language,
        'knowledge': [(source.problem_id, source.digest()) for source in sources],
        'solves': list(ProblemSolve.objects.filter(user_id=user_id).order_by('problem_id').values_list('problem_id',flat=True)),
        'models': [settings.AI_HINT_MODEL, settings.AI_EMBEDDING_MODEL],
        'similarity_threshold': settings.AI_HINTS_SIMILARITY_THRESHOLD,
        'retrieval_backend': getattr(settings,'AI_RETRIEVAL_BACKEND','local'),
        'pinecone_identity': _remote_identity(),
        'version': 2,
    }
    return hashlib.sha256(json.dumps(data, sort_keys=True).encode()).hexdigest()


def _remote_identity():
    if getattr(settings,'AI_RETRIEVAL_BACKEND','local') == 'pinecone':
        from .pinecone_store import index_identity
        from .provider import ProviderError
        try:
            return index_identity()
        except ProviderError:
            return 'invalid-pinecone-configuration'
    return ''


def cosine(left, right):
    if len(left) != len(right) or not left:
        return 0.0
    norm = math.sqrt(sum(x*x for x in left) * sum(x*x for x in right))
    return sum(x*y for x,y in zip(left,right)) / norm if norm else 0.0


def retrieve(user_id, problem):
    from .provider import embed_texts
    sources = eligible_knowledge(user_id, problem.id)
    if not sources:
        return []
    target, _ = ProblemKnowledge.objects.get_or_create(problem=problem)
    if getattr(settings,'AI_RETRIEVAL_BACKEND','local') == 'pinecone':
        from .pinecone_store import retrieve_sources
        result = retrieve_sources(sources,problem,target.concepts)
        # Remote results never authorize access: re-check current solve and knowledge state.
        release_connections()
        current = database_retry(lambda: {source.problem_id:source.digest() for source in eligible_knowledge(user_id,problem.id)})
        previous = {source.problem_id:source.digest() for source in sources}
        if any(current.get(source['problem_id']) != previous.get(source['problem_id']) for source in result):
            from .provider import ProviderError
            raise ProviderError('Learning history changed during retrieval. Please request a new hint.')
        return result
    nodes = [target] + sources
    stale = [node for node in nodes if node.content_hash != node.digest() or node.embedding_model != settings.AI_EMBEDDING_MODEL or not node.embedding]
    if stale:
        # No approach summaries or source code are embedded, including the target's notes.
        texts = ['\n'.join([node.problem.title, node.problem.description, ', '.join(node.concepts)])[:14000] for node in stale]
        release_connections()
        embeddings = embed_texts(texts)
        if len(embeddings) != len(texts):
            from .provider import ProviderError
            raise ProviderError('Embedding provider returned an invalid response.', retryable=False)
        for node, vector in zip(stale, embeddings):
            node.embedding = vector
            node.embedding_model = settings.AI_EMBEDDING_MODEL
            node.content_hash = node.digest()
            # A concurrent admin update must not attach an old index to new knowledge.
            database_retry(lambda: ProblemKnowledge.objects.filter(pk=node.pk, updated_at=node.updated_at).update(embedding=vector, embedding_model=node.embedding_model, content_hash=node.content_hash))
    ranked = sorted(sources, key=lambda source: cosine(target.embedding,source.embedding), reverse=True)
    relevant = [source for source in ranked if cosine(target.embedding,source.embedding) >= settings.AI_HINTS_SIMILARITY_THRESHOLD][:3]
    return [{
        'problem_id': source.problem_id, 'title': source.problem.title,
        'concepts': source.concepts, 'approach_summary': source.approach_summary,
        'similarity': round(cosine(target.embedding,source.embedding),4),
    } for source in relevant]
