"""Ollama-only staged acquisition, exact verification and fixed reply acceptance."""
import argparse
import json
import os
import secrets
from pathlib import Path
import shutil

from . import model_verify as artifacts, storage
from .ollama import Cancelled, OllamaError
from .owned_ollama import owned, PIN
from .pull_jobs import Queue, Control, Progress, worker_lock, write_json, read_json, stamp


class OnboardingQueue(Queue):
    def run_verified(self, job_id, *, backend=owned, revision=artifacts.registry_revision,
                     free=lambda p: shutil.disk_usage(p).free, callback=None,
                     assistant_stopped=False):
        if not assistant_stopped:
            raise ValueError('Stop the assistant before model load testing; acknowledge --assistant-stopped')
        with worker_lock(self.root):
            job = self.get(job_id)
            if job['state'] != 'queued':
                raise ValueError('Queue or retry the job before running')
            entry = self.check(job)
            target = Path(job['storage']['path'])
            # Store-wide exclusion across cooperating queues/users.
            with worker_lock(target):
                control = Control(self, job_id)
                def save(state=None):
                    if state:
                        job['state'] = state
                    job['updated'] = stamp()
                    write_json(self.path(job_id), job)
                    if callback:
                        callback(json.loads(json.dumps(job)))
                def check():
                    self.check(job)
                    if control.is_set():
                        raise Cancelled('Model onboarding paused')
                try:
                    check()
                    # Refuse to replace a preexisting tag, even on a failed pull.
                    existing = artifacts.manifest_path(target, entry['tag'])
                    if existing.exists():
                        artifacts.check_manifest(artifacts.read_manifest(target, entry['tag']), entry)
                    revision(entry)  # Check mutable registry tag before any weight request.
                    staging = storage.safe_local(target / '.argos-pulls')
                    staging.mkdir(mode=0o700, exist_ok=True)
                    stage = storage.safe_local(staging / job_id)
                    stage.mkdir(mode=0o700, exist_ok=True)
                    # Reject linked contents before letting Ollama write into staging.
                    for path in stage.rglob('*'):
                        storage.safe_local(path)
                    if free(stage) < self.budget(entry, stage):
                        raise ValueError('Insufficient staging space')
                    # Publishing requires atomic hard links on this filesystem.
                    probe = stage / ('.link-source-' + secrets.token_hex(16))
                    linked = stage / (probe.name + '-linked')
                    try:
                        with probe.open('xb') as stream:
                            stream.write(b'argos')
                        os.link(probe, linked)
                    finally:
                        probe.unlink(missing_ok=True)
                        linked.unlink(missing_ok=True)
                    job.update(attempts=job['attempts'] + 1, error=None,
                               integrity_verified=False, inference_ready=False, reply_test=None)
                    progress = Progress(entry)
                    job['progress'] = progress.snapshot()
                    save('downloading')
                    with backend(stage) as client:
                        if client.version() != PIN:
                            raise ValueError('Backend version differs from pinned runtime')
                        def event(value):
                            check()
                            job['progress'] = progress.event(value)
                            save()
                        client.pull(entry['tag'], callback=event, cancel=control)
                        check()
                        save('verifying')
                        def verified(count):
                            check()
                            job['verification_bytes'] = count
                            save()
                        artifacts.verify(stage, entry, control, verified)
                        # Exact local manifest detects a registry tag race during pull.
                        job['integrity_verified'] = True
                        check()
                        save('loading')
                        metadata = client.show(entry['tag'])
                        if (metadata.get('details', {}).get('quantization_level') != entry['quantization']
                                or metadata.get('details', {}).get('family') != entry['family']):
                            raise ValueError('Loaded model metadata differs from catalog')
                        save('testing')
                        try:
                            reply = client.generate(entry['tag'], 'Reply with a short greeting.',
                                                    options={'num_ctx': 2048, 'num_predict': 32,
                                                             'temperature': 0, 'seed': 1},
                                                    think=False, keep_alive=0, cancel=control)
                            if not reply['text'].strip():
                                raise ValueError('Model did not produce a test reply')
                            final = reply['final']
                            counts = {}
                            for name in ('load_duration', 'prompt_eval_count', 'prompt_eval_duration',
                                         'eval_count', 'eval_duration'):
                                value = final.get(name)
                                counts[name] = value if type(value) is int and value >= 0 else None
                            job['reply_test'] = dict(counts, ollama_version=PIN, context_tokens=2048,
                                                     generation_limit=32,
                                                     time_to_first_token_seconds=reply['time_to_first_token_seconds'],
                                                     elapsed_seconds=reply['elapsed_seconds'],
                                                     text_reply_verified=True,
                                                     vision_verified=False, tools_verified=False,
                                                     performance_benchmark=False)
                        finally:
                            client.unload(entry['tag'])
                    # Stop daemon/runner writes BEFORE publishing into the real store.
                    check()
                    save('publishing')
                    artifacts.publish(stage, target, entry, control)
                    check()
                    job['progress']['bytes_done'] = entry['total_download_bytes']
                    job['progress']['artifact_bytes'] = {a['digest']: a['size'] for a in entry['artifacts']}
                    job['progress']['eta_seconds'] = 0
                    job.update(state='ready', inference_ready=True)
                except Cancelled:
                    job.update(state='cancelled' if control.action() == 'cancel' else 'paused', inference_ready=False)
                except OllamaError:
                    job.update(state='interrupted', inference_ready=False,
                               error='Backend operation interrupted; retry explicitly')
                except (OSError, ValueError):
                    job.update(state='failed', inference_ready=False,
                               error='Revision, storage, artifact or reply check failed')
                except KeyboardInterrupt:
                    job.update(state='paused', inference_ready=False)
                save()
                return job


def main(argv=None):
    parser = argparse.ArgumentParser(description='Verified catalog-model jobs; no agent activation.')
    parser.add_argument('--state', type=Path, default=Path.home() / '.config/argos-live/state.json')
    sub = parser.add_subparsers(dest='command', required=True)
    sub.add_parser('init')
    create = sub.add_parser('create')
    create.add_argument('tag')
    for action in ('status', 'pause', 'cancel', 'retry', 'run'):
        command = sub.add_parser(action)
        command.add_argument('id')
        if action == 'run':
            command.add_argument('--assistant-stopped', action='store_true')
    args = parser.parse_args(argv)
    state_path = storage.safe_local(args.state.absolute())
    configured = read_json(state_path)
    root = state_path.parent / 'pull-jobs'
    if args.command == 'init':
        storage.validate_configured(configured)
        Queue.initialize(root)
        print(json.dumps({'queue': str(root), 'initialized': True}))
        return 0
    queue = OnboardingQueue(root, configured)
    if args.command == 'create':
        result = queue.create(args.tag)
    elif args.command == 'status':
        result = queue.get(args.id)
    elif args.command in {'pause', 'cancel'}:
        queue.request(args.id, args.command)
        result = {'id': args.id, 'requested': args.command}
    elif args.command == 'retry':
        result = queue.retry(args.id)
    else:
        result = queue.run_verified(args.id, assistant_stopped=args.assistant_stopped,
                                    callback=lambda job: print(json.dumps(job), flush=True))
    print(json.dumps(result))
    return 0 if result.get('state') not in {'failed', 'interrupted'} else 1
