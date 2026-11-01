"""SQLite transactions serialize state changes. A revision prevents stale tabs overwriting data."""
import json
import sqlite3
from contextlib import contextmanager
from . import config


class Connection(sqlite3.Connection):
    def __exit__(self, *args):
        try:
            return super().__exit__(*args)
        finally:
            self.close()


def connect():
    c = sqlite3.connect(config.DB_PATH, timeout=15, factory=Connection)
    c.row_factory = sqlite3.Row
    c.execute('PRAGMA foreign_keys=ON')
    c.execute('PRAGMA busy_timeout=15000')
    return c


@contextmanager
def transaction():
    c = connect()
    try:
        c.execute('BEGIN IMMEDIATE')
        yield c
        c.commit()
    except BaseException:
        c.rollback()
        raise
    finally:
        c.close()


def init():
    config.DB_PATH.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    with connect() as c:
        config.DB_PATH.chmod(0o600)
        c.execute('PRAGMA journal_mode=WAL')
        c.executescript('''
        CREATE TABLE IF NOT EXISTS users (
          id TEXT PRIMARY KEY, email TEXT UNIQUE, role TEXT DEFAULT 'user',
          demo INTEGER DEFAULT 0, created_at TEXT DEFAULT CURRENT_TIMESTAMP,
          last_seen_at TEXT, state TEXT NOT NULL, revision INTEGER DEFAULT 0);
        CREATE TABLE IF NOT EXISTS sessions (
          token TEXT PRIMARY KEY, user_id TEXT REFERENCES users(id) ON DELETE CASCADE,
          expires_at TEXT NOT NULL);
        CREATE TABLE IF NOT EXISTS login_codes (
          email TEXT PRIMARY KEY, hash TEXT NOT NULL, expires_at REAL NOT NULL,
          sent_at REAL NOT NULL, tries INTEGER DEFAULT 0);
        CREATE TABLE IF NOT EXISTS auth_limits (ip TEXT PRIMARY KEY, at REAL, count INTEGER);
        CREATE TABLE IF NOT EXISTS proposals (
          id TEXT PRIMARY KEY, user_id TEXT REFERENCES users(id) ON DELETE CASCADE,
          revision INTEGER, payload TEXT, created_at TEXT DEFAULT CURRENT_TIMESTAMP);
        CREATE TABLE IF NOT EXISTS notices (
          id TEXT PRIMARY KEY, user_id TEXT REFERENCES users(id) ON DELETE CASCADE,
          kind TEXT, title TEXT, body TEXT, period TEXT, created_at TEXT DEFAULT CURRENT_TIMESTAMP,
          read INTEGER DEFAULT 0);
        CREATE TABLE IF NOT EXISTS deliveries (
          id TEXT PRIMARY KEY, user_id TEXT REFERENCES users(id) ON DELETE CASCADE,
          status TEXT, attempts INTEGER DEFAULT 0, error TEXT,
          updated_at TEXT DEFAULT CURRENT_TIMESTAMP);
        CREATE TABLE IF NOT EXISTS llm_usage (
          id INTEGER PRIMARY KEY, task TEXT, actor TEXT,
          prompt_tokens INTEGER DEFAULT 0, cached_tokens INTEGER DEFAULT 0,
          completion_tokens INTEGER DEFAULT 0, cost REAL DEFAULT 0,
          at TEXT DEFAULT CURRENT_TIMESTAMP);
        ''')


def read_user(uid):
    with connect() as c:
        row = c.execute('SELECT * FROM users WHERE id=?', (uid,)).fetchone()
        return dict(row) if row else None


def decode(row):
    return json.loads(row['state'])


def save(c, uid, state, revision):
    result = c.execute('UPDATE users SET state=?, revision=revision+1 WHERE id=? AND revision=?',
                       (json.dumps(state, ensure_ascii=False), uid, revision))
    if result.rowcount != 1:
        raise ValueError('数据已更新，请刷新后重试')
