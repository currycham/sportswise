#!/usr/bin/env python3
"""Consistent SQLite backup, including WAL data. Call with source and destination paths."""
import os
import sqlite3
import sys
from pathlib import Path
if len(sys.argv)!=3:
    raise SystemExit('Usage: python deploy/backup.py <source.db> <destination.db>')
source,destination=map(Path,sys.argv[1:])
if not source.is_file() or source.resolve()==destination.resolve():
    raise SystemExit('Source must exist and destination must be different')
destination.parent.mkdir(parents=True,exist_ok=True)
os.umask(0o077)
with sqlite3.connect(f'file:{source}?mode=ro',uri=True) as src,sqlite3.connect(destination) as dst:
    src.backup(dst)
print('Backup complete')
