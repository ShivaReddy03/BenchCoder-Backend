from unittest.mock import patch
from datetime import timedelta
from django.contrib.auth import get_user_model
from django.test import TestCase, override_settings
from django.urls import reverse
from django.utils import timezone
from rest_framework.test import APITestCase
from problems.models import Problem, TestCase as ProblemCase
from submissions.models import ProblemSolve
from .models import HintRequest, ProblemKnowledge
from .retrieval import request_fingerprint, retrieve
from .tasks import generate_request
from .provider import ProviderError


@override_settings(AI_RETRIEVAL_BACKEND='local',AI_API_KEY='test-key',AI_HINTS_DAILY_LIMIT=20,AI_HINTS_GLOBAL_DAILY_LIMIT=200)
class HintTests(APITestCase):
    def setUp(self):
        self.user = get_user_model().objects.create_user(username='learner',password='testpass123')
        self.other = get_user_model().objects.create_user(username='someone',password='testpass123')
        self.problem = Problem.objects.create(title='Target',description='Public target',difficulty='easy')
        self.solved = Problem.objects.create(title='Solved',description='Public solved',difficulty='easy')
        self.unseen = Problem.objects.create(title='Unseen',description='Unseen problem',difficulty='easy')
        self.knowledge = ProblemKnowledge.objects.create(problem=self.solved,concepts=['hash map'],approach_summary='Reviewed solved teaching note')
        ProblemKnowledge.objects.create(problem=self.unseen,concepts=['secret'],approach_summary='NEVER_SEND')
        ProblemKnowledge.objects.create(problem=self.problem,concepts=['map'],approach_summary='CURRENT_SOLUTION_NEVER_SEND')
        ProblemSolve.objects.create(user=self.user,problem=self.solved)
        ProblemCase.objects.create(problem=self.problem,input='PRIVATE_INPUT',expected_output='PRIVATE_OUTPUT',is_public=False)
        self.client.force_authenticate(self.user)
        self.payload = {'problem':self.problem.id,'level':'concept','code':'','language':'python'}

    def job(self,**kwargs):
        data = {'problem':self.problem,'level':'concept','code':'','language':'python'}
        data.update(kwargs)
        return HintRequest.objects.create(user=self.user,fingerprint=request_fingerprint(self.user.id,**{key:data[key] for key in ('problem','level','code','language')}),**data)

    @patch('hints.views.generate_request.apply_async')
    def test_async_ownership_and_active_limit(self,dispatch):
        response = self.client.post(reverse('hint-create'),self.payload)
        self.assertEqual(response.status_code,202)
        dispatch.assert_called_once()
        self.assertEqual(self.client.post(reverse('hint-create'),self.payload).status_code,429)
        self.client.force_authenticate(self.other)
        self.assertEqual(self.client.get(reverse('hint-detail',args=[response.data['id']])).status_code,404)
        self.client.force_authenticate(None)
        self.assertEqual(self.client.get(reverse('hint-config')).status_code,401)

    @override_settings(AI_API_KEY='')
    def test_missing_provider_truthful_and_no_secret_config(self):
        self.assertFalse(self.client.get(reverse('hint-config')).data['enabled'])
        response = self.client.post(reverse('hint-create'),self.payload)
        self.assertEqual(response.status_code,503)
        self.assertEqual(response.data['status'],'failed')
        self.assertEqual(HintRequest.objects.count(),1)
        self.assertNotIn('AI_API_KEY',str(response.data))

    @patch('hints.views.generate_request.apply_async',side_effect=ConnectionError)
    def test_broker_failure_is_persisted(self,dispatch):
        response = self.client.post(reverse('hint-create'),self.payload)
        self.assertEqual(response.status_code,503)
        self.assertEqual(HintRequest.objects.get().status,'failed')

    @override_settings(AI_HINTS_DAILY_LIMIT=1)
    @patch('hints.views.generate_request.apply_async')
    def test_cache_precedes_limits_and_knowledge_invalidates(self,dispatch):
        job = self.job(status='completed',hint='A cached hint')
        response = self.client.post(reverse('hint-create'),self.payload)
        self.assertEqual(response.status_code,200)
        self.assertEqual(response.data['id'],job.id)
        dispatch.assert_not_called()
        self.knowledge.approach_summary = 'Updated reviewed note'
        self.knowledge.save()
        self.assertEqual(self.client.post(reverse('hint-create'),self.payload).status_code,429)

    @override_settings(AI_HINTS_GLOBAL_DAILY_LIMIT=1)
    def test_global_limit_applies_across_users(self):
        self.job(status='failed')
        self.client.force_authenticate(self.other)
        self.assertEqual(self.client.post(reverse('hint-create'),self.payload).status_code,429)

    def test_debugging_requires_code_and_max_length(self):
        self.assertEqual(self.client.post(reverse('hint-create'),{**self.payload,'level':'debugging'}).status_code,400)
        self.assertEqual(self.client.post(reverse('hint-create'),{**self.payload,'code':'x'*12001}).status_code,400)

    @patch('hints.provider.embed_texts',return_value=[[1.,0.],[1.,0.]])
    def test_retrieval_uses_only_personally_solved_knowledge(self,embed):
        sources = retrieve(self.user.id,self.problem)
        self.assertEqual([source['problem_id'] for source in sources],[self.solved.id])
        self.assertNotIn('NEVER_SEND',str(embed.call_args))
        self.assertNotIn('PRIVATE_INPUT',str(embed.call_args))
        self.assertNotIn('CURRENT_SOLUTION',str(embed.call_args))
        self.knowledge.refresh_from_db()
        self.assertEqual(self.knowledge.content_hash,self.knowledge.digest())

    @patch('hints.provider.embed_texts',return_value=[[1.,0.],[1.,0.]])
    @patch('hints.provider.generate_hint',return_value='Think about a key-value lookup.')
    def test_task_context_privacy_and_idempotency(self,generate,embed):
        job = self.job()
        generate_request.run(job.id)
        job.refresh_from_db()
        self.assertEqual(job.status,'completed')
        context = generate.call_args.args[0]
        self.assertNotIn('PRIVATE_INPUT',str(context))
        self.assertNotIn('CURRENT_SOLUTION',str(context))
        self.assertNotIn('NEVER_SEND',str(context))
        self.assertNotIn('approach_summary',job.retrieved_sources[0])
        generate_request.run(job.id)
        generate.assert_called_once()

    @patch('hints.provider.embed_texts',side_effect=ProviderError('Provider unavailable.',retryable=False))
    def test_provider_failure_is_safe(self,embed):
        job = self.job()
        generate_request.run(job.id)
        job.refresh_from_db()
        self.assertEqual(job.status,'failed')
        self.assertEqual(job.error_message,'Provider unavailable.')

    def test_knowledge_change_between_enqueue_and_execution_rejected(self):
        job = self.job()
        self.knowledge.approach_summary = 'Changed'
        self.knowledge.save()
        with patch('hints.provider.generate_hint') as provider:
            generate_request.run(job.id)
        job.refresh_from_db()
        self.assertEqual(job.status,'failed')
        provider.assert_not_called()

    def test_stale_hint_fails_on_read(self):
        job = self.job()
        HintRequest.objects.filter(pk=job.id).update(created_at=timezone.now()-timedelta(minutes=4))
        self.assertEqual(self.client.get(reverse('hint-detail',args=[job.id])).data['status'],'failed')

    @patch('hints.provider.embed_texts')
    def test_no_solved_knowledge_skips_embedding_call(self,embed):
        ProblemSolve.objects.all().delete()
        self.assertEqual(retrieve(self.user.id,self.problem),[])
        embed.assert_not_called()

    @patch('hints.provider.embed_texts',return_value=[[1.,0.],[1.,0.]])
    def test_embedding_cache_includes_target(self,embed):
        retrieve(self.user.id,self.problem)
        retrieve(self.user.id,self.problem)
        embed.assert_called_once()

    @patch('hints.provider.embed_texts',return_value=[[1.,0.],[-1.,0.]])
    def test_unrelated_sources_are_not_used(self,embed):
        self.assertEqual(retrieve(self.user.id,self.problem),[])
