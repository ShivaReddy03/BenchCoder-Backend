from django.db import migrations


def normalize_history(apps, schema_editor):
    Submission = apps.get_model('submissions', 'Submission')
    Solve = apps.get_model('submissions', 'ProblemSolve')
    User = apps.get_model('users', 'User')
    Submission.objects.exclude(verdict__in=['P', 'Judging']).update(status='completed')
    Submission.objects.filter(verdict='Judging').update(status='failed', verdict='OT', error_message='Previous execution was interrupted.')
    for user_id, problem_id in Submission.objects.filter(verdict='AC').values_list('user_id', 'problem_id').distinct():
        Solve.objects.get_or_create(user_id=user_id, problem_id=problem_id)
    from django.db.models import Sum
    for user in User.objects.all():
        solved = Solve.objects.filter(user_id=user.id)
        user.problems_solved = solved.count()
        user.score = solved.aggregate(total=Sum('problem__points'))['total'] or 0
        user.save(update_fields=['problems_solved', 'score'])


class Migration(migrations.Migration):
    dependencies = [('submissions', '0003_submission_attempt_submission_error_message_and_more')]
    operations = [migrations.RunPython(normalize_history, migrations.RunPython.noop)]
