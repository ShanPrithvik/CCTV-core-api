import os
import urllib.parse


def build_database_uri() -> str:
    """Build the SQLAlchemy URI from the current environment.

    Evaluated at app startup (not at import) so tests and runtime env changes
    are actually honored.
    """
    engine = os.getenv("DB_ENGINE", "sqlite").strip().lower()
    if engine == "mysql":
        user = os.getenv("DB_USER", "root")
        password = urllib.parse.quote(os.getenv("DB_PASSWORD", ""))
        host = os.getenv("DB_HOST", "localhost")
        port = os.getenv("DB_PORT", "3306")
        name = os.getenv("DB_NAME", "cctv_db")
        return f"mysql://{user}:{password}@{host}:{port}/{name}"

    sqlite_path = os.getenv("SQLITE_PATH", "cctv.db")
    if sqlite_path == ":memory:":
        return "sqlite://"
    return f"sqlite:///{sqlite_path}"


def sqlalchemy_engine_options() -> dict:
    engine = os.getenv("DB_ENGINE", "sqlite").strip().lower()
    options = {"pool_pre_ping": True}
    if engine != "mysql":
        options["connect_args"] = {"check_same_thread": False}
    return options


class DBConfig:
    SQLALCHEMY_TRACK_MODIFICATIONS = False
