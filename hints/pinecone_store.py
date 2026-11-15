"""Pinecone Documents API (2026-07), integrated embedding, bounded REST transport."""
import hashlib
import json
import math
import time
from urllib.error import HTTPError, URLError
from urllib.parse import urlsplit, quote
from urllib.request import Request, HTTPRedirectHandler, build_opener
from django.conf import settings
from .provider import ProviderError
from .db_lifecycle import release_connections, database_retry


class NoRedirect(HTTPRedirectHandler):
    def redirect_request(self, request, fp, code, msg, headers, newurl):
        return None


def host_url():
    raw = getattr(settings, 'PINECONE_INDEX_HOST', '').strip()
    raw = raw if '://' in raw else 'https://' + raw
    try:
        parsed = urlsplit(raw)
        port = parsed.port
    except ValueError:
        raise ProviderError('Pinecone index host must be a valid HTTPS pinecone.io host.') from None
    if (parsed.scheme != 'https' or not parsed.hostname or not parsed.hostname.endswith('.pinecone.io')
            or parsed.username or parsed.password or port not in (None,443)
            or parsed.path not in ('','/') or parsed.query or parsed.fragment):
        raise ProviderError('Pinecone index host must be an HTTPS pinecone.io data-plane host.')
    return 'https://' + parsed.hostname


def is_configured():
    try:
        host_url()
        return bool(getattr(settings,'PINECONE_API_KEY','').strip())
    except ProviderError:
        return False


def index_identity():
    values = [host_url(),getattr(settings,'PINECONE_NAMESPACE','benchcoder-knowledge-v1'),getattr(settings,'PINECONE_EMBEDDING_FIELD','chunk_text'),getattr(settings,'PINECONE_EMBEDDING_MODEL','text-embedding-3-small'),'2026-07']
    return hashlib.sha256(json.dumps(values).encode()).hexdigest()


def record_id(source):
    model = getattr(settings,'PINECONE_EMBEDDING_MODEL','text-embedding-3-small')
    version = hashlib.sha256((source.digest() + model).encode()).hexdigest()
    return f'problem-{source.problem_id}-{version}'


def _post(operation, payload):
    # Validate destination before attaching the secret; redirects are always refused.
    host = host_url()
    key = getattr(settings,'PINECONE_API_KEY','').strip()
    if not key:
        raise ProviderError('Pinecone credentials are not configured. Ask the administrator.')
    namespace = quote(getattr(settings,'PINECONE_NAMESPACE','benchcoder-knowledge-v1'),safe='')
    request = Request(host + '/namespaces/' + namespace + '/documents/' + operation,
        data=json.dumps(payload,allow_nan=False).encode(),
        headers={'Api-Key':key,'Content-Type':'application/json','X-Pinecone-API-Version':'2026-07'},method='POST')
    try:
        with build_opener(NoRedirect()).open(request,timeout=30 if operation == 'upsert' else 10) as response:
            body = response.read(2_000_001)
        if len(body) > 2_000_000:
            raise ProviderError('Pinecone returned an oversized response.')
        result = json.loads(body)
        if not isinstance(result,dict):
            raise ValueError('Expected object')
        return result
    except HTTPError as error:
        if error.code in (401,403):
            raise ProviderError('Pinecone credentials or index access need administrator attention.') from None
        if 300 <= error.code < 400:
            raise ProviderError('Pinecone redirected the request. Check the configured index host.') from None
        raise ProviderError('Pinecone could not complete retrieval. Please try again.',retryable=error.code==429 or error.code>=500) from None
    except (URLError,TimeoutError,OSError):
        raise ProviderError('Pinecone could not be reached. Please try again.',retryable=True) from None
    except (TypeError,ValueError):
        raise ProviderError('Pinecone returned an invalid response.') from None


def upsert_sources(sources):
    field = getattr(settings,'PINECONE_EMBEDDING_FIELD','chunk_text')
    model = getattr(settings,'PINECONE_EMBEDDING_MODEL','text-embedding-3-small')
    documents = []
    for source in sources:
        key = record_id(source)
        # Explicit allowlist: no teaching notes, attempts, tests, or learner identifiers.
        text = '\n'.join([source.problem.title,source.problem.description,', '.join(source.concepts)])[:14000]
        documents.append({'_id':key,'record_key':key,field:text,'title':source.problem.title,'problem_id':str(source.problem_id),'content_hash':source.digest(),'embedding_model':model})
    if documents:
        result = _post('upsert',{'documents':documents})
        if result.get('upserted_count') != len(documents):
            raise ProviderError('Pinecone did not confirm all learning documents were stored.',retryable=True)


def search_sources(query, permitted_keys):
    field = getattr(settings,'PINECONE_EMBEDDING_FIELD','chunk_text')
    result = _post('search',{
        'score_by':[{'type':'embed','fields':[field],'query':query[:14000]}],
        'top_k':min(3,len(permitted_keys)),
        'filter':{'record_key':{'$in':permitted_keys}},
        'include_fields':['record_key','problem_id','content_hash','embedding_model'],
    })
    matches = result.get('matches')
    if not isinstance(matches,list):
        raise ProviderError('Pinecone returned invalid search results.')
    return matches


def retrieve_sources(sources, problem, target_concepts):
    from .models import ProblemKnowledge
    identity = index_identity()
    permitted = {record_id(source):source for source in sources}
    stale = [source for key,source in permitted.items() if source.pinecone_record_id != key or source.pinecone_index_identity != identity]
    release_connections()
    upsert_sources(stale)
    for source in stale:
        database_retry(lambda: ProblemKnowledge.objects.filter(pk=source.pk,updated_at=source.updated_at).update(pinecone_record_id=record_id(source),pinecone_index_identity=identity))
    query = '\n'.join([problem.title,problem.description,', '.join(target_concepts)])
    for attempt in range(3):
        release_connections()
        matches = search_sources(query,list(permitted))
        validated = []
        seen = set()
        for match in matches:
            if not isinstance(match,dict):
                continue
            fields = match.get('fields',match)
            key = match.get('_id')
            source = permitted.get(key)
            if not source or key in seen or not isinstance(fields,dict):
                continue
            if (fields.get('record_key') != key or fields.get('problem_id') != str(source.problem_id)
                    or fields.get('content_hash') != source.digest()
                    or fields.get('embedding_model') != getattr(settings,'PINECONE_EMBEDDING_MODEL','text-embedding-3-small')):
                continue
            score = match.get('_score')
            if not isinstance(score,(int,float)) or isinstance(score,bool) or not math.isfinite(score):
                continue
            seen.add(key)
            validated.append((source,float(score)))
        if len(validated) >= min(3,len(permitted)):
            return [{ 'problem_id':source.problem_id,'title':source.problem.title,'concepts':source.concepts,
                'approach_summary':source.approach_summary,'similarity':round(score,4)}
                for source,score in validated if score >= settings.AI_HINTS_SIMILARITY_THRESHOLD][:3]
        if attempt < 2:
            time.sleep(.5)
    raise ProviderError('Pinecone learning documents are not searchable yet. Please try again.',retryable=True)
