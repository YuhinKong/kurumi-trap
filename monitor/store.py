import sqlite3
import json
from datetime import datetime, timezone
from .config import ROOT

class Store:
    def __init__(self, mode='real', path=None):
        from pathlib import Path
        self.path = Path(path) if path else ROOT / 'data' / f'{mode}.sqlite3'
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with self.connect() as db:
            db.executescript('''CREATE TABLE IF NOT EXISTS cache (key TEXT PRIMARY KEY, ts REAL, payload TEXT);
            CREATE TABLE IF NOT EXISTS events (id INTEGER PRIMARY KEY, ts TEXT, kind TEXT, payload TEXT);
            CREATE TABLE IF NOT EXISTS notified (key TEXT PRIMARY KEY);
            CREATE TABLE IF NOT EXISTS signal_keys (key TEXT PRIMARY KEY);''')
    def connect(self):
        db = sqlite3.connect(self.path, timeout=20)
        db.execute('PRAGMA journal_mode=WAL')
        return db
    def get(self, key):
        with self.connect() as db:
            r = db.execute('SELECT ts,payload FROM cache WHERE key=?',(key,)).fetchone()
        return (r[0],json.loads(r[1])) if r else None
    def put(self,key,payload):
        with self.connect() as db:
            db.execute('INSERT OR REPLACE INTO cache VALUES (?,?,?)',(key,datetime.now().timestamp(),json.dumps(payload,ensure_ascii=False,allow_nan=False)))
    def event(self,kind,payload):
        with self.connect() as db:
            db.execute('INSERT INTO events(ts,kind,payload) VALUES (?,?,?)',(datetime.now(timezone.utc).isoformat(),kind,json.dumps(payload,ensure_ascii=False,default=str)))
    def history(self,kind='scan'):
        with self.connect() as db:
            return [json.loads(r[0]) for r in db.execute('SELECT payload FROM events WHERE kind=? ORDER BY id DESC LIMIT 300',(kind,))]
    def claimed(self,key):
        with self.connect() as db:
            return db.execute('SELECT 1 FROM notified WHERE key=?',(key,)).fetchone() is not None
    def mark(self,key):
        with self.connect() as db:
            db.execute('INSERT OR IGNORE INTO notified VALUES (?)',(key,))

    def record_signal(self,key,row):
        with self.connect() as db:
            inserted=db.execute('INSERT OR IGNORE INTO signal_keys VALUES (?)',(key,)).rowcount
            if inserted:
                db.execute('INSERT INTO events(ts,kind,payload) VALUES (?,?,?)',(datetime.now(timezone.utc).isoformat(),'signal',json.dumps(row,ensure_ascii=False,default=str)))
