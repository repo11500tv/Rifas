"""Limitación de intentos persistente en SQLite, compartida por los procesos Gunicorn.
No registra contraseñas ni identificadores en claro.
"""
import hashlib
import sqlite3
import time
from flask import request
from platform_app import DB

SCHEMA = """CREATE TABLE IF NOT EXISTS auth_attempts (
 id INTEGER PRIMARY KEY,
 scope TEXT NOT NULL,
 key_hash TEXT NOT NULL,
 attempted_at INTEGER NOT NULL
);
CREATE INDEX IF NOT EXISTS ix_auth_attempts ON auth_attempts(scope,key_hash,attempted_at);
"""

def initialize_security():
    with sqlite3.connect(f'file:{DB}?mode=rw', uri=True, timeout=15) as c:
        c.executescript(SCHEMA)

def _keys(scope, identity):
    ip = (request.remote_addr or 'unknown')[:128]
    # The IP and identity buckets independently prevent both brute force and
    # credential stuffing. IP is the proxy-normalized remote address.
    return [hashlib.sha256(('ip:'+ip).encode()).hexdigest(),
            hashlib.sha256(('id:'+identity.lower()).encode()).hexdigest()]

def allow_attempt(scope, identity, max_attempts=5, window_seconds=900):
    cutoff=int(time.time())-window_seconds
    keys=_keys(scope,identity)
    with sqlite3.connect(f'file:{DB}?mode=rw',uri=True,timeout=15) as c:
        for key in keys:
            n=c.execute('SELECT COUNT(*) FROM auth_attempts WHERE scope=? AND key_hash=? AND attempted_at>=?',(scope,key,cutoff)).fetchone()[0]
            if n>=max_attempts: return False
    return True

def record_failure(scope, identity):
    now=int(time.time())
    with sqlite3.connect(f'file:{DB}?mode=rw',uri=True,timeout=15) as c:
        for key in _keys(scope,identity):
            c.execute('INSERT INTO auth_attempts(scope,key_hash,attempted_at) VALUES(?,?,?)',(scope,key,now))
        c.execute('DELETE FROM auth_attempts WHERE attempted_at<?',(now-86400,))

def clear_failures(scope, identity):
    # Successful authentication clears only the identity bucket, not the
    # shared IP bucket (to prevent bypass by rotating valid accounts).
    key=_keys(scope,identity)[1]
    with sqlite3.connect(f'file:{DB}?mode=rw',uri=True,timeout=15) as c:
        c.execute('DELETE FROM auth_attempts WHERE scope=? AND key_hash=?',(scope,key))
