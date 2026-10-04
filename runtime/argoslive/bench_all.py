"""Run speed and ability sequentially, preserving their separate identities."""
import argparse
import json
from pathlib import Path
import sys

from . import bench_ability, bench_speed
from .ollama import Client, OllamaError
from .results import DEFAULT, Store


def main(argv=None):
    parser = argparse.ArgumentParser(description='Run speed then original ability probes; code execution excluded.')
    parser.add_argument('--model', required=True)
    parser.add_argument('--suite', choices=['quick', 'standard'], default='quick')
    parser.add_argument('--size', action='append', choices=['short', 'medium', 'long'], help='Speed sizes; default all.')
    parser.add_argument('--ollama', default='http://127.0.0.1:11434')
    parser.add_argument('--timeout', type=int, default=120, help='API read timeout, 1–600 seconds.')
    parser.add_argument('--results-dir', type=Path, default=DEFAULT)
    parser.add_argument('--json', action='store_true')
    args = parser.parse_args(argv)
    if not 1 <= args.timeout <= 600:
        raise ValueError('Benchmark timeout must be between 1 and 600 seconds')
    client, store = Client(args.ollama, timeout=args.timeout), Store(args.results_dir)
    def speed_progress(value):
        if not args.json:
            print(f"Speed {value['size']}: {value['phase']}", file=sys.stderr, flush=True)
    def ability_progress(value):
        if not args.json and value['phase'] == 'scored':
            print(f"Ability {value['completed']}/{value['total']}: {value['elapsed_seconds']:.1f}s; "
                  f"ETA {value['eta_seconds']:.1f}s", file=sys.stderr, flush=True)
    try:
        speed = bench_speed.run(client, args.model, sizes=args.size or ('short', 'medium', 'long'), progress=speed_progress)
        speed_path = store.save(speed)
        if not args.json:
            print(f'Speed saved: {speed_path}', flush=True)
        ability = bench_ability.run(client, args.model, suite=args.suite, progress=ability_progress)
        ability_path = store.save(ability)
    except OllamaError as exc:
        raise ValueError('Combined benchmark backend failed; any already-saved speed run remains available.') from exc
    if args.json:
        print(json.dumps({'schema': 'argos-bench-batch/1', 'runs': [speed, ability]}, indent=2))
    else:
        print(f'Ability saved: {ability_path}')
        print(f"Ability {ability['state']}: {ability['summary']['correct']}/{ability['summary']['total']}; "
              f"{ability['summary']['format_errors']} format errors. Code execution excluded.")
    return 0 if ability['coverage']['complete'] else 130
