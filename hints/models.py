import hashlib
import json
from django.conf import settings
from django.db import models


class ProblemKnowledge(models.Model):
    problem = models.OneToOneField('problems.Problem', on_delete=models.CASCADE, related_name='knowledge')
    concepts = models.JSONField(default=list)
    approach_summary = models.TextField(blank=True, help_text='Reviewed teaching notes, never reference solutions. Retrieved only for problems this learner already solved.')
    embedding = models.JSONField(default=list, blank=True, editable=False)
    embedding_model = models.CharField(max_length=100, blank=True, editable=False)
    content_hash = models.CharField(max_length=64, blank=True, editable=False)
    pinecone_record_id = models.CharField(max_length=160, blank=True, editable=False)
    pinecone_index_identity = models.CharField(max_length=64, blank=True, editable=False)
    updated_at = models.DateTimeField(auto_now=True)

    def digest(self):
        content = [self.problem.title, self.problem.description, self.concepts, self.approach_summary]
        return hashlib.sha256(json.dumps(content, sort_keys=True).encode()).hexdigest()

    def clean(self):
        from django.core.exceptions import ValidationError
        if not isinstance(self.concepts, list) or len(self.concepts) > 30 or any(not isinstance(value, str) or len(value) > 100 for value in self.concepts):
            raise ValidationError({'concepts': 'Use a list of up to 30 concept names, each at most 100 characters.'})
        if len(self.approach_summary) > 6000:
            raise ValidationError({'approach_summary': 'Keep reviewed notes within 6000 characters.'})

    def __str__(self):
        return self.problem.title


class HintRequest(models.Model):
    user = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE)
    problem = models.ForeignKey('problems.Problem', on_delete=models.CASCADE)
    level = models.CharField(max_length=12, choices=[('concept','Concept'),('approach','Approach'),('debugging','Debugging')])
    code = models.TextField(blank=True)
    language = models.CharField(max_length=10, choices=[('python','Python'),('javascript','JavaScript')], default='python')
    status = models.CharField(max_length=12, default='queued', choices=[('queued','Queued'),('running','Running'),('completed','Completed'),('failed','Failed')])
    hint = models.TextField(blank=True)
    retrieved_sources = models.JSONField(default=list)
    error_message = models.TextField(blank=True)
    fingerprint = models.CharField(max_length=64, db_index=True)
    created_at = models.DateTimeField(auto_now_add=True, db_index=True)
    started_at = models.DateTimeField(null=True, blank=True)
    finished_at = models.DateTimeField(null=True, blank=True)


class HintQuota(models.Model):
    # Serializes global daily admission across users; user row serializes per-user admission.
    name = models.CharField(max_length=20, unique=True, default='global')
