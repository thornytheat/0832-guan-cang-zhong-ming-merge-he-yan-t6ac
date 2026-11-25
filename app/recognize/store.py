"""互认事件与分组签发结论的 SQLite 账本。

写入在单个事务内完成：更正事件先入账并重算，随后才校验本次提交的签发
请求。因此同批提交的更正一旦影响目标组，携带旧版本号的签发结论立刻
失去资格，返回 STALE_RECOGNITION。事件所牵连组的既有结论按受影响范围
精确失效，未被波及的合格组结论保持有效。
"""

import json
import sqlite3
from contextlib import closing, contextmanager
from pathlib import Path

from app.recognize.domain import Registry, RecognitionError

SCHEMA = '''
CREATE TABLE IF NOT EXISTS rec_events (
    seq INTEGER PRIMARY KEY AUTOINCREMENT,
    payload TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS rec_signoffs (
    gid TEXT PRIMARY KEY,
    status TEXT NOT NULL,
    base_seq INTEGER NOT NULL,
    revision INTEGER NOT NULL DEFAULT 1,
    note TEXT NOT NULL DEFAULT ''
);
'''


class RecognitionStore:
    def __init__(self, path):
        self.path = Path(path)

    @contextmanager
    def connect(self):
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with closing(sqlite3.connect(self.path, timeout=15)) as db, db:
            db.row_factory = sqlite3.Row
            db.execute('PRAGMA foreign_keys=ON')
            db.executescript(SCHEMA)
            yield db

    # ------------------------------------------------------------ 事件回放
    @staticmethod
    def _replay(db):
        registry = Registry()
        for row in db.execute('SELECT payload FROM rec_events ORDER BY seq'):
            registry.apply(json.loads(row['payload']))
        return registry

    def registry(self):
        with self.connect() as db:
            return self._replay(db)

    def snapshot(self):
        with self.connect() as db:
            registry = self._replay(db)
            snapshot = registry.snapshot()
            snapshot['signoffs'] = self._signoff_rows(db)
        return snapshot

    @staticmethod
    def _signoff_rows(db):
        rows = db.execute('SELECT gid,status,base_seq,revision,note '
                          'FROM rec_signoffs ORDER BY gid').fetchall()
        return [dict(row) for row in rows]

    # ------------------------------------------------------------ 事件提交
    def admit(self, events):
        sequence, _ = self.submit(events, [])
        return sequence

    def submit(self, events, signoffs):
        """在一个事务内先记更正事件，再处理分组签发请求。

        返回 (最新事件序号, 本次成功签发的结论列表)。事件非法或任一签发
        请求失去资格时整体回滚，不产生部分写入。
        """
        if not isinstance(events, list) or not isinstance(signoffs, list):
            raise RecognitionError('RECOGNITION_FIELDS')
        if not events and not signoffs:
            raise RecognitionError('RECOGNITION_FIELDS')
        issued = []
        with self.connect() as db:
            registry = self._replay(db)
            for event in events:
                if not isinstance(event, dict):
                    raise RecognitionError('RECOGNITION_FIELDS')
                registry.apply(event)  # 领域校验失败时整个事务回滚
                touched = registry.affected_groups(event)
                db.execute('INSERT INTO rec_events(payload) VALUES (?)',
                           (json.dumps(event, ensure_ascii=False),))
                # 更正先入账：受牵连组的旧结论立即失去资格。
                db.executemany('DELETE FROM rec_signoffs WHERE gid=?',
                               [(gid,) for gid in sorted(touched)])
            for request in signoffs:
                issued.append(self._signoff(db, registry, request))
            sequence = registry.sequence
        return sequence, issued

    # ------------------------------------------------------------ 分组签发
    def signoff(self, values):
        _, issued = self.submit([], [values])
        return issued[0]

    def _signoff(self, db, registry, values):
        if not isinstance(values, dict):
            raise RecognitionError('RECOGNITION_FIELDS')
        gid = values.get('group')
        revision = values.get('revision')
        note = values.get('note', '')
        if not gid or type(revision) is not int or revision < 0 \
                or not isinstance(note, str) or not (3 <= len(note.strip()) <= 200):
            raise RecognitionError('RECOGNITION_FIELDS')
        if gid not in registry.groups:
            raise RecognitionError('GROUP_NOT_FOUND')
        current = db.execute('SELECT * FROM rec_signoffs WHERE gid=?', (gid,)).fetchone()
        expected_revision = 0 if current is None else current['revision']
        if revision != expected_revision:
            raise RecognitionError('STALE_RECOGNITION')
        if not registry.releasable([gid]):
            raise RecognitionError('GROUP_NOT_RELEASABLE')
        note = note.strip()
        if current is None:
            # 条件 INSERT 把并发首签的唯一约束竞争交给乐观锁，而非 IntegrityError。
            cursor = db.execute(
                'INSERT INTO rec_signoffs(gid,status,base_seq,revision,note) '
                'SELECT ?,?,?,1,? WHERE NOT EXISTS (SELECT 1 FROM rec_signoffs WHERE gid=?)',
                (gid, 'ISSUED', registry.sequence, note, gid))
            if cursor.rowcount != 1:
                raise RecognitionError('STALE_RECOGNITION')
        else:
            db.execute('UPDATE rec_signoffs SET status=?,base_seq=?,revision=revision+1,'
                       'note=? WHERE gid=?',
                       ('ISSUED', registry.sequence, note, gid))
        return self._load_signoff(db, gid)

    def _load_signoff(self, db, gid):
        row = db.execute('SELECT gid,status,base_seq,revision,note '
                         'FROM rec_signoffs WHERE gid=?', (gid,)).fetchone()
        return dict(row) if row else None

    def list_signoffs(self):
        with self.connect() as db:
            return self._signoff_rows(db)
