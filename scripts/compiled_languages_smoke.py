"""Run trusted Java/C++ fixtures through the real isolated Docker runner."""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from judge.runner import execute

PROGRAMS = {
    'java': 'import java.util.*; public class Main { public static void main(String[] args) { Scanner sc = new Scanner(System.in); System.out.println(sc.nextLong() + sc.nextLong()); } }',
    'cpp': '#include <iostream>\nint main(){long long a,b; std::cin>>a>>b; std::cout<<a+b<<"\\n";}',
}

for language, source in PROGRAMS.items():
    result = execute(source, language, '2 3\n')
    assert result['verdict'] == 'AC' and result['output'].strip() == '5', (language, result)
    bad = execute('this is not valid source code', language, '')
    assert bad['verdict'] == 'CE', (language, bad)
    loop = ('public class Main { public static void main(String[] args) { while(true){} } }'
            if language == 'java' else 'int main(){while(true){}}')
    timed = execute(loop, language, '')
    assert timed['verdict'] == 'TLE', (language, timed)
    print(f'{language}: correct output, compilation error, and runtime timeout passed.', flush=True)
