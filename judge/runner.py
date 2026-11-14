"""Docker-only execution. The worker controls Docker; submitted programs never do."""
import io
import tarfile
import time
import uuid
from datetime import datetime, timezone
import docker

OUTPUT_LIMIT = 65536
TIME_LIMIT = 3.0
MEMORY_MB = 128
LANGUAGES = {
    'python': ('python:3.12-slim', 'main.py', 'python -m py_compile /code/main.py', 'python /code/main.py'),
    'javascript': ('node:22-slim', 'main.js', 'node --check /code/main.js', 'node /code/main.js'),
}


class InfrastructureError(Exception):
    pass


def archive(files):
    stream = io.BytesIO()
    with tarfile.open(fileobj=stream, mode='w') as bundle:
        for name, content in files.items():
            data = content.encode('utf-8')
            item = tarfile.TarInfo(name)
            item.size = len(data)
            item.mode = 0o444
            bundle.addfile(item, io.BytesIO(data))
    return stream.getvalue()



def execute(code, language, input_data):
    if language not in LANGUAGES:
        raise InfrastructureError('Unsupported execution language.')
    image, filename, check, command = LANGUAGES[language]
    client = None
    container = None
    staging = None
    volume = None
    try:
        client = docker.from_env(timeout=5)
        # Pre-pull images during setup: requests never pull or execute locally.
        client.images.get(image)
        # Reap containers abandoned by hard-killed workers, without touching live jobs.
        for old in client.containers.list(all=True, filters={'label': 'benchcoder.runner=true'}):
            created = datetime.fromisoformat(old.attrs['Created'][:19] + '+00:00')
            if (datetime.now(timezone.utc) - created).total_seconds() > 600:
                old.remove(force=True)
        for old_volume in client.volumes.list(filters={'label': 'benchcoder.runner=true'}):
            created_at = old_volume.attrs.get('CreatedAt', '')
            if created_at:
                created = datetime.fromisoformat(created_at[:19] + '+00:00')
                if (datetime.now(timezone.utc) - created).total_seconds() > 600:
                    try:
                        old_volume.remove()
                    except docker.errors.DockerException:
                        pass
        script = f'{check} > /tmp/stdout 2> /tmp/stderr; result=$?; if [ $result -ne 0 ]; then result=120; else timeout -s KILL 3 {command} < /code/input > /tmp/stdout 2> /tmp/stderr; result=$?; fi; head -c 65537 /tmp/stdout; head -c 65537 /tmp/stderr >&2; exit $result'
        volume = client.volumes.create(labels={'benchcoder.runner': 'true'})
        staging = client.containers.create(image, ['true'], network_mode='none', read_only=True, volumes={volume.name: {'bind': '/code', 'mode': 'rw'}}, labels={'benchcoder.runner': 'true'})
        staging.put_archive('/code', archive({filename: code, 'input': input_data}))
        staging.remove(force=True)
        staging = None
        container = client.containers.create(
            image, ['sh', '-c', script], name='benchcoder-' + uuid.uuid4().hex,
            user='65534:65534', network_disabled=True, network_mode='none',
            read_only=True, cap_drop=['ALL'], security_opt=['no-new-privileges:true'],
            pids_limit=32, nano_cpus=1000000000, mem_limit=f'{MEMORY_MB}m',
            memswap_limit=f'{MEMORY_MB}m', tmpfs={'/tmp': 'rw,noexec,nosuid,size=16m,mode=1777'},
            environment={'PYTHONPYCACHEPREFIX': '/tmp/cache', 'PYTHONDONTWRITEBYTECODE': '1'},
            volumes={volume.name: {'bind': '/code', 'mode': 'ro'}},
            working_dir='/code', log_config=docker.types.LogConfig(type='json-file', config={'max-size': '1m', 'max-file': '1'}),
            labels={'benchcoder.runner': 'true'},
        )
        peak = 0
        container.start()
        started = time.monotonic()
        while True:
            container.reload()
            if container.status in ('exited', 'dead'):
                break
            if time.monotonic() - started > TIME_LIMIT:
                container.kill()
                return {'verdict': 'TLE', 'output': '', 'error': 'Time limit exceeded.', 'time': TIME_LIMIT, 'memory': peak / 1048576}
            stats = container.stats(stream=False, one_shot=True)
            memory = stats.get('memory_stats', {})
            peak = max(peak, memory.get('max_usage', 0), memory.get('usage', 0))
            time.sleep(0.05)
        elapsed = time.monotonic() - started
        state = container.attrs['State']
        output = container.logs(stdout=True, stderr=False).decode('utf-8', errors='replace')
        error = container.logs(stdout=False, stderr=True).decode('utf-8', errors='replace')
        verdict = 'AC'
        if state.get('OOMKilled'):
            verdict = 'MLE'
        elif len(output.encode('utf-8')) > OUTPUT_LIMIT or len(error.encode('utf-8')) > OUTPUT_LIMIT:
            verdict, error = 'RE', 'Output limit exceeded.'
        elif state.get('ExitCode') in (124, 137):
            verdict, error = 'TLE', 'Time limit exceeded.'
        elif state.get('ExitCode') == 120:
            verdict = 'CE'
        elif state.get('ExitCode') != 0:
            verdict = 'RE'
        return {'verdict': verdict, 'output': output[:OUTPUT_LIMIT], 'error': error[:OUTPUT_LIMIT], 'time': elapsed, 'memory': peak / 1048576 if peak else None}
    except docker.errors.DockerException as exc:
        raise InfrastructureError('Execution service is unavailable.') from exc
    finally:
        if container is not None:
            try:
                container.remove(force=True)
            except docker.errors.DockerException:
                pass
        if staging is not None:
            try:
                staging.remove(force=True)
            except docker.errors.DockerException:
                pass
        if volume is not None:
            try:
                volume.remove()
            except docker.errors.DockerException:
                pass
        if client is not None:
            client.close()
