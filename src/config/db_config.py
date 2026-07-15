import os
import urllib.parse


class DBConfig:
    """
    Defaults to a local SQLite file so the app runs with zero external
    dependencies (handy for a free/demo deployment). Set DB_ENGINE=mysql
    and the DB_* variables below to use MySQL instead.
    """

    DB_ENGINE = os.getenv("DB_ENGINE", "sqlite").strip().lower()

    if DB_ENGINE == "mysql":
        DB_USER = os.getenv("DB_USER", "root")
        DB_PASSWORD = os.getenv("DB_PASSWORD", "")
        DB_HOST = os.getenv("DB_HOST", "localhost")
        DB_PORT = os.getenv("DB_PORT", "3306")
        DB_NAME = os.getenv("DB_NAME", "cctv_db")

        _encoded_password = urllib.parse.quote(DB_PASSWORD)

        SQLALCHEMY_DATABASE_URI = (
            f"mysql://{DB_USER}:{_encoded_password}@{DB_HOST}:{DB_PORT}/{DB_NAME}"
        )
    else:
        SQLITE_PATH = os.getenv("SQLITE_PATH", "cctv.db")
        SQLALCHEMY_DATABASE_URI = f"sqlite:///{SQLITE_PATH}"

    SQLALCHEMY_TRACK_MODIFICATIONS = False
