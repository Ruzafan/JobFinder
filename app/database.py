import json
import os
import sqlite3
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Optional

try:
    import psycopg2
    import psycopg2.extras
    HAS_PSYCOPG2 = True
except ImportError:
    HAS_PSYCOPG2 = False


DATA_DIR = Path(os.getenv("JOBFINDER_DATA_DIR", Path(__file__).resolve().parent.parent / "data"))
DATA_DIR.mkdir(parents=True, exist_ok=True)
DB_PATH = DATA_DIR / "jobfinder.db"


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _normalize_topic(topic: str) -> str:
    return " ".join(topic.strip().lower().split())


def _get_database_url() -> str:
    url = (os.getenv("DATABASE_URL") or "").strip()
    if url.startswith("postgres://"):
        url = url.replace("postgres://", "postgresql://", 1)
    return url


class _PgCursorWrapper:
    def __init__(self, raw_cursor):
        self._cur = raw_cursor
        self.lastrowid = None

    def execute(self, query: str, params: Any = None):
        clean_q = query.strip().replace("?", "%s")
        upper_q = clean_q.upper()
        # In PostgreSQL, append RETURNING id to INSERT statements to populate lastrowid
        if upper_q.startswith("INSERT INTO") and "RETURNING" not in upper_q:
            clean_q = clean_q.rstrip("; ") + " RETURNING id;"
            if params is not None:
                self._cur.execute(clean_q, params)
            else:
                self._cur.execute(clean_q)
            try:
                row = self._cur.fetchone()
                if row:
                    self.lastrowid = row[0]
            except Exception:
                pass
            return self

        if params is not None:
            self._cur.execute(clean_q, params)
        else:
            self._cur.execute(clean_q)
        return self

    def executemany(self, query: str, seq_of_params: Any):
        clean_q = query.replace("?", "%s")
        return self._cur.executemany(clean_q, seq_of_params)

    def fetchone(self):
        return self._cur.fetchone()

    def fetchall(self):
        return self._cur.fetchall()

    def __iter__(self):
        return iter(self._cur)

    @property
    def rowcount(self):
        return self._cur.rowcount

    def __getattr__(self, name):
        return getattr(self._cur, name)


class _PgConnWrapper:
    def __init__(self, raw_conn):
        self._conn = raw_conn

    def cursor(self):
        raw_cur = self._conn.cursor(cursor_factory=psycopg2.extras.DictCursor)
        return _PgCursorWrapper(raw_cur)

    def execute(self, query: str, params: Any = None):
        cur = self.cursor()
        cur.execute(query, params)
        return cur

    def commit(self):
        return self._conn.commit()

    def rollback(self):
        return self._conn.rollback()

    def close(self):
        return self._conn.close()

    def executescript(self, script: str):
        with self._conn.cursor() as cur:
            cur.execute(script)
        self._conn.commit()


@contextmanager
def get_conn():
    db_url = _get_database_url()
    if db_url and HAS_PSYCOPG2:
        raw_conn = psycopg2.connect(db_url)
        conn = _PgConnWrapper(raw_conn)
        try:
            yield conn
            conn.commit()
        except Exception:
            conn.rollback()
            raise
        finally:
            conn.close()
    else:
        DATA_DIR.mkdir(parents=True, exist_ok=True)
        conn = sqlite3.connect(str(DB_PATH))
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA journal_mode=WAL;")
        conn.execute("PRAGMA foreign_keys=ON;")
        try:
            yield conn
            conn.commit()
        finally:
            conn.close()


def _migrate_from_sqlite_to_pg(pg_conn: _PgConnWrapper) -> None:
    """Safely seeds PostgreSQL from existing local SQLite database if Postgres is empty."""
    if not DB_PATH.exists():
        return
    try:
        sq_conn = sqlite3.connect(str(DB_PATH))
        sq_conn.row_factory = sqlite3.Row
        with sq_conn:
            # 1. Profiles
            profs = sq_conn.execute("SELECT * FROM cv_profiles").fetchall()
            for p in profs:
                pd = dict(p)
                pg_conn.execute(
                    """
                    INSERT INTO cv_profiles (id, profile_name, is_active, full_name, headline, raw_text, filename, updated_at)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                    ON CONFLICT(id) DO UPDATE SET
                        profile_name = EXCLUDED.profile_name,
                        is_active = EXCLUDED.is_active,
                        full_name = EXCLUDED.full_name,
                        headline = EXCLUDED.headline,
                        raw_text = EXCLUDED.raw_text,
                        filename = EXCLUDED.filename,
                        updated_at = EXCLUDED.updated_at
                    """,
                    (pd["id"], pd["profile_name"], pd["is_active"], pd["full_name"], pd["headline"], pd["raw_text"], pd["filename"], pd["updated_at"]),
                )
            # 2. Legacy cv_profile
            legacy = sq_conn.execute("SELECT * FROM cv_profile WHERE id = 1").fetchone()
            if legacy:
                ld = dict(legacy)
                pg_conn.execute(
                    """
                    INSERT INTO cv_profile (id, full_name, headline, raw_text, filename, updated_at)
                    VALUES (1, ?, ?, ?, ?, ?)
                    ON CONFLICT(id) DO UPDATE SET
                        full_name = EXCLUDED.full_name,
                        headline = EXCLUDED.headline,
                        raw_text = EXCLUDED.raw_text,
                        filename = EXCLUDED.filename,
                        updated_at = EXCLUDED.updated_at
                    """,
                    (ld["full_name"], ld["headline"], ld["raw_text"], ld["filename"], ld["updated_at"]),
                )
            # 3. Knowledge facts
            facts = sq_conn.execute("SELECT * FROM knowledge_facts").fetchall()
            for f in facts:
                fd = dict(f)
                pg_conn.execute(
                    """
                    INSERT INTO knowledge_facts (topic, topic_norm, category, status, details, source, created_at, updated_at)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                    ON CONFLICT(topic_norm) DO NOTHING
                    """,
                    (fd["topic"], fd["topic_norm"], fd["category"], fd["status"], fd["details"], fd["source"], fd["created_at"], fd["updated_at"]),
                )
            # 4. Search preferences
            prefs = sq_conn.execute("SELECT * FROM search_preferences WHERE id = 1").fetchone()
            if prefs:
                prd = dict(prefs)
                pg_conn.execute(
                    """
                    INSERT INTO search_preferences (id, target_roles_json, location, country, modality, experience_level, keywords_include_json, keywords_exclude_json, min_salary, preferred_sources_json, updated_at)
                    VALUES (1, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    ON CONFLICT(id) DO UPDATE SET
                        target_roles_json = EXCLUDED.target_roles_json,
                        location = EXCLUDED.location,
                        country = EXCLUDED.country,
                        modality = EXCLUDED.modality,
                        experience_level = EXCLUDED.experience_level,
                        keywords_include_json = EXCLUDED.keywords_include_json,
                        keywords_exclude_json = EXCLUDED.keywords_exclude_json,
                        min_salary = EXCLUDED.min_salary,
                        preferred_sources_json = EXCLUDED.preferred_sources_json,
                        updated_at = EXCLUDED.updated_at
                    """,
                    (prd["target_roles_json"], prd["location"], prd["country"], prd["modality"], prd["experience_level"], prd["keywords_include_json"], prd["keywords_exclude_json"], prd["min_salary"], prd["preferred_sources_json"], prd["updated_at"]),
                )
        sq_conn.close()
    except Exception:
        pass


def init_db() -> None:
    db_url = _get_database_url()
    if db_url and HAS_PSYCOPG2:
        with get_conn() as conn:
            conn.executescript(
                """
                CREATE TABLE IF NOT EXISTS cv_profile (
                    id INTEGER PRIMARY KEY CHECK (id = 1),
                    full_name TEXT NOT NULL DEFAULT '',
                    headline TEXT NOT NULL DEFAULT '',
                    raw_text TEXT NOT NULL DEFAULT '',
                    filename TEXT NOT NULL DEFAULT '',
                    updated_at TEXT NOT NULL
                );

                CREATE TABLE IF NOT EXISTS knowledge_facts (
                    id SERIAL PRIMARY KEY,
                    topic TEXT NOT NULL,
                    topic_norm TEXT NOT NULL UNIQUE,
                    category TEXT NOT NULL DEFAULT 'Habilidad técnica',
                    status TEXT NOT NULL DEFAULT 'confirmed',
                    details TEXT NOT NULL DEFAULT '',
                    source TEXT NOT NULL DEFAULT 'manual',
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL
                );

                CREATE TABLE IF NOT EXISTS job_analyses (
                    id SERIAL PRIMARY KEY,
                    job_title TEXT NOT NULL DEFAULT '',
                    company TEXT NOT NULL DEFAULT '',
                    source_url TEXT NOT NULL DEFAULT '',
                    raw_description TEXT NOT NULL DEFAULT '',
                    target_language TEXT NOT NULL DEFAULT 'auto',
                    match_score INTEGER NOT NULL DEFAULT 0,
                    ats_score INTEGER NOT NULL DEFAULT 0,
                    analysis_json TEXT NOT NULL DEFAULT '{}',
                    answers_json TEXT NOT NULL DEFAULT '[]',
                    adapted_cv_markdown TEXT NOT NULL DEFAULT '',
                    adapted_cv_structured_json TEXT NOT NULL DEFAULT '{}',
                    changelog_json TEXT NOT NULL DEFAULT '[]',
                    keywords_integrated_json TEXT NOT NULL DEFAULT '[]',
                    honesty_notes_json TEXT NOT NULL DEFAULT '[]',
                    provider_used TEXT NOT NULL DEFAULT 'local',
                    cover_letter_markdown TEXT NOT NULL DEFAULT '',
                    recruiter_pitch_text TEXT NOT NULL DEFAULT '',
                    interview_prep_json TEXT NOT NULL DEFAULT '{}',
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL
                );

                CREATE TABLE IF NOT EXISTS app_settings (
                    id INTEGER PRIMARY KEY CHECK (id = 1),
                    provider TEXT NOT NULL DEFAULT 'local',
                    api_key TEXT NOT NULL DEFAULT '',
                    model TEXT NOT NULL DEFAULT '',
                    base_url TEXT NOT NULL DEFAULT '',
                    default_language TEXT NOT NULL DEFAULT 'auto',
                    tone TEXT NOT NULL DEFAULT 'profesional y directo',
                    updated_at TEXT NOT NULL
                );

                CREATE TABLE IF NOT EXISTS search_preferences (
                    id INTEGER PRIMARY KEY CHECK (id = 1),
                    target_roles_json TEXT NOT NULL DEFAULT '[]',
                    location TEXT NOT NULL DEFAULT 'España',
                    country TEXT NOT NULL DEFAULT 'España',
                    modality TEXT NOT NULL DEFAULT 'all',
                    experience_level TEXT NOT NULL DEFAULT 'mid',
                    keywords_include_json TEXT NOT NULL DEFAULT '[]',
                    keywords_exclude_json TEXT NOT NULL DEFAULT '[]',
                    min_salary INTEGER DEFAULT NULL,
                    preferred_sources_json TEXT NOT NULL DEFAULT '["remotive", "arbeitnow", "web_boards"]',
                    updated_at TEXT NOT NULL
                );

                CREATE TABLE IF NOT EXISTS discovered_jobs (
                    id SERIAL PRIMARY KEY,
                    external_id TEXT NOT NULL DEFAULT '',
                    source TEXT NOT NULL DEFAULT 'web',
                    title TEXT NOT NULL,
                    company TEXT NOT NULL DEFAULT '',
                    location TEXT NOT NULL DEFAULT '',
                    country TEXT NOT NULL DEFAULT 'España',
                    modality TEXT NOT NULL DEFAULT 'onsite',
                    source_url TEXT NOT NULL UNIQUE,
                    description_snippet TEXT NOT NULL DEFAULT '',
                    raw_description TEXT NOT NULL DEFAULT '',
                    salary_text TEXT NOT NULL DEFAULT '',
                    match_score INTEGER NOT NULL DEFAULT 0,
                    match_reasons_json TEXT NOT NULL DEFAULT '[]',
                    missing_skills_json TEXT NOT NULL DEFAULT '[]',
                    status TEXT NOT NULL DEFAULT 'new',
                    published_at TEXT NOT NULL DEFAULT '',
                    discovered_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL
                );
                CREATE INDEX IF NOT EXISTS idx_discovered_jobs_score ON discovered_jobs(match_score DESC);
                CREATE INDEX IF NOT EXISTS idx_discovered_jobs_status ON discovered_jobs(status);

                CREATE TABLE IF NOT EXISTS cv_profiles (
                    id SERIAL PRIMARY KEY,
                    profile_name TEXT NOT NULL,
                    is_active INTEGER NOT NULL DEFAULT 0,
                    full_name TEXT NOT NULL DEFAULT '',
                    headline TEXT NOT NULL DEFAULT '',
                    raw_text TEXT NOT NULL DEFAULT '',
                    filename TEXT NOT NULL DEFAULT '',
                    updated_at TEXT NOT NULL
                );

                CREATE TABLE IF NOT EXISTS application_tracker (
                    id SERIAL PRIMARY KEY,
                    job_analysis_id INTEGER DEFAULT NULL,
                    discovered_job_id INTEGER DEFAULT NULL,
                    job_title TEXT NOT NULL,
                    company TEXT NOT NULL,
                    location TEXT NOT NULL DEFAULT '',
                    source_url TEXT NOT NULL DEFAULT '',
                    stage TEXT NOT NULL DEFAULT 'saved',
                    salary_discussed TEXT NOT NULL DEFAULT '',
                    contact_name TEXT NOT NULL DEFAULT '',
                    contact_email TEXT NOT NULL DEFAULT '',
                    notes TEXT NOT NULL DEFAULT '',
                    applied_at TEXT DEFAULT NULL,
                    next_followup_at TEXT DEFAULT NULL,
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL
                );
                CREATE INDEX IF NOT EXISTS idx_application_stage ON application_tracker(stage);

                CREATE TABLE IF NOT EXISTS job_digests (
                    id SERIAL PRIMARY KEY,
                    digest_date TEXT NOT NULL,
                    profile_id INTEGER DEFAULT NULL,
                    profile_name TEXT NOT NULL,
                    jobs_json TEXT NOT NULL DEFAULT '[]',
                    total_count INTEGER NOT NULL DEFAULT 0,
                    created_at TEXT NOT NULL
                );
                """
            )
            for col, col_type in [
                ("cover_letter_markdown", "TEXT NOT NULL DEFAULT ''"),
                ("recruiter_pitch_text", "TEXT NOT NULL DEFAULT ''"),
                ("interview_prep_json", "TEXT NOT NULL DEFAULT '{}'"),
            ]:
                try:
                    conn.execute(f"ALTER TABLE job_analyses ADD COLUMN IF NOT EXISTS {col} {col_type}")
                except Exception:
                    pass

            # Auto-seed settings if empty
            row = conn.execute("SELECT id FROM app_settings WHERE id = 1").fetchone()
            if not row:
                conn.execute(
                    """
                    INSERT INTO app_settings (id, provider, api_key, model, base_url, default_language, tone, updated_at)
                    VALUES (1, 'local', '', '', 'http://host.docker.internal:11434/v1', 'auto', 'profesional y directo', ?)
                    ON CONFLICT(id) DO NOTHING
                    """,
                    (_now_iso(),),
                )
            row = conn.execute("SELECT id FROM search_preferences WHERE id = 1").fetchone()
            if not row:
                conn.execute(
                    """
                    INSERT INTO search_preferences (id, target_roles_json, location, country, modality, experience_level, keywords_include_json, keywords_exclude_json, min_salary, preferred_sources_json, updated_at)
                    VALUES (1, '[]', 'España', 'España', 'all', 'mid', '[]', '[]', NULL, '["linkedin", "remotive", "jobicy"]', ?)
                    ON CONFLICT(id) DO NOTHING
                    """,
                    (_now_iso(),),
                )
            try:
                prof_count = conn.execute("SELECT COUNT(*) as c FROM cv_profiles").fetchone()["c"]
                if prof_count == 0 and DB_PATH.exists():
                    _migrate_from_sqlite_to_pg(conn)
            except Exception:
                pass
        return

    DATA_DIR.mkdir(parents=True, exist_ok=True)
    with get_conn() as conn:
        conn.executescript(
            """
            CREATE TABLE IF NOT EXISTS cv_profile (
                id INTEGER PRIMARY KEY CHECK (id = 1),
                full_name TEXT NOT NULL DEFAULT '',
                headline TEXT NOT NULL DEFAULT '',
                raw_text TEXT NOT NULL DEFAULT '',
                filename TEXT NOT NULL DEFAULT '',
                updated_at TEXT NOT NULL
            );

            CREATE TABLE IF NOT EXISTS knowledge_facts (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                topic TEXT NOT NULL,
                topic_norm TEXT NOT NULL UNIQUE,
                category TEXT NOT NULL DEFAULT 'Habilidad técnica',
                status TEXT NOT NULL DEFAULT 'confirmed',
                details TEXT NOT NULL DEFAULT '',
                source TEXT NOT NULL DEFAULT 'manual',
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL
            );

            CREATE TABLE IF NOT EXISTS job_analyses (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                job_title TEXT NOT NULL DEFAULT '',
                company TEXT NOT NULL DEFAULT '',
                source_url TEXT NOT NULL DEFAULT '',
                raw_description TEXT NOT NULL DEFAULT '',
                target_language TEXT NOT NULL DEFAULT 'auto',
                match_score INTEGER NOT NULL DEFAULT 0,
                ats_score INTEGER NOT NULL DEFAULT 0,
                analysis_json TEXT NOT NULL DEFAULT '{}',
                answers_json TEXT NOT NULL DEFAULT '[]',
                adapted_cv_markdown TEXT NOT NULL DEFAULT '',
                adapted_cv_structured_json TEXT NOT NULL DEFAULT '{}',
                changelog_json TEXT NOT NULL DEFAULT '[]',
                keywords_integrated_json TEXT NOT NULL DEFAULT '[]',
                honesty_notes_json TEXT NOT NULL DEFAULT '[]',
                provider_used TEXT NOT NULL DEFAULT 'local',
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL
            );

            CREATE TABLE IF NOT EXISTS app_settings (
                id INTEGER PRIMARY KEY CHECK (id = 1),
                provider TEXT NOT NULL DEFAULT 'local',
                api_key TEXT NOT NULL DEFAULT '',
                model TEXT NOT NULL DEFAULT '',
                base_url TEXT NOT NULL DEFAULT '',
                default_language TEXT NOT NULL DEFAULT 'auto',
                tone TEXT NOT NULL DEFAULT 'profesional y directo',
                updated_at TEXT NOT NULL
            );

            CREATE TABLE IF NOT EXISTS search_preferences (
                id INTEGER PRIMARY KEY CHECK (id = 1),
                target_roles_json TEXT NOT NULL DEFAULT '[]',
                location TEXT NOT NULL DEFAULT 'España',
                country TEXT NOT NULL DEFAULT 'España',
                modality TEXT NOT NULL DEFAULT 'all',
                experience_level TEXT NOT NULL DEFAULT 'mid',
                keywords_include_json TEXT NOT NULL DEFAULT '[]',
                keywords_exclude_json TEXT NOT NULL DEFAULT '[]',
                min_salary INTEGER DEFAULT NULL,
                preferred_sources_json TEXT NOT NULL DEFAULT '["remotive", "arbeitnow", "web_boards"]',
                updated_at TEXT NOT NULL
            );

            CREATE TABLE IF NOT EXISTS discovered_jobs (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                external_id TEXT NOT NULL DEFAULT '',
                source TEXT NOT NULL DEFAULT 'web',
                title TEXT NOT NULL,
                company TEXT NOT NULL DEFAULT '',
                location TEXT NOT NULL DEFAULT '',
                country TEXT NOT NULL DEFAULT 'España',
                modality TEXT NOT NULL DEFAULT 'onsite',
                source_url TEXT NOT NULL UNIQUE,
                description_snippet TEXT NOT NULL DEFAULT '',
                raw_description TEXT NOT NULL DEFAULT '',
                salary_text TEXT NOT NULL DEFAULT '',
                match_score INTEGER NOT NULL DEFAULT 0,
                match_reasons_json TEXT NOT NULL DEFAULT '[]',
                missing_skills_json TEXT NOT NULL DEFAULT '[]',
                status TEXT NOT NULL DEFAULT 'new',
                published_at TEXT NOT NULL DEFAULT '',
                discovered_at TEXT NOT NULL,
                updated_at TEXT NOT NULL
            );

            CREATE INDEX IF NOT EXISTS idx_discovered_jobs_score ON discovered_jobs(match_score DESC);
            CREATE INDEX IF NOT EXISTS idx_discovered_jobs_status ON discovered_jobs(status);

            CREATE TABLE IF NOT EXISTS cv_profiles (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                profile_name TEXT NOT NULL,
                is_active INTEGER NOT NULL DEFAULT 0,
                full_name TEXT NOT NULL DEFAULT '',
                headline TEXT NOT NULL DEFAULT '',
                raw_text TEXT NOT NULL DEFAULT '',
                filename TEXT NOT NULL DEFAULT '',
                updated_at TEXT NOT NULL
            );

            CREATE TABLE IF NOT EXISTS application_tracker (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                job_analysis_id INTEGER DEFAULT NULL,
                discovered_job_id INTEGER DEFAULT NULL,
                job_title TEXT NOT NULL,
                company TEXT NOT NULL,
                location TEXT NOT NULL DEFAULT '',
                source_url TEXT NOT NULL DEFAULT '',
                stage TEXT NOT NULL DEFAULT 'saved',
                salary_discussed TEXT NOT NULL DEFAULT '',
                contact_name TEXT NOT NULL DEFAULT '',
                contact_email TEXT NOT NULL DEFAULT '',
                notes TEXT NOT NULL DEFAULT '',
                applied_at TEXT DEFAULT NULL,
                next_followup_at TEXT DEFAULT NULL,
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL
            );
            CREATE INDEX IF NOT EXISTS idx_application_stage ON application_tracker(stage);

            CREATE TABLE IF NOT EXISTS job_digests (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                digest_date TEXT NOT NULL,
                profile_id INTEGER DEFAULT NULL,
                profile_name TEXT NOT NULL,
                jobs_json TEXT NOT NULL DEFAULT '[]',
                total_count INTEGER NOT NULL DEFAULT 0,
                created_at TEXT NOT NULL
            );
            """
        )

        try:
            conn.execute("ALTER TABLE search_preferences ADD COLUMN country TEXT NOT NULL DEFAULT 'España'")
        except Exception:
            pass
        try:
            conn.execute("ALTER TABLE discovered_jobs ADD COLUMN country TEXT NOT NULL DEFAULT 'España'")
        except Exception:
            pass

        # Job Analyses new columns: cover letter, recruiter pitch, interview prep
        for col, col_type in [
            ("cover_letter_markdown", "TEXT NOT NULL DEFAULT ''"),
            ("recruiter_pitch_text", "TEXT NOT NULL DEFAULT ''"),
            ("interview_prep_json", "TEXT NOT NULL DEFAULT '{}'"),
        ]:
            try:
                conn.execute(f"ALTER TABLE job_analyses ADD COLUMN {col} {col_type}")
            except Exception:
                pass

        # Auto-migrate legacy cv_profile row into cv_profiles if cv_profiles is empty
        try:
            prof_count = conn.execute("SELECT COUNT(*) as c FROM cv_profiles").fetchone()["c"]
            if prof_count == 0:
                legacy_cv = conn.execute("SELECT * FROM cv_profile WHERE id = 1").fetchone()
                if legacy_cv and legacy_cv["raw_text"]:
                    conn.execute(
                        """
                        INSERT INTO cv_profiles (id, profile_name, is_active, full_name, headline, raw_text, filename, updated_at)
                        VALUES (1, 'Perfil Principal', 1, ?, ?, ?, ?, ?)
                        """,
                        (
                            legacy_cv["full_name"],
                            legacy_cv["headline"],
                            legacy_cv["raw_text"],
                            legacy_cv["filename"],
                            legacy_cv["updated_at"],
                        ),
                    )
        except Exception:
            pass

        # Seed default settings from environment if table is empty
        row = conn.execute("SELECT id FROM app_settings WHERE id = 1").fetchone()
        if not row:
            env_provider = (os.getenv("AI_PROVIDER") or "").strip().lower()
            env_key = ""
            env_model = ""
            env_base = os.getenv("OLLAMA_BASE_URL", "http://host.docker.internal:11434/v1")

            if not env_provider:
                if os.getenv("GEMINI_API_KEY"):
                    env_provider = "gemini"
                    env_key = os.getenv("GEMINI_API_KEY", "")
                    env_model = "gemini-2.5-flash"
                elif os.getenv("OPENAI_API_KEY"):
                    env_provider = "openai"
                    env_key = os.getenv("OPENAI_API_KEY", "")
                    env_model = "gpt-4o-mini"
                elif os.getenv("ANTHROPIC_API_KEY"):
                    env_provider = "anthropic"
                    env_key = os.getenv("ANTHROPIC_API_KEY", "")
                    env_model = "claude-3-5-sonnet-latest"
                else:
                    env_provider = "local"
            else:
                if env_provider == "gemini":
                    env_key = os.getenv("GEMINI_API_KEY", "")
                    env_model = "gemini-2.5-flash"
                elif env_provider == "openai":
                    env_key = os.getenv("OPENAI_API_KEY", "")
                    env_model = "gpt-4o-mini"
                elif env_provider == "anthropic":
                    env_key = os.getenv("ANTHROPIC_API_KEY", "")
                    env_model = "claude-3-5-sonnet-latest"
                elif env_provider == "ollama":
                    env_model = "llama3.1"

            conn.execute(
                """
                INSERT INTO app_settings (id, provider, api_key, model, base_url, default_language, tone, updated_at)
                VALUES (1, ?, ?, ?, ?, 'auto', 'profesional y directo', ?)
                """,
                (env_provider, env_key, env_model, env_base, _now_iso()),
            )


# --- Multi-Profile CV Profiles ---

def list_cv_profiles() -> list[dict[str, Any]]:
    with get_conn() as conn:
        rows = conn.execute("SELECT * FROM cv_profiles ORDER BY is_active DESC, id ASC").fetchall()
        if not rows:
            legacy = conn.execute("SELECT * FROM cv_profile WHERE id = 1").fetchone()
            if legacy and legacy["raw_text"]:
                conn.execute(
                    """
                    INSERT INTO cv_profiles (id, profile_name, is_active, full_name, headline, raw_text, filename, updated_at)
                    VALUES (1, 'Perfil Principal', 1, ?, ?, ?, ?, ?)
                    ON CONFLICT(id) DO UPDATE SET
                        profile_name = EXCLUDED.profile_name,
                        is_active = EXCLUDED.is_active,
                        full_name = EXCLUDED.full_name,
                        headline = EXCLUDED.headline,
                        raw_text = EXCLUDED.raw_text,
                        filename = EXCLUDED.filename,
                        updated_at = EXCLUDED.updated_at
                    """,
                    (legacy["full_name"], legacy["headline"], legacy["raw_text"], legacy["filename"], legacy["updated_at"]),
                )
                rows = conn.execute("SELECT * FROM cv_profiles ORDER BY is_active DESC, id ASC").fetchall()
        return [dict(r) for r in rows]


def get_active_cv_profile() -> Optional[dict[str, Any]]:
    with get_conn() as conn:
        row = conn.execute("SELECT * FROM cv_profiles WHERE is_active = 1 LIMIT 1").fetchone()
        if not row:
            row = conn.execute("SELECT * FROM cv_profiles ORDER BY id ASC LIMIT 1").fetchone()
        if not row:
            legacy = conn.execute("SELECT * FROM cv_profile WHERE id = 1").fetchone()
            return dict(legacy) if legacy else None
        return dict(row)


def get_cv_profile(profile_id: Optional[int] = None) -> Optional[dict[str, Any]]:
    with get_conn() as conn:
        if profile_id:
            row = conn.execute("SELECT * FROM cv_profiles WHERE id = ?", (profile_id,)).fetchone()
            return dict(row) if row else None
        return get_active_cv_profile()


def create_cv_profile(
    profile_name: str,
    full_name: str = "",
    headline: str = "",
    raw_text: str = "",
    filename: str = "",
    set_active: bool = True,
) -> dict[str, Any]:
    now = _now_iso()
    name = profile_name.strip() or "Nuevo Perfil"
    with get_conn() as conn:
        if set_active:
            conn.execute("UPDATE cv_profiles SET is_active = 0")
        cur = conn.execute(
            """
            INSERT INTO cv_profiles (profile_name, is_active, full_name, headline, raw_text, filename, updated_at)
            VALUES (?, ?, ?, ?, ?, ?, ?)
            """,
            (name, 1 if set_active else 0, full_name.strip(), headline.strip(), raw_text.strip(), filename.strip(), now),
        )
        pid = cur.lastrowid
        if set_active:
            conn.execute(
                """
                INSERT INTO cv_profile (id, full_name, headline, raw_text, filename, updated_at)
                VALUES (1, ?, ?, ?, ?, ?)
                ON CONFLICT(id) DO UPDATE SET
                    full_name = excluded.full_name,
                    headline = excluded.headline,
                    raw_text = excluded.raw_text,
                    filename = excluded.filename,
                    updated_at = excluded.updated_at
                """,
                (full_name.strip(), headline.strip(), raw_text.strip(), filename.strip(), now),
            )
        row = conn.execute("SELECT * FROM cv_profiles WHERE id = ?", (pid,)).fetchone()
        return dict(row)


def update_cv_profile(
    profile_id: int,
    profile_name: Optional[str] = None,
    full_name: Optional[str] = None,
    headline: Optional[str] = None,
    raw_text: Optional[str] = None,
    filename: Optional[str] = None,
) -> Optional[dict[str, Any]]:
    now = _now_iso()
    with get_conn() as conn:
        existing = conn.execute("SELECT * FROM cv_profiles WHERE id = ?", (profile_id,)).fetchone()
        if not existing:
            return None
        new_name = profile_name.strip() if profile_name is not None else existing["profile_name"]
        new_full = full_name.strip() if full_name is not None else existing["full_name"]
        new_head = headline.strip() if headline is not None else existing["headline"]
        new_raw = raw_text.strip() if raw_text is not None else existing["raw_text"]
        new_file = filename.strip() if filename is not None else existing["filename"]

        conn.execute(
            """
            UPDATE cv_profiles
            SET profile_name = ?, full_name = ?, headline = ?, raw_text = ?, filename = ?, updated_at = ?
            WHERE id = ?
            """,
            (new_name, new_full, new_head, new_raw, new_file, now, profile_id),
        )
        if existing["is_active"]:
            conn.execute(
                """
                INSERT INTO cv_profile (id, full_name, headline, raw_text, filename, updated_at)
                VALUES (1, ?, ?, ?, ?, ?)
                ON CONFLICT(id) DO UPDATE SET
                    full_name = excluded.full_name,
                    headline = excluded.headline,
                    raw_text = excluded.raw_text,
                    filename = excluded.filename,
                    updated_at = excluded.updated_at
                """,
                (new_full, new_head, new_raw, new_file, now),
            )
        row = conn.execute("SELECT * FROM cv_profiles WHERE id = ?", (profile_id,)).fetchone()
        return dict(row) if row else None


def set_active_cv_profile(profile_id: int) -> Optional[dict[str, Any]]:
    now = _now_iso()
    with get_conn() as conn:
        existing = conn.execute("SELECT * FROM cv_profiles WHERE id = ?", (profile_id,)).fetchone()
        if not existing:
            return None
        conn.execute("UPDATE cv_profiles SET is_active = 0")
        conn.execute("UPDATE cv_profiles SET is_active = 1, updated_at = ? WHERE id = ?", (now, profile_id))
        conn.execute(
            """
            INSERT INTO cv_profile (id, full_name, headline, raw_text, filename, updated_at)
            VALUES (1, ?, ?, ?, ?, ?)
            ON CONFLICT(id) DO UPDATE SET
                full_name = excluded.full_name,
                headline = excluded.headline,
                raw_text = excluded.raw_text,
                filename = excluded.filename,
                updated_at = excluded.updated_at
            """,
            (existing["full_name"], existing["headline"], existing["raw_text"], existing["filename"], now),
        )
        row = conn.execute("SELECT * FROM cv_profiles WHERE id = ?", (profile_id,)).fetchone()
        return dict(row) if row else None


def delete_cv_profile(profile_id: int) -> bool:
    with get_conn() as conn:
        existing = conn.execute("SELECT * FROM cv_profiles WHERE id = ?", (profile_id,)).fetchone()
        if not existing:
            return False
        total = conn.execute("SELECT COUNT(*) as c FROM cv_profiles").fetchone()["c"]
        if total <= 1:
            return False
        cur = conn.execute("DELETE FROM cv_profiles WHERE id = ?", (profile_id,))
        if existing["is_active"]:
            next_p = conn.execute("SELECT id FROM cv_profiles ORDER BY id ASC LIMIT 1").fetchone()
            if next_p:
                set_active_cv_profile(next_p["id"])
        return cur.rowcount > 0


def save_cv_profile(full_name: str, headline: str, raw_text: str, filename: str = "", profile_id: Optional[int] = None) -> dict[str, Any]:
    now = _now_iso()
    with get_conn() as conn:
        target_id = profile_id
        if not target_id:
            active = conn.execute("SELECT id FROM cv_profiles WHERE is_active = 1 LIMIT 1").fetchone()
            target_id = active["id"] if active else None

        existing_file = ""
        if target_id:
            existing = conn.execute("SELECT filename FROM cv_profiles WHERE id = ?", (target_id,)).fetchone()
            existing_file = existing["filename"] if existing else ""
        else:
            legacy = conn.execute("SELECT filename FROM cv_profile WHERE id = 1").fetchone()
            existing_file = legacy["filename"] if legacy else ""

        final_filename = filename if filename else existing_file

        if target_id:
            conn.execute(
                """
                UPDATE cv_profiles
                SET full_name = ?, headline = ?, raw_text = ?, filename = ?, updated_at = ?
                WHERE id = ?
                """,
                (full_name.strip(), headline.strip(), raw_text.strip(), final_filename, now, target_id),
            )
        else:
            cur = conn.execute(
                """
                INSERT INTO cv_profiles (profile_name, is_active, full_name, headline, raw_text, filename, updated_at)
                VALUES ('Perfil Principal', 1, ?, ?, ?, ?, ?)
                """,
                (full_name.strip(), headline.strip(), raw_text.strip(), final_filename, now),
            )
            target_id = cur.lastrowid

        conn.execute(
            """
            INSERT INTO cv_profile (id, full_name, headline, raw_text, filename, updated_at)
            VALUES (1, ?, ?, ?, ?, ?)
            ON CONFLICT(id) DO UPDATE SET
                full_name = excluded.full_name,
                headline = excluded.headline,
                raw_text = excluded.raw_text,
                filename = excluded.filename,
                updated_at = excluded.updated_at
            """,
            (full_name.strip(), headline.strip(), raw_text.strip(), final_filename, now),
        )
        row = conn.execute("SELECT * FROM cv_profiles WHERE id = ?", (target_id,)).fetchone()
        return dict(row)


# --- Knowledge Base Facts ---

def list_knowledge_facts(status: Optional[str] = None, query: Optional[str] = None) -> list[dict[str, Any]]:
    sql = "SELECT * FROM knowledge_facts WHERE 1=1"
    params: list[Any] = []
    if status:
        sql += " AND status = ?"
        params.append(status)
    if query:
        q = f"%{query.strip().lower()}%"
        sql += " AND (LOWER(topic) LIKE ? OR LOWER(details) LIKE ? OR LOWER(category) LIKE ?)"
        params.extend([q, q, q])
    sql += " ORDER BY updated_at DESC, id DESC"
    with get_conn() as conn:
        rows = conn.execute(sql, params).fetchall()
        return [dict(r) for r in rows]


def upsert_knowledge_fact(
    topic: str,
    category: str = "Habilidad técnica",
    status: str = "confirmed",
    details: str = "",
    source: str = "manual",
) -> dict[str, Any]:
    now = _now_iso()
    clean_topic = topic.strip()
    norm = _normalize_topic(clean_topic)
    with get_conn() as conn:
        conn.execute(
            """
            INSERT INTO knowledge_facts (topic, topic_norm, category, status, details, source, created_at, updated_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(topic_norm) DO UPDATE SET
                topic = excluded.topic,
                category = excluded.category,
                status = excluded.status,
                details = CASE
                    WHEN excluded.details != '' THEN excluded.details
                    ELSE knowledge_facts.details
                END,
                source = excluded.source,
                updated_at = excluded.updated_at
            """,
            (clean_topic, norm, category.strip() or "Habilidad técnica", status, details.strip(), source, now, now),
        )
        row = conn.execute("SELECT * FROM knowledge_facts WHERE topic_norm = ?", (norm,)).fetchone()
        return dict(row)


def update_knowledge_fact(fact_id: int, updates: dict[str, Any]) -> Optional[dict[str, Any]]:
    with get_conn() as conn:
        existing = conn.execute("SELECT * FROM knowledge_facts WHERE id = ?", (fact_id,)).fetchone()
        if not existing:
            return None
        topic = updates.get("topic") if updates.get("topic") is not None else existing["topic"]
        category = updates.get("category") if updates.get("category") is not None else existing["category"]
        status = updates.get("status") if updates.get("status") is not None else existing["status"]
        details = updates.get("details") if updates.get("details") is not None else existing["details"]
        now = _now_iso()
        conn.execute(
            """
            UPDATE knowledge_facts
            SET topic = ?, topic_norm = ?, category = ?, status = ?, details = ?, updated_at = ?
            WHERE id = ?
            """,
            (topic.strip(), _normalize_topic(topic), category.strip(), status, details.strip(), now, fact_id),
        )
        row = conn.execute("SELECT * FROM knowledge_facts WHERE id = ?", (fact_id,)).fetchone()
        return dict(row)


def delete_knowledge_fact(fact_id: int) -> bool:
    with get_conn() as conn:
        cur = conn.execute("DELETE FROM knowledge_facts WHERE id = ?", (fact_id,))
        return cur.rowcount > 0


# --- Job Analyses ---

def _hydrate_job_row(row: Any) -> dict[str, Any]:
    data = dict(row)
    for col, key, default in [
        ("analysis_json", "analysis", {}),
        ("answers_json", "answers", []),
        ("adapted_cv_structured_json", "adapted_cv_structured", {}),
        ("changelog_json", "changelog", []),
        ("keywords_integrated_json", "keywords_integrated", []),
        ("honesty_notes_json", "honesty_notes", []),
        ("interview_prep_json", "interview_prep", {}),
    ]:
        try:
            val = data.pop(col, None)
            data[key] = json.loads(val or json.dumps(default))
        except Exception:
            data[key] = default
    if "cover_letter_markdown" not in data:
        data["cover_letter_markdown"] = ""
    if "recruiter_pitch_text" not in data:
        data["recruiter_pitch_text"] = ""
    return data


def create_job_analysis(
    job_title: str,
    company: str,
    source_url: str,
    raw_description: str,
    target_language: str,
    analysis: dict[str, Any],
    provider_used: str,
) -> dict[str, Any]:
    now = _now_iso()
    match_score = int(analysis.get("match_score", 0) or 0)
    ats_score = int(analysis.get("ats_score", match_score) or 0)
    with get_conn() as conn:
        cur = conn.execute(
            """
            INSERT INTO job_analyses (
                job_title, company, source_url, raw_description, target_language,
                match_score, ats_score, analysis_json, provider_used, created_at, updated_at
            )
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                job_title.strip() or analysis.get("job_title", "Oferta de empleo"),
                company.strip() or analysis.get("company", ""),
                source_url.strip(),
                raw_description.strip(),
                target_language,
                match_score,
                ats_score,
                json.dumps(analysis, ensure_ascii=False),
                provider_used,
                now,
                now,
            ),
        )
        row = conn.execute("SELECT * FROM job_analyses WHERE id = ?", (cur.lastrowid,)).fetchone()
        return _hydrate_job_row(row)


def update_job_analysis(
    job_id: int,
    *,
    analysis: Optional[dict[str, Any]] = None,
    answers: Optional[list[dict[str, Any]]] = None,
    adapted_cv_markdown: Optional[str] = None,
    adapted_cv_structured: Optional[dict[str, Any]] = None,
    changelog: Optional[list[Any]] = None,
    keywords_integrated: Optional[list[Any]] = None,
    honesty_notes: Optional[list[Any]] = None,
    cover_letter_markdown: Optional[str] = None,
    recruiter_pitch_text: Optional[str] = None,
    interview_prep: Optional[dict[str, Any]] = None,
    provider_used: Optional[str] = None,
    job_title: Optional[str] = None,
    company: Optional[str] = None,
) -> Optional[dict[str, Any]]:
    with get_conn() as conn:
        existing = conn.execute("SELECT * FROM job_analyses WHERE id = ?", (job_id,)).fetchone()
        if not existing:
            return None

        fields: list[str] = ["updated_at = ?"]
        values: list[Any] = [_now_iso()]

        if analysis is not None:
            fields.append("analysis_json = ?")
            values.append(json.dumps(analysis, ensure_ascii=False))
            fields.append("match_score = ?")
            values.append(int(analysis.get("match_score", existing["match_score"]) or 0))
            fields.append("ats_score = ?")
            values.append(int(analysis.get("ats_score", existing["ats_score"]) or 0))
        if answers is not None:
            fields.append("answers_json = ?")
            values.append(json.dumps(answers, ensure_ascii=False))
        if adapted_cv_markdown is not None:
            fields.append("adapted_cv_markdown = ?")
            values.append(adapted_cv_markdown)
        if adapted_cv_structured is not None:
            fields.append("adapted_cv_structured_json = ?")
            values.append(json.dumps(adapted_cv_structured, ensure_ascii=False))
        if changelog is not None:
            fields.append("changelog_json = ?")
            values.append(json.dumps(changelog, ensure_ascii=False))
        if keywords_integrated is not None:
            fields.append("keywords_integrated_json = ?")
            values.append(json.dumps(keywords_integrated, ensure_ascii=False))
        if honesty_notes is not None:
            fields.append("honesty_notes_json = ?")
            values.append(json.dumps(honesty_notes, ensure_ascii=False))
        if cover_letter_markdown is not None:
            fields.append("cover_letter_markdown = ?")
            values.append(cover_letter_markdown)
        if recruiter_pitch_text is not None:
            fields.append("recruiter_pitch_text = ?")
            values.append(recruiter_pitch_text)
        if interview_prep is not None:
            fields.append("interview_prep_json = ?")
            values.append(json.dumps(interview_prep, ensure_ascii=False))
        if provider_used is not None:
            fields.append("provider_used = ?")
            values.append(provider_used)
        if job_title is not None:
            fields.append("job_title = ?")
            values.append(job_title)
        if company is not None:
            fields.append("company = ?")
            values.append(company)

        values.append(job_id)
        conn.execute(f"UPDATE job_analyses SET {', '.join(fields)} WHERE id = ?", values)
        row = conn.execute("SELECT * FROM job_analyses WHERE id = ?", (job_id,)).fetchone()
        return _hydrate_job_row(row)


def get_job_analysis(job_id: int) -> Optional[dict[str, Any]]:
    with get_conn() as conn:
        row = conn.execute("SELECT * FROM job_analyses WHERE id = ?", (job_id,)).fetchone()
        return _hydrate_job_row(row) if row else None


def list_job_analyses(limit: int = 50) -> list[dict[str, Any]]:
    with get_conn() as conn:
        rows = conn.execute(
            """
            SELECT id, job_title, company, source_url, match_score, ats_score,
                   provider_used, created_at, updated_at,
                   CASE WHEN LENGTH(adapted_cv_markdown) > 0 THEN 1 ELSE 0 END AS has_adapted_cv
            FROM job_analyses
            ORDER BY updated_at DESC, id DESC
            LIMIT ?
            """,
            (limit,),
        ).fetchall()
        return [dict(r) for r in rows]


def delete_job_analysis(job_id: int) -> bool:
    with get_conn() as conn:
        cur = conn.execute("DELETE FROM job_analyses WHERE id = ?", (job_id,))
        return cur.rowcount > 0


# --- App Settings ---

def get_settings(mask_key: bool = False) -> dict[str, Any]:
    with get_conn() as conn:
        row = conn.execute("SELECT * FROM app_settings WHERE id = 1").fetchone()
        if not row:
            init_db()
            row = conn.execute("SELECT * FROM app_settings WHERE id = 1").fetchone()
        data = dict(row)
        raw_key = data.get("api_key", "")
        data["has_api_key"] = bool(raw_key)
        if mask_key:
            if len(raw_key) > 8:
                data["api_key_masked"] = f"{raw_key[:4]}••••{raw_key[-4:]}"
            elif raw_key:
                data["api_key_masked"] = "••••••••"
            else:
                data["api_key_masked"] = ""
            data.pop("api_key", None)
        return data


def save_settings(
    provider: str,
    api_key: Optional[str],
    model: str,
    base_url: str,
    default_language: str,
    tone: str,
) -> dict[str, Any]:
    with get_conn() as conn:
        existing = conn.execute("SELECT api_key FROM app_settings WHERE id = 1").fetchone()
        final_key = existing["api_key"] if (api_key is None and existing) else (api_key or "").strip()
        conn.execute(
            """
            UPDATE app_settings
            SET provider = ?, api_key = ?, model = ?, base_url = ?,
                default_language = ?, tone = ?, updated_at = ?
            WHERE id = 1
            """,
            (
                provider,
                final_key,
                model.strip(),
                base_url.strip(),
                default_language.strip() or "auto",
                tone.strip() or "profesional y directo",
                _now_iso(),
            ),
        )
    return get_settings(mask_key=True)


# --- Search Preferences ---

def _hydrate_preferences_row(row: Any) -> dict[str, Any]:
    if not row:
        return {}
    data = dict(row)
    if "country" not in data or not data["country"]:
        data["country"] = "España"
    for col, key, default in [
        ("target_roles_json", "target_roles", []),
        ("keywords_include_json", "keywords_include", []),
        ("keywords_exclude_json", "keywords_exclude", []),
        ("preferred_sources_json", "preferred_sources", ["remotive", "arbeitnow", "web_boards"]),
    ]:
        try:
            data[key] = json.loads(data.pop(col) or json.dumps(default))
        except Exception:
            data[key] = default
    return data


def get_search_preferences() -> dict[str, Any]:
    with get_conn() as conn:
        row = conn.execute("SELECT * FROM search_preferences WHERE id = 1").fetchone()
        if not row:
            now = _now_iso()
            conn.execute(
                """
                INSERT INTO search_preferences (
                    id, target_roles_json, location, country, modality, experience_level,
                    keywords_include_json, keywords_exclude_json, min_salary,
                    preferred_sources_json, updated_at
                )
                VALUES (1, '[]', 'España', 'España', 'all', 'mid', '[]', '[]', NULL, '["remotive", "arbeitnow", "web_boards"]', ?)
                """,
                (now,),
            )
            row = conn.execute("SELECT * FROM search_preferences WHERE id = 1").fetchone()
        return _hydrate_preferences_row(row)


def save_search_preferences(
    target_roles: list[str],
    location: str,
    country: str = "España",
    modality: str = "all",
    experience_level: str = "mid",
    keywords_include: list[str] = None,
    keywords_exclude: list[str] = None,
    min_salary: Optional[int] = None,
    preferred_sources: list[str] = None,
) -> dict[str, Any]:
    now = _now_iso()
    with get_conn() as conn:
        conn.execute(
            """
            INSERT INTO search_preferences (
                id, target_roles_json, location, country, modality, experience_level,
                keywords_include_json, keywords_exclude_json, min_salary,
                preferred_sources_json, updated_at
            )
            VALUES (1, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(id) DO UPDATE SET
                target_roles_json = excluded.target_roles_json,
                location = excluded.location,
                country = excluded.country,
                modality = excluded.modality,
                experience_level = excluded.experience_level,
                keywords_include_json = excluded.keywords_include_json,
                keywords_exclude_json = excluded.keywords_exclude_json,
                min_salary = excluded.min_salary,
                preferred_sources_json = excluded.preferred_sources_json,
                updated_at = excluded.updated_at
            """,
            (
                json.dumps(target_roles or [], ensure_ascii=False),
                location.strip() or "España",
                (country or "España").strip(),
                modality.strip() or "all",
                experience_level.strip() or "mid",
                json.dumps(keywords_include or [], ensure_ascii=False),
                json.dumps(keywords_exclude or [], ensure_ascii=False),
                min_salary,
                json.dumps(preferred_sources or [], ensure_ascii=False),
                now,
            ),
        )
        row = conn.execute("SELECT * FROM search_preferences WHERE id = 1").fetchone()
        return _hydrate_preferences_row(row)


# --- Discovered Jobs ---

def _hydrate_discovered_job(row: Any) -> dict[str, Any]:
    data = dict(row)
    if "country" not in data or not data["country"]:
        data["country"] = "España"
    for col, key, default in [
        ("match_reasons_json", "match_reasons", []),
        ("missing_skills_json", "missing_skills", []),
    ]:
        try:
            data[key] = json.loads(data.pop(col) or json.dumps(default))
        except Exception:
            data[key] = default
    return data


def save_discovered_jobs(jobs: list[dict[str, Any]]) -> dict[str, int]:
    now = _now_iso()
    inserted = 0
    updated = 0
    with get_conn() as conn:
        for job in jobs:
            url = (job.get("source_url") or "").strip()
            if not url or len(url) < 6:
                continue
            title = (job.get("title") or "").strip()
            if not title:
                continue

            existing = conn.execute(
                "SELECT id, status FROM discovered_jobs WHERE source_url = ?",
                (url,),
            ).fetchone()

            reasons_json = json.dumps(job.get("match_reasons") or [], ensure_ascii=False)
            missing_json = json.dumps(job.get("missing_skills") or [], ensure_ascii=False)
            score = int(job.get("match_score", 0) or 0)
            job_country = str(job.get("country") or "España").strip()

            if existing:
                # Do not revert 'dismissed' or 'saved' status on existing jobs
                conn.execute(
                    """
                    UPDATE discovered_jobs
                    SET title = ?, company = ?, location = ?, country = ?, modality = ?,
                        description_snippet = ?, raw_description = ?, salary_text = ?,
                        match_score = ?, match_reasons_json = ?, missing_skills_json = ?,
                        updated_at = ?
                    WHERE id = ?
                    """,
                    (
                        title,
                        (job.get("company") or "").strip(),
                        (job.get("location") or "").strip(),
                        job_country,
                        job.get("modality", "onsite"),
                        (job.get("description_snippet") or "")[:400],
                        (job.get("raw_description") or "")[:18000],
                        (job.get("salary_text") or "").strip(),
                        score,
                        reasons_json,
                        missing_json,
                        now,
                        existing["id"],
                    ),
                )
                updated += 1
            else:
                conn.execute(
                    """
                    INSERT INTO discovered_jobs (
                        external_id, source, title, company, location, country, modality,
                        source_url, description_snippet, raw_description, salary_text,
                        match_score, match_reasons_json, missing_skills_json, status,
                        published_at, discovered_at, updated_at
                    )
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 'new', ?, ?, ?)
                    """,
                    (
                        str(job.get("external_id") or ""),
                        str(job.get("source") or "web"),
                        title,
                        (job.get("company") or "").strip(),
                        (job.get("location") or "").strip(),
                        job_country,
                        job.get("modality", "onsite"),
                        url,
                        (job.get("description_snippet") or "")[:400],
                        (job.get("raw_description") or "")[:18000],
                        (job.get("salary_text") or "").strip(),
                        score,
                        reasons_json,
                        missing_json,
                        str(job.get("published_at") or ""),
                        now,
                        now,
                    ),
                )
                inserted += 1
    return {"inserted": inserted, "updated": updated, "total": inserted + updated}


def list_discovered_jobs(
    status: Optional[str] = None,
    min_score: int = 0,
    modality: Optional[str] = None,
    country: Optional[str] = None,
    query: Optional[str] = None,
    limit: int = 60,
) -> list[dict[str, Any]]:
    sql = "SELECT * FROM discovered_jobs WHERE match_score >= ?"
    params: list[Any] = [min_score]

    if status:
        sql += " AND status = ?"
        params.append(status)
    else:
        # By default exclude dismissed from the main feed
        sql += " AND status != 'dismissed'"

    if modality and modality != "all":
        sql += " AND modality = ?"
        params.append(modality)

    if country and country.strip().lower() not in ("global", "todas", "all", ""):
        c_norm = country.strip().lower()
        sql += " AND (LOWER(country) = ? OR LOWER(location) LIKE ? OR LOWER(location) LIKE '%worldwide%' OR LOWER(location) LIKE '%remoto%')"
        params.extend([c_norm, f"%{c_norm}%"])

    if query:
        q = f"%{query.strip().lower()}%"
        sql += " AND (LOWER(title) LIKE ? OR LOWER(company) LIKE ? OR LOWER(description_snippet) LIKE ?)"
        params.extend([q, q, q])

    sql += " ORDER BY match_score DESC, updated_at DESC LIMIT ?"
    params.append(limit)

    with get_conn() as conn:
        rows = conn.execute(sql, params).fetchall()
        return [_hydrate_discovered_job(r) for r in rows]


def get_discovered_job(job_id: int) -> Optional[dict[str, Any]]:
    with get_conn() as conn:
        row = conn.execute("SELECT * FROM discovered_jobs WHERE id = ?", (job_id,)).fetchone()
        return _hydrate_discovered_job(row) if row else None


def update_discovered_job_status(job_id: int, status: str) -> Optional[dict[str, Any]]:
    now = _now_iso()
    with get_conn() as conn:
        conn.execute(
            "UPDATE discovered_jobs SET status = ?, updated_at = ? WHERE id = ?",
            (status, now, job_id),
        )
        row = conn.execute("SELECT * FROM discovered_jobs WHERE id = ?", (job_id,)).fetchone()
        return _hydrate_discovered_job(row) if row else None


def delete_discovered_job(job_id: int) -> bool:
    with get_conn() as conn:
        cur = conn.execute("DELETE FROM discovered_jobs WHERE id = ?", (job_id,))
        return cur.rowcount > 0


def clear_discovered_jobs(status: Optional[str] = None) -> int:
    with get_conn() as conn:
        if status:
            cur = conn.execute("DELETE FROM discovered_jobs WHERE status = ?", (status,))
        else:
            cur = conn.execute("DELETE FROM discovered_jobs")
        return cur.rowcount


# --- Application Tracker ---

def list_applications(stage: Optional[str] = None, query: Optional[str] = None) -> list[dict[str, Any]]:
    sql = "SELECT * FROM application_tracker WHERE 1=1"
    params: list[Any] = []
    if stage and stage != "all":
        sql += " AND stage = ?"
        params.append(stage)
    if query:
        q = f"%{query.strip().lower()}%"
        sql += " AND (LOWER(job_title) LIKE ? OR LOWER(company) LIKE ? OR LOWER(notes) LIKE ?)"
        params.extend([q, q, q])
    sql += " ORDER BY updated_at DESC, id DESC"
    with get_conn() as conn:
        rows = conn.execute(sql, params).fetchall()
        return [dict(r) for r in rows]


def get_application(app_id: int) -> Optional[dict[str, Any]]:
    with get_conn() as conn:
        row = conn.execute("SELECT * FROM application_tracker WHERE id = ?", (app_id,)).fetchone()
        return dict(row) if row else None


def create_application(
    job_title: str,
    company: str,
    location: str = "",
    source_url: str = "",
    stage: str = "saved",
    salary_discussed: str = "",
    contact_name: str = "",
    contact_email: str = "",
    notes: str = "",
    applied_at: Optional[str] = None,
    next_followup_at: Optional[str] = None,
    job_analysis_id: Optional[int] = None,
    discovered_job_id: Optional[int] = None,
) -> dict[str, Any]:
    now = _now_iso()
    with get_conn() as conn:
        cur = conn.execute(
            """
            INSERT INTO application_tracker (
                job_analysis_id, discovered_job_id, job_title, company, location, source_url,
                stage, salary_discussed, contact_name, contact_email, notes,
                applied_at, next_followup_at, created_at, updated_at
            )
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                job_analysis_id,
                discovered_job_id,
                job_title.strip() or "Nueva Solicitud",
                company.strip() or "Empresa",
                location.strip(),
                source_url.strip(),
                stage.strip() or "saved",
                salary_discussed.strip(),
                contact_name.strip(),
                contact_email.strip(),
                notes.strip(),
                applied_at or (now if stage in ("applied", "interviewing", "offered") else None),
                next_followup_at,
                now,
                now,
            ),
        )
        row = conn.execute("SELECT * FROM application_tracker WHERE id = ?", (cur.lastrowid,)).fetchone()
        return dict(row)


def update_application(app_id: int, updates: dict[str, Any]) -> Optional[dict[str, Any]]:
    with get_conn() as conn:
        existing = conn.execute("SELECT * FROM application_tracker WHERE id = ?", (app_id,)).fetchone()
        if not existing:
            return None

        allowed = [
            "job_title", "company", "location", "source_url", "stage",
            "salary_discussed", "contact_name", "contact_email", "notes",
            "applied_at", "next_followup_at", "job_analysis_id", "discovered_job_id"
        ]
        fields = ["updated_at = ?"]
        values: list[Any] = [_now_iso()]

        for key in allowed:
            if key in updates:
                fields.append(f"{key} = ?")
                values.append(updates[key])

        values.append(app_id)
        conn.execute(f"UPDATE application_tracker SET {', '.join(fields)} WHERE id = ?", values)
        row = conn.execute("SELECT * FROM application_tracker WHERE id = ?", (app_id,)).fetchone()
        return dict(row)


def delete_application(app_id: int) -> bool:
    with get_conn() as conn:
        cur = conn.execute("DELETE FROM application_tracker WHERE id = ?", (app_id,))
        return cur.rowcount > 0


# --- Job Digest ---

def _hydrate_digest(row: Any) -> dict[str, Any]:
    data = dict(row)
    try:
        data["jobs"] = json.loads(data.pop("jobs_json", "[]") or "[]")
    except Exception:
        data["jobs"] = []
    return data


def save_digest(
    digest_date: str,
    profile_id: Optional[int],
    profile_name: str,
    jobs: list[dict[str, Any]],
) -> dict[str, Any]:
    now = _now_iso()
    with get_conn() as conn:
        cur = conn.execute(
            """
            INSERT INTO job_digests (digest_date, profile_id, profile_name, jobs_json, total_count, created_at)
            VALUES (?, ?, ?, ?, ?, ?)
            """,
            (
                digest_date,
                profile_id,
                profile_name or "Perfil Principal",
                json.dumps(jobs, ensure_ascii=False),
                len(jobs),
                now,
            ),
        )
        row = conn.execute("SELECT * FROM job_digests WHERE id = ?", (cur.lastrowid,)).fetchone()
        return _hydrate_digest(row)


def get_latest_digest(profile_id: Optional[int] = None) -> Optional[dict[str, Any]]:
    with get_conn() as conn:
        if profile_id:
            row = conn.execute(
                "SELECT * FROM job_digests WHERE profile_id = ? ORDER BY id DESC LIMIT 1",
                (profile_id,),
            ).fetchone()
        else:
            row = conn.execute("SELECT * FROM job_digests ORDER BY id DESC LIMIT 1").fetchone()
        return _hydrate_digest(row) if row else None


def list_digests(limit: int = 7) -> list[dict[str, Any]]:
    with get_conn() as conn:
        rows = conn.execute(
            "SELECT * FROM job_digests ORDER BY id DESC LIMIT ?",
            (limit,),
        ).fetchall()
        return [_hydrate_digest(r) for r in rows]


