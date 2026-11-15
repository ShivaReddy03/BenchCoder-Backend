"""Reviewed stdin/stdout demo fixtures; never fabricate solved histories."""
import os
import secrets
import time
from django.contrib.auth import get_user_model
from django.core.management.base import BaseCommand, CommandError
from django.db import transaction
from problems.models import Problem, TestCase

MARKER = 'Seeded RAG demonstration dataset v1.'

# Every solution reads stdin and writes only the expected answer.
DATA = [
    ('Array Sum', 'Print the sum of the space-separated integers on the first line.', ['arrays', 'linear scan', 'accumulator'], 'Accumulate each value once; an empty list has sum zero.',
     [('', '0'), ('1 2 3', '6'), ('-5 5 7', '7'), ('0 0', '0')],
     "import sys\nprint(sum(map(int, sys.stdin.read().split())))", "const s=require('fs').readFileSync(0,'utf8').trim();console.log(s?s.split(/\\s+/).map(Number).reduce((a,b)=>a+b,0):0);"),
    ('Contains Duplicate', 'Print YES if a space-separated integer list contains a duplicate, otherwise NO.', ['arrays', 'hash set', 'membership', 'lookup'], 'Track seen values in a hash set; repeated membership identifies a duplicate.',
     [('1 2 3', 'NO'), ('1 2 1', 'YES'), ('-2 -2', 'YES'), ('', 'NO')],
     "import sys\na=sys.stdin.read().split();print('YES' if len(a)!=len(set(a)) else 'NO')", "const s=require('fs').readFileSync(0,'utf8').trim();const a=s?s.split(/\\s+/):[];console.log(new Set(a).size<a.length?'YES':'NO');"),
    ('Sorted Pair Sum', 'First line: sorted integers. Second line: target. Print YES if two distinct positions sum to target, otherwise NO.', ['arrays', 'two pointers', 'sorted order', 'pair sum'], 'Move left and right pointers inward according to whether their sum is below or above the target.',
     [('1 2 4 7\n9', 'YES'), ('1 2 3\n10', 'NO'), ('2 2\n4', 'YES'), ('5\n10', 'NO')],
     "import sys\ns=sys.stdin.read().splitlines();a=list(map(int,s[0].split()));t=int(s[1]);l=0;r=len(a)-1\nwhile l<r and a[l]+a[r]!=t:\n if a[l]+a[r]<t:l+=1\n else:r-=1\nprint('YES' if l<r else 'NO')", "const s=require('fs').readFileSync(0,'utf8').trim().split(/\\r?\\n/);const a=s[0].trim().split(/\\s+/).map(Number),t=Number(s[1]);let l=0,r=a.length-1;while(l<r&&a[l]+a[r]!==t){if(a[l]+a[r]<t)l++;else r--;}console.log(l<r?'YES':'NO');"),
    ('Valid Anagram', 'Two lines contain lowercase words. Print YES when their character counts match, otherwise NO.', ['strings', 'frequency map', 'hash map', 'counting'], 'Count characters in each word and compare their frequency maps.',
     [('listen\nsilent', 'YES'), ('rat\ncar', 'NO'), ('aab\nabb', 'NO'), ('aa\naa', 'YES')],
     "import sys\nfrom collections import Counter\na,b=sys.stdin.read().splitlines();print('YES' if Counter(a)==Counter(b) else 'NO')", "const [a,b]=require('fs').readFileSync(0,'utf8').trim().split(/\\r?\\n/);const norm=s=>s.split('').sort().join('');console.log(norm(a)===norm(b)?'YES':'NO');"),
    ('First Unique Character', 'One line contains a lowercase word. Print the zero-based index of its first character occurring once, or -1.', ['strings', 'frequency map', 'hash map', 'lookup'], 'Build character frequencies first, then scan in original order to locate the first frequency of one.',
     [('leetcode', '0'), ('loveleetcode', '2'), ('aabb', '-1'), ('z', '0')],
     "import sys\nfrom collections import Counter\ns=sys.stdin.read().strip();c=Counter(s);print(next((i for i,x in enumerate(s) if c[x]==1),-1))", "const s=require('fs').readFileSync(0,'utf8').trim(),c={};for(const x of s)c[x]=(c[x]||0)+1;console.log([...s].findIndex(x=>c[x]===1));"),
    ('Reverse Word', 'One line contains a lowercase word. Print it reversed.', ['strings', 'two pointers', 'sequence'], 'Swap symmetric positions while moving pointers toward the middle.',
     [('hello', 'olleh'), ('a', 'a'), ('abcd', 'dcba'), ('level', 'level')],
     "import sys\nprint(sys.stdin.read().strip()[::-1])", "console.log(require('fs').readFileSync(0,'utf8').trim().split('').reverse().join(''));"),
    ('Two Sum', 'First line: space-separated integers. Second line: target. Print YES if two distinct positions sum to target, otherwise NO. Values need not be sorted.', ['arrays', 'hash map', 'lookup', 'pair sum', 'frequency map'], 'For each value, look for its required complement among previously seen values. Sorting also permits a two-pointer approach when only existence is required.',
     [('2 7 11 15\n9', 'YES'), ('1 2 3\n8', 'NO'), ('3 3\n6', 'YES'), ('-4 2 9\n5', 'YES')],
     "import sys\ns=sys.stdin.read().splitlines();a=list(map(int,s[0].split()));t=int(s[1]);seen=set();ok=False\nfor x in a:\n if t-x in seen:ok=True;break\n seen.add(x)\nprint('YES' if ok else 'NO')", "const s=require('fs').readFileSync(0,'utf8').trim().split(/\\r?\\n/),a=s[0].split(/\\s+/).map(Number),t=Number(s[1]),seen=new Set();let ok=false;for(const x of a){if(seen.has(t-x)){ok=true;break;}seen.add(x);}console.log(ok?'YES':'NO');"),
    ('Count Distinct Values', 'Print the number of distinct integers in a space-separated list.', ['arrays', 'hash set', 'counting'], 'Insert each value in a set and read its final size.',
     [('1 2 2 3', '3'), ('', '0'), ('-1 -1 0', '2'), ('7', '1')],
     "import sys\nprint(len(set(sys.stdin.read().split())))", "const s=require('fs').readFileSync(0,'utf8').trim();console.log(new Set(s?s.split(/\\s+/):[]).size);"),
]


class Command(BaseCommand):
    help = 'Seed reviewed hint-demo problems; optionally create users and submit real solutions.'

    def add_arguments(self, parser):
        parser.add_argument('--create-users', action='store_true')
        parser.add_argument('--submit-solutions', action='store_true')
        parser.add_argument('--wait', action='store_true')
        parser.add_argument('--timeout', type=int, default=240)

    def handle(self, *args, **options):
        from hints.models import ProblemKnowledge
        from submissions.models import Submission, ProblemSolve
        from judge.tasks import judge_submission
        seeded = {}
        for title, description, concepts, approach, cases, py, js in DATA:
            title = '[Hint Demo] ' + title
            with transaction.atomic():
                problem, created = Problem.objects.get_or_create(title=title, defaults={
                    'description': MARKER + '\n\n' + description,
                    'difficulty': 'easy', 'points': 10,
                })
                if not created and not problem.description.startswith(MARKER):
                    raise CommandError('Refusing to modify an unrelated problem with a reserved demo title.')
                description_changed = problem.description != MARKER + '\n\n' + description
                problem.description = MARKER + '\n\n' + description
                problem.save(update_fields=['description', 'updated_at'])
                existing = list(problem.test_cases.order_by('id'))
                for index, (input_data, output) in enumerate(cases):
                    values = {'input': input_data, 'expected_output': output, 'is_public': index < 3}
                    if index < len(existing):
                        TestCase.objects.filter(pk=existing[index].pk).update(**values)
                    else:
                        TestCase.objects.create(problem=problem, **values)
                for extra in existing[len(cases):]:
                    extra.delete()
                knowledge, _ = ProblemKnowledge.objects.get_or_create(problem=problem)
                # Keep embeddings only while their source knowledge is unchanged.
                if description_changed or knowledge.concepts != concepts or knowledge.approach_summary != approach:
                    knowledge.concepts = concepts
                    knowledge.approach_summary = approach
                    knowledge.embedding = []
                    knowledge.embedding_model = ''
                    knowledge.content_hash = ''
                    knowledge.full_clean()
                    knowledge.save()
                seeded[title] = (problem, py, js)
        self.stdout.write(f'Seeded {len(seeded)} reviewed problems. Shared target: [Hint Demo] Two Sum.')
        histories = {'demo_arrays': ['Contains Duplicate', 'Sorted Pair Sum'],
                     'demo_strings': ['Valid Anagram', 'First Unique Character']}
        users = {}
        for username in histories:
            user = get_user_model().objects.filter(username=username).first()
            if user and (user.email != username + '@example.invalid' or user.is_staff or user.is_superuser):
                raise CommandError('Refusing to use an unrelated or privileged account: ' + username)
            if user is None and options['create_users']:
                password = os.environ.get('HINT_DEMO_PASSWORD') or secrets.token_urlsafe(24)
                user = get_user_model().objects.create_user(username=username, password=password, email=username + '@example.invalid')
                if not os.environ.get('HINT_DEMO_PASSWORD'):
                    self.stdout.write(f'Created {username}; generated password (shown once): {password}')
                else:
                    self.stdout.write(f'Created {username} using HINT_DEMO_PASSWORD.')
            if user:
                users[username] = user
        if not options['submit_solutions']:
            self.stdout.write('No accepted results or solve histories were fabricated. Use --submit-solutions to enqueue real evaluations.')
            return
        if len(users) != 2:
            raise CommandError('Create both demo users first with --create-users (or provide existing accounts).')
        queued = []
        for username, titles in histories.items():
            for short_title in titles:
                problem, py, js = seeded['[Hint Demo] ' + short_title]
                if ProblemSolve.objects.filter(user=users[username], problem=problem).exists():
                    continue
                pending = Submission.objects.filter(user=users[username], problem=problem, kind='submit', status__in=['queued', 'running']).order_by('-id').first()
                if pending is None:
                    pending = Submission.objects.create(user=users[username], problem=problem, code=py if username == 'demo_arrays' else js, language='python' if username == 'demo_arrays' else 'javascript')
                    try:
                        judge_submission.apply_async(args=[pending.id], retry=False)
                    except Exception as exc:
                        from django.utils import timezone
                        pending.status, pending.verdict = 'failed', 'OT'
                        pending.error_message = 'Execution queue unavailable during demo setup.'
                        pending.finished_at = timezone.now()
                        pending.save()
                        raise CommandError('Could not enqueue demo evaluation; check Redis/Celery.') from exc
                queued.append(pending.id)
        self.stdout.write(f'Waiting on {len(queued)} real evaluations.' if options['wait'] else f'Queued/reused {len(queued)} evaluations; check submission history for acceptance.')
        if options['wait']:
            deadline = time.monotonic() + options['timeout']
            while time.monotonic() < deadline:
                pending = Submission.objects.filter(pk__in=queued)
                if not pending.exclude(status__in=['completed', 'failed']).exists():
                    if pending.exclude(status='completed', verdict='AC').exists():
                        raise CommandError('At least one real demo solution failed; inspect its submission details.')
                    self.stdout.write(self.style.SUCCESS('All demo history solutions were actually accepted.'))
                    return
                time.sleep(1)
            raise CommandError('Timed out waiting for actual demo judging; rerun once workers are available.')
