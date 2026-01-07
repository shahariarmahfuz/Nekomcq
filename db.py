import os
from functools import lru_cache

try:
    from libsql_client import create_client
except ImportError:  # pragma: no cover
    create_client = None


class LibsqlDatabase:
    def __init__(self, url, auth_token):
        if not create_client:
            raise RuntimeError("libsql-client package is required.")
        self._client = create_client(url, auth_token=auth_token)

    def execute(self, sql, args=None):
        return self._client.execute(sql, args or [])

    def executemany(self, sql, args_list):
        return self._client.executemany(sql, args_list)

    def close(self):
        self._client.close()


@lru_cache(maxsize=1)
def _client():
    url = os.environ.get("DATABASE_URL", "")
    if not url:
        raise RuntimeError("DATABASE_URL must be set via environment variables.")
    if not url.startswith("libsql://"):
        raise RuntimeError("DATABASE_URL must be a libsql connection string.")
    auth_token = os.environ.get("DATABASE_AUTH_TOKEN")
    return LibsqlDatabase(url, auth_token)


def get_db():
    return _client()


def init_db():
    db = get_db()
    db.execute(
        "CREATE TABLE IF NOT EXISTS users ("
        "id INTEGER PRIMARY KEY AUTOINCREMENT,"
        "name TEXT NOT NULL,"
        "email TEXT UNIQUE NOT NULL,"
        "password_hash TEXT NOT NULL,"
        "created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP"
        ")"
    )
    db.execute(
        "CREATE TABLE IF NOT EXISTS subjects ("
        "id INTEGER PRIMARY KEY AUTOINCREMENT,"
        "name TEXT UNIQUE NOT NULL,"
        "created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP"
        ")"
    )
    db.execute(
        "CREATE TABLE IF NOT EXISTS import_batches ("
        "id INTEGER PRIMARY KEY AUTOINCREMENT,"
        "filename TEXT NOT NULL,"
        "created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP"
        ")"
    )
    db.execute(
        "CREATE TABLE IF NOT EXISTS mcqs ("
        "id INTEGER PRIMARY KEY AUTOINCREMENT,"
        "subject_id INTEGER NOT NULL,"
        "question TEXT NOT NULL,"
        "option_a TEXT NOT NULL,"
        "option_b TEXT NOT NULL,"
        "option_c TEXT NOT NULL,"
        "option_d TEXT NOT NULL,"
        "correct_option TEXT NOT NULL,"
        "batch_id INTEGER,"
        "created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,"
        "FOREIGN KEY(subject_id) REFERENCES subjects(id),"
        "FOREIGN KEY(batch_id) REFERENCES import_batches(id)"
        ")"
    )
    db.execute(
        "CREATE TABLE IF NOT EXISTS exam_attempts ("
        "id INTEGER PRIMARY KEY AUTOINCREMENT,"
        "user_id INTEGER NOT NULL,"
        "total_questions INTEGER NOT NULL,"
        "correct_count INTEGER NOT NULL,"
        "incorrect_count INTEGER NOT NULL,"
        "accuracy INTEGER NOT NULL,"
        "created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,"
        "FOREIGN KEY(user_id) REFERENCES users(id)"
        ")"
    )
