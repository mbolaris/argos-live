#!/usr/bin/env python3
"""Compile an explicit JSON definition to a new, validated assessment cartridge."""
import argparse
from pathlib import Path
import sqlite3
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'runtime'))
from argoslive.ability import decode
from argoslive.proctor import compile_cartridge
from argoslive.proctor.cartridge import MAX_BYTES


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('definition', type=Path)
    parser.add_argument('destination', type=Path)
    args = parser.parse_args()
    try:
        with args.definition.open('rb') as stream:
            data = stream.read(MAX_BYTES + 1)
        if len(data) > MAX_BYTES:
            raise ValueError('Definition exceeds cartridge limit')
        compile_cartridge(decode(data.decode('utf-8')), args.destination)
    except (ValueError, KeyError, TypeError, OSError, sqlite3.Error) as exc:
        parser.exit(1, f'Cannot compile cartridge: {exc}\n')


if __name__ == '__main__':
    main()
