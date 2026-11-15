"""Original practice catalog. Reference code is seed-time verification data only."""
MARKER = '[BenchCoder practice catalog v1]'


def item(title, statement, input_format, output_format, constraints, concepts, approach, inputs, solve, python, javascript):
    cases = [(value, str(solve(value))) for value in inputs]
    examples = '\n\n'.join(f'Example {i+1}\nInput:\n{value or "(empty input)"}\nOutput:\n{answer}' for i, (value, answer) in enumerate(cases[:3]))
    description = f'{MARKER}\n\n{statement}\n\nInput format\n{input_format}\n\nOutput format\n{output_format}\n\nConstraints\n{constraints}\n\n{examples}'
    return dict(title=title, description=description, concepts=concepts, approach_summary=approach, cases=cases, python=python, javascript=javascript)


def ints(text):
    return list(map(int, text.split()))


def rising(text):
    a = ints(text); best = current = 0; previous = None
    for value in a:
        current = current + 1 if previous is not None and value > previous else 1
        best = max(best, current); previous = value
    return best


def balanced(text):
    stack=[]; pairs={')':'(', ']':'[', '}':'{'}
    for char in text.strip():
        if char in pairs:
            if not stack or stack.pop()!=pairs[char]: return 'NO'
        else: stack.append(char)
    return 'YES' if not stack else 'NO'


def stairs(text):
    n=int(text); a,b=1,1
    for _ in range(n): a,b=b,a+b
    return a


def nonadjacent(text):
    prev=current=0
    for x in ints(text): prev,current=current,max(current,prev+x)
    return current


def intervals(text):
    rows=[ints(line) for line in text.splitlines() if line.strip()]
    if not rows:return 0
    rows.sort(); count=1; end=rows[0][1]
    for start,finish in rows[1:]:
        if start>end:count+=1
        end=max(end,finish)
    return count


CATALOG = [
item('Longest Rising Stretch', 'Find the length of the longest contiguous strictly increasing stretch of readings.', 'One line of space-separated integer readings; the line may be empty.', 'One integer: the maximum stretch length, or 0 for no readings.', '0 <= number of readings <= 100000; -1000000 <= reading <= 1000000.', ['arrays','linear scan'], 'Track the current increasing stretch and the greatest length seen; reset on a non-increasing neighbor.',
['1 2 3 1 2','4 4 4','','-3 -2 -1','5 4 3 2 1','7','1 3 2 4 6 8'], rising,
"import sys\na=list(map(int,sys.stdin.read().split()));best=run=0;prev=None\nfor x in a:\n run=run+1 if prev is not None and x>prev else 1;best=max(best,run);prev=x\nprint(best)",
"const a=require('fs').readFileSync(0,'utf8').trim();let best=0,run=0,prev=null;for(const x of a?a.split(/\\s+/).map(Number):[]){run=prev!==null&&x>prev?run+1:1;best=Math.max(best,run);prev=x;}console.log(best);"),
item('Second Distinct Peak', 'Find the second greatest distinct reading. Repeated greatest values count only once.', 'One line of space-separated integers, possibly empty.', 'The second greatest distinct value, or NONE if it does not exist.', '0 <= number of values <= 100000; -1000000 <= value <= 1000000.', ['arrays','distinct values'], 'Maintain the greatest two distinct values while scanning, or deduplicate and order the values.',
['4 9 9 2','-5 -2 -3','8 8','','1','2 1','-1 0 0'],lambda s: sorted(set(ints(s)))[-2] if len(set(ints(s)))>1 else 'NONE',
"import sys\na=sorted(set(map(int,sys.stdin.read().split())));print(a[-2] if len(a)>1 else 'NONE')",
"const s=require('fs').readFileSync(0,'utf8').trim(),a=[...new Set(s?s.split(/\\s+/).map(Number):[])].sort((a,b)=>a-b);console.log(a.length>1?a[a.length-2]:'NONE');"),
item('Zero-Free Cargo', 'Remove zero-valued cargo entries while preserving the order of all remaining entries.', 'One line of space-separated integers, possibly empty.', 'Remaining values separated by single spaces, or EMPTY when none remain.', '0 <= number of entries <= 100000; -1000000 <= value <= 1000000.', ['arrays','stable filtering'], 'Append only nonzero entries in their original order.',
['0 3 0 4','0 0','1 -2 3','','0','-1 0 -1','0 5 0 0 6 0'],lambda s:' '.join(str(x) for x in ints(s) if x) or 'EMPTY',
"import sys\nprint(' '.join(str(x) for x in map(int,sys.stdin.read().split()) if x) or 'EMPTY')",
"const s=require('fs').readFileSync(0,'utf8').trim();console.log((s?s.split(/\\s+/).map(Number).filter(x=>x!==0).join(' '):'')||'EMPTY');"),
item('Most Frequent Beacon', 'Find the most frequent beacon identifier. Break ties by choosing the smallest identifier.', 'One nonempty line of space-separated integer identifiers.', 'The chosen identifier.', '1 <= number of identifiers <= 100000; -1000000 <= identifier <= 1000000.', ['hash map','frequency counting','tie breaking'], 'Count each identifier, then compare candidates first by frequency and then by numeric order.',
['3 1 3 2 1','7 7 7','-2 -1 -2 -1','5','0 0 -1','9 8 7','2 2 1 1 1'],lambda s:min(set(ints(s)),key=lambda x:(-ints(s).count(x),x)),
"import sys\nfrom collections import Counter\nc=Counter(map(int,sys.stdin.read().split()));print(min(c,key=lambda x:(-c[x],x)))",
"const a=require('fs').readFileSync(0,'utf8').trim().split(/\\s+/).map(Number),c=new Map();for(const x of a)c.set(x,(c.get(x)||0)+1);let best=a[0];for(const [x,n]of c)if(n>c.get(best)||n===c.get(best)&&x<best)best=x;console.log(best);"),
item('Distinct Window Count', 'Count the distinct integers in a list.', 'One line of space-separated integers, possibly empty.', 'One integer: the number of distinct values.', '0 <= number of values <= 100000; -1000000 <= value <= 1000000.', ['hash set','deduplication'], 'Insert values into a set and use its size.',
['1 2 2 3','5 5','','-1 0 1','7','0 0 0','4 3 2 1 4'],lambda s:len(set(ints(s))),
"import sys\nprint(len(set(map(int,sys.stdin.read().split()))))",
"const s=require('fs').readFileSync(0,'utf8').trim();console.log(new Set(s?s.split(/\\s+/).map(Number):[]).size);"),
item('Equal Inventory Labels', 'Determine whether two lowercase labels contain exactly the same multiset of characters.', 'Exactly two lines, each a nonempty lowercase English word.', 'YES if their character counts are equal, otherwise NO.', '1 <= length of each word <= 100000; characters a-z only.', ['strings','frequency map'], 'Compare character frequencies for the two labels.',
['east\nseat','apple\npapel','aab\nabb','a\na','ab\na','zzzz\nzzzz','abc\ncba'],lambda s:'YES' if sorted(s.splitlines()[0])==sorted(s.splitlines()[1]) else 'NO',
"import sys\na,b=sys.stdin.read().splitlines();print('YES' if sorted(a)==sorted(b) else 'NO')",
"const[a,b]=require('fs').readFileSync(0,'utf8').trim().split(/\\r?\\n/),f=s=>s.split('').sort().join('');console.log(f(a)===f(b)?'YES':'NO');"),
item('First Solo Letter', 'Find the first character in a lowercase word that appears exactly once.', 'One nonempty lowercase English word.', 'That character, or NONE if every character repeats.', '1 <= word length <= 100000; characters a-z only.', ['strings','frequency counting','order'], 'Count all characters, then scan the original word to retain its ordering.',
['swiss','aabb','letter','z','abca','aaaaa','aabbccd'],lambda s:next((x for x in s.strip() if s.strip().count(x)==1),'NONE'),
"import sys\nfrom collections import Counter\ns=sys.stdin.read().strip();c=Counter(s);print(next((x for x in s if c[x]==1),'NONE'))",
"const s=require('fs').readFileSync(0,'utf8').trim(),c={};for(const x of s)c[x]=(c[x]||0)+1;console.log([...s].find(x=>c[x]===1)||'NONE');"),
item('Compact Letter Runs', 'Encode each maximal consecutive run as its letter followed by its length. Always include the length, even for one letter.', 'One nonempty lowercase English word.', 'The concatenated run encoding.', '1 <= word length <= 100000; characters a-z only.', ['strings','run length encoding'], 'Walk through consecutive equal letters and emit a count when a run ends.',
['aaabbc','a','abab','zzzz','aabbaa','abcde','xxxxxxxxxx'],lambda s:''.join(c+str(len(list(g))) for c,g in __import__('itertools').groupby(s.strip())),
"import sys,itertools\nprint(''.join(c+str(len(list(g))) for c,g in itertools.groupby(sys.stdin.read().strip())))",
"const s=require('fs').readFileSync(0,'utf8').trim();let out='',i=0;while(i<s.length){let j=i+1;while(j<s.length&&s[j]===s[i])j++;out+=s[i]+(j-i);i=j;}console.log(out);"),
item('Nested Gate Check', 'Check whether a sequence of round, square and curly gates is correctly nested and fully closed.', 'One line containing only ()[]{}; the line may be empty.', 'YES if every closing gate matches the latest unmatched opening gate, otherwise NO.', '0 <= sequence length <= 100000.', ['stack','balanced brackets'], 'Push opening gates and verify each closing gate against the stack top.',
['([]){}','([)]','','(','}{','{{[()]}}','(()'],balanced,
"import sys\ns=sys.stdin.read().strip();stack=[];pairs={')':'(',']':'[','}':'{'};ok=True\nfor c in s:\n if c in pairs:\n  if not stack or stack.pop()!=pairs[c]:ok=False;break\n else:stack.append(c)\nprint('YES' if ok and not stack else 'NO')",
"const s=require('fs').readFileSync(0,'utf8').trim(),st=[],p={')':'(',']':'[','}':'{'};let ok=true;for(const c of s){if(c in p){if(st.pop()!==p[c]){ok=false;break;}}else st.push(c);}console.log(ok&&!st.length?'YES':'NO');"),
item('Nearest Warmer Reading', 'For each reading, count how many later positions you must move to find a strictly greater reading. Use 0 when none exists.', 'One nonempty line of space-separated integers.', 'One distance per reading, in input order, separated by spaces.', '1 <= number of readings <= 100000; -1000000 <= reading <= 1000000.', ['monotonic stack','arrays'], 'Keep unresolved indices in a decreasing stack and resolve them when a greater reading arrives.',
['3 1 4 2','5 4 3','1 2 3','7','2 2 3','-3 -2 -1','1 1 1'],lambda s:' '.join(str(next((j-i for j in range(i+1,len(ints(s))) if ints(s)[j]>x),0)) for i,x in enumerate(ints(s))),
"import sys\na=list(map(int,sys.stdin.read().split()));ans=[0]*len(a);st=[]\nfor i,x in enumerate(a):\n while st and a[st[-1]]<x:\n  j=st.pop();ans[j]=i-j\n st.append(i)\nprint(*ans)",
"const a=require('fs').readFileSync(0,'utf8').trim().split(/\\s+/).map(Number),ans=a.map(()=>0),st=[];a.forEach((x,i)=>{while(st.length&&a[st[st.length-1]]<x){const j=st.pop();ans[j]=i-j;}st.push(i);});console.log(ans.join(' '));"),
item('Sorted Insertion Slot', 'Find the first position where a target can be inserted in a sorted list without breaking nondecreasing order.', 'First line: sorted integers, possibly empty. Second line: one target integer.', 'The zero-based insertion index, before any existing equal values.', '0 <= list length <= 100000; all values and target are between -1000000 and 1000000.', ['binary search','lower bound'], 'Binary-search the first position whose value is at least the target.',
['1 3 3 8\n3','1 4 9\n5','\n7','2\n1','2\n3','-5 -2 0\n-3','1 1 1\n1'],lambda s:__import__('bisect').bisect_left(ints(s.splitlines()[0]),int(s.splitlines()[1])),
"import sys,bisect\ns=sys.stdin.read().splitlines();print(bisect.bisect_left(list(map(int,s[0].split())),int(s[1])))",
"const s=require('fs').readFileSync(0,'utf8').split(/\\r?\\n/),a=s[0].trim()?s[0].trim().split(/\\s+/).map(Number):[],t=Number(s[1]);let l=0,r=a.length;while(l<r){const m=Math.floor((l+r)/2);if(a[m]<t)l=m+1;else r=m;}console.log(l);"),
item('Whole Square Root', 'Find the greatest nonnegative integer whose square does not exceed the given number.', 'One nonnegative integer n.', 'The floor of the square root of n.', '0 <= n <= 1000000000000. Use integer-safe arithmetic.', ['binary search','numeric bounds'], 'Search the monotonic boundary between candidate squares that fit and those that exceed the number.',
['0','1','15','16','999999999999','1000000000000','2'],lambda s:__import__('math').isqrt(int(s)),
"import sys,math\nprint(math.isqrt(int(sys.stdin.read())))",
"const n=BigInt(require('fs').readFileSync(0,'utf8').trim());let l=0n,r=n+1n;while(l+1n<r){const m=(l+r)/2n;if(m*m<=n)l=m;else r=m;}console.log(String(l));"),
item('One-or-Two Stair Routes', 'Count the ways to reach exactly step n when each move advances one or two steps. There is one empty route to step zero.', 'One integer n.', 'The number of distinct move sequences.', '0 <= n <= 40.', ['dynamic programming','recurrence'], 'The last move arrives from one or two steps earlier; combine those route counts with the zero-step base case.',
['0','1','4','2','3','10','40'],stairs,
"import sys\na=b=1\nfor _ in range(int(sys.stdin.read())):a,b=b,a+b\nprint(a)",
"const n=Number(require('fs').readFileSync(0,'utf8'));let a=1,b=1;for(let i=0;i<n;i++)[a,b]=[b,a+b];console.log(a);"),
item('Nonadjacent Reward Trail', 'Choose any readings as rewards without choosing neighboring positions. Maximize their sum. Choosing nothing is allowed.', 'One line of space-separated integer rewards, possibly empty.', 'The maximum obtainable sum.', '0 <= number of rewards <= 100000; -1000000 <= reward <= 1000000.', ['dynamic programming','take or skip'], 'At each position compare skipping it with taking it after the best solution two positions earlier.',
['2 7 9 3 1','-3 -2 -5','','5','5 1 5','1 2 3 4','0 0'],nonadjacent,
"import sys\na=b=0\nfor x in map(int,sys.stdin.read().split()):a,b=b,max(b,a+x)\nprint(b)",
"const s=require('fs').readFileSync(0,'utf8').trim();let a=0,b=0;for(const x of s?s.split(/\\s+/).map(Number):[])[a,b]=[b,Math.max(b,a+x)];console.log(b);"),
item('Connected Booking Blocks', 'Count merged blocks of closed intervals. Intervals touching at an endpoint belong to the same block.', 'Zero or more lines, each containing start and end integers. Each start is no greater than its end.', 'The number of connected blocks after merging all overlapping or touching intervals.', '0 <= interval count <= 100000; -1000000 <= start <= end <= 1000000.', ['sorting','interval merging'], 'Sort intervals by start, extend the current block across touching intervals, and count a new block only after a gap.',
['1 3\n3 5\n8 9','1 10\n2 3','','5 5','1 2\n4 5\n7 8','-4 -1\n-2 0','9 10\n1 2\n2 9'],intervals,
"import sys\na=sorted(tuple(map(int,l.split())) for l in sys.stdin.read().splitlines() if l.strip());count=0;end=None\nfor l,r in a:\n if end is None or l>end:count+=1\n end=r if end is None else max(end,r)\nprint(count)",
"const s=require('fs').readFileSync(0,'utf8').trim(),a=s?s.split(/\\r?\\n/).map(l=>l.trim().split(/\\s+/).map(Number)).sort((a,b)=>a[0]-b[0]||a[1]-b[1]):[];let count=0,end=null;for(const[l,r]of a){if(end===null||l>end)count++;end=end===null?r:Math.max(end,r);}console.log(count);")
]
