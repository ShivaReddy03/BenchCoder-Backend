from django.conf import settings
from django.db import models


class SolutionRequest(models.Model):
    user = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE)
    problem = models.ForeignKey('problems.Problem', on_delete=models.CASCADE)
    code = models.TextField(blank=True)
    language = models.CharField(max_length=10, choices=[('python', 'Python'), ('javascript', 'JavaScript'), ('java', 'Java'), ('cpp', 'C++')])
    status = models.CharField(max_length=12, default='queued', choices=[('queued', 'Queued'), ('running', 'Running'), ('completed', 'Completed'), ('failed', 'Failed')])
    fingerprint = models.CharField(max_length=64, db_index=True)
    explanation = models.TextField(blank=True)
    solution_code = models.TextField(blank=True)
    time_complexity = models.TextField(blank=True)
    space_complexity = models.TextField(blank=True)
    error_message = models.TextField(blank=True)
    created_at = models.DateTimeField(auto_now_add=True, db_index=True)
    started_at = models.DateTimeField(null=True, blank=True)
    finished_at = models.DateTimeField(null=True, blank=True)


class SolutionQuota(models.Model):
    name = models.CharField(max_length=20, unique=True, default='global')
