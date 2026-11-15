from django.conf import settings
from django.db import models


class Submission(models.Model):
    VERDICT_CHOICES = [(v, label) for v, label in [('AC', 'Accepted'), ('WA', 'Wrong Answer'), ('TLE', 'Time Limit Exceeded'), ('MLE', 'Memory Limit Exceeded'), ('RE', 'Runtime Error'), ('CE', 'Compilation Error'), ('OT', 'Infrastructure Error'), ('P', 'Pending')]]
    LANGUAGE_CHOICES = [('python', 'Python'), ('javascript', 'JavaScript'), ('java', 'Java'), ('cpp', 'C++')]
    user = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE)
    problem = models.ForeignKey('problems.Problem', on_delete=models.CASCADE)
    code = models.TextField()
    language = models.CharField(max_length=10, choices=LANGUAGE_CHOICES, default='python')
    kind = models.CharField(max_length=10, choices=[('run', 'Run'), ('submit', 'Submit')], default='submit')
    status = models.CharField(max_length=12, choices=[('queued', 'Queued'), ('running', 'Running'), ('completed', 'Completed'), ('failed', 'Failed')], default='queued')
    verdict = models.CharField(max_length=20, choices=VERDICT_CHOICES, default='P')
    execution_time = models.FloatField(null=True, blank=True)
    memory_used = models.FloatField(null=True, blank=True)
    passed_tests = models.PositiveIntegerField(default=0)
    total_tests = models.PositiveIntegerField(default=0)
    error_message = models.TextField(blank=True)
    sample_results = models.JSONField(default=list, blank=True)
    submitted_at = models.DateTimeField(auto_now_add=True)
    started_at = models.DateTimeField(null=True, blank=True)
    finished_at = models.DateTimeField(null=True, blank=True)
    attempt = models.PositiveIntegerField(default=0)
    # Retain existing data for a future AI cycle; never expose simulated analysis.
    ai_feedback = models.TextField(null=True, blank=True)
    ai_status = models.CharField(max_length=30, default='Not Requested')

    def __str__(self):
        return f'{self.user.username} - {self.problem.title} - {self.verdict}'


class ProblemSolve(models.Model):
    user = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE)
    problem = models.ForeignKey('problems.Problem', on_delete=models.CASCADE)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        constraints = [models.UniqueConstraint(fields=['user', 'problem'], name='unique_user_problem_solve')]
