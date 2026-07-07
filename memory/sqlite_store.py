"""Persistência SQLite (seção 11): schema versionado, WAL, FKs ativadas.

Migração 1: schema base (MVP). Migração 2 (V1): FTS5 sincronizado por
triggers + tabela de estado de indexação vetorial (indexed_files).
"""

from __future__ import annotations

import sqlite3
from pathlib import Path

SCHEMA_V1 = """
CREATE TABLE projects (
    id INTEGER PRIMARY KEY,
    name TEXT NOT NULL,
    path TEXT NOT NULL UNIQUE,
    created_at TEXT NOT NULL DEFAULT (datetime('now'))
);

CREATE TABLE files (
    id INTEGER PRIMARY KEY,
    project_id INTEGER NOT NULL REFERENCES projects(id) ON DELETE CASCADE,
    path TEXT NOT NULL,
    hash TEXT NOT NULL,
    last_modified TEXT NOT NULL,
    UNIQUE(project_id, path)
);

CREATE TABLE interactions (
    id INTEGER PRIMARY KEY,
    project_id INTEGER REFERENCES projects(id),
    timestamp TEXT NOT NULL DEFAULT (datetime('now')),
    task_type TEXT NOT NULL,
    provider TEXT NOT NULL,
    model TEXT NOT NULL,
    prompt TEXT NOT NULL,          -- já redigido (sem segredos)
    response TEXT,
    input_tokens INTEGER,
    output_tokens INTEGER,
    duration_ms INTEGER,
    cost_estimate REAL DEFAULT 0,
    confidence REAL,
    status TEXT NOT NULL,          -- ok|parse_error|provider_error|rejected|approved
    git_branch TEXT
);
CREATE INDEX idx_interactions_project_ts ON interactions(project_id, timestamp);

CREATE TABLE interaction_files (
    interaction_id INTEGER NOT NULL REFERENCES interactions(id) ON DELETE CASCADE,
    file_id INTEGER NOT NULL REFERENCES files(id),
    PRIMARY KEY (interaction_id, file_id)
);

CREATE TABLE tags (
    id INTEGER PRIMARY KEY,
    name TEXT NOT NULL UNIQUE
);

CREATE TABLE interaction_tags (
    interaction_id INTEGER NOT NULL REFERENCES interactions(id) ON DELETE CASCADE,
    tag_id INTEGER NOT NULL REFERENCES tags(id),
    PRIMARY KEY (interaction_id, tag_id)
);

CREATE TABLE commits (
    id INTEGER PRIMARY KEY,
    project_id INTEGER NOT NULL REFERENCES projects(id),
    interaction_id INTEGER REFERENCES interactions(id),
    hash TEXT NOT NULL,
    branch TEXT,
    message TEXT,
    timestamp TEXT NOT NULL DEFAULT (datetime('now'))
);
"""

SCHEMA_V2 = """
-- Busca textual complementar à vetorial (busca híbrida completa na V2)
CREATE VIRTUAL TABLE interactions_fts USING fts5(
    prompt, response, content='interactions', content_rowid='id'
);

-- Triggers mantêm o FTS sincronizado com interactions
CREATE TRIGGER interactions_fts_ai AFTER INSERT ON interactions BEGIN
    INSERT INTO interactions_fts(rowid, prompt, response)
    VALUES (new.id, new.prompt, new.response);
END;
CREATE TRIGGER interactions_fts_ad AFTER DELETE ON interactions BEGIN
    INSERT INTO interactions_fts(interactions_fts, rowid, prompt, response)
    VALUES ('delete', old.id, old.prompt, old.response);
END;
CREATE TRIGGER interactions_fts_au AFTER UPDATE ON interactions BEGIN
    INSERT INTO interactions_fts(interactions_fts, rowid, prompt, response)
    VALUES ('delete', old.id, old.prompt, old.response);
    INSERT INTO interactions_fts(rowid, prompt, response)
    VALUES (new.id, new.prompt, new.response);
END;

-- Backfill do que já existe
INSERT INTO interactions_fts(rowid, prompt, response)
SELECT id, prompt, response FROM interactions;

-- Estado da indexação vetorial (invalidação por hash — seção 12)
CREATE TABLE indexed_files (
    project_id INTEGER NOT NULL REFERENCES projects(id) ON DELETE CASCADE,
    path TEXT NOT NULL,
    hash TEXT NOT NULL,
    chunks INTEGER NOT NULL,
    embedding_model TEXT NOT NULL,
    indexed_at TEXT NOT NULL DEFAULT (datetime('now')),
    PRIMARY KEY (project_id, path)
);
"""

# Colunas que podem ser atualizadas após o registro inicial
_UPDATABLE = {"status", "confidence", "response", "cost_estimate", "input_tokens", "output_tokens", "duration_ms"}


class SQLiteStore:
    MIGRATIONS: dict[int, str] = {1: SCHEMA_V1, 2: SCHEMA_V2}

    def __init__(self, db_path: Path | str):
        db_path = Path(db_path)
        db_path.parent.mkdir(parents=True, exist_ok=True)
        self.conn = sqlite3.connect(str(db_path))
        self.conn.row_factory = sqlite3.Row
        self.conn.execute("PRAGMA foreign_keys = ON")
        self.conn.execute("PRAGMA journal_mode = WAL")
        self._migrate()

    def _migrate(self) -> None:
        exists = self.conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table' AND name='schema_version'"
        ).fetchone()
        if exists is None:
            self.conn.execute("CREATE TABLE schema_version (version INTEGER NOT NULL)")
            self.conn.execute("INSERT INTO schema_version VALUES (0)")
            self.conn.commit()
        current = self.conn.execute("SELECT version FROM schema_version").fetchone()[0]
        for version in sorted(self.MIGRATIONS):
            if version > current:
                self.conn.executescript(self.MIGRATIONS[version])
                self.conn.execute("UPDATE schema_version SET version = ?", (version,))
                self.conn.commit()

    # --- projetos -----------------------------------------------------------

    def get_or_create_project(self, name: str, path: str) -> int:
        row = self.conn.execute("SELECT id FROM projects WHERE path = ?", (path,)).fetchone()
        if row:
            return row["id"]
        cur = self.conn.execute(
            "INSERT INTO projects (name, path) VALUES (?, ?)", (name, path)
        )
        self.conn.commit()
        return cur.lastrowid

    # --- interações ---------------------------------------------------------

    def record_interaction(
        self,
        *,
        project_id: int | None,
        task_type: str,
        provider: str,
        model: str,
        prompt: str,
        response: str | None = None,
        input_tokens: int | None = None,
        output_tokens: int | None = None,
        duration_ms: int | None = None,
        cost_estimate: float = 0.0,
        confidence: float | None = None,
        status: str = "ok",
        git_branch: str | None = None,
    ) -> int:
        cur = self.conn.execute(
            """INSERT INTO interactions
               (project_id, task_type, provider, model, prompt, response,
                input_tokens, output_tokens, duration_ms, cost_estimate,
                confidence, status, git_branch)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (
                project_id, task_type, provider, model, prompt, response,
                input_tokens, output_tokens, duration_ms, cost_estimate,
                confidence, status, git_branch,
            ),
        )
        self.conn.commit()
        return cur.lastrowid

    def update_interaction(self, interaction_id: int, **fields) -> None:
        invalid = set(fields) - _UPDATABLE
        if invalid:
            raise ValueError(f"Colunas não atualizáveis: {invalid}")
        if not fields:
            return
        assignments = ", ".join(f"{col} = ?" for col in fields)
        self.conn.execute(
            f"UPDATE interactions SET {assignments} WHERE id = ?",
            (*fields.values(), interaction_id),
        )
        self.conn.commit()

    def get_interaction(self, interaction_id: int) -> dict | None:
        row = self.conn.execute(
            "SELECT * FROM interactions WHERE id = ?", (interaction_id,)
        ).fetchone()
        return dict(row) if row else None

    def last_interaction_id(self, project_id: int | None = None) -> int | None:
        if project_id is None:
            row = self.conn.execute("SELECT MAX(id) AS m FROM interactions").fetchone()
        else:
            row = self.conn.execute(
                "SELECT MAX(id) AS m FROM interactions WHERE project_id = ?", (project_id,)
            ).fetchone()
        return row["m"]

    def history(
        self,
        project: str | None = None,
        tag: str | None = None,
        limit: int = 20,
    ) -> list[dict]:
        query = """
            SELECT i.*, p.name AS project_name
            FROM interactions i
            LEFT JOIN projects p ON p.id = i.project_id
            WHERE 1=1
        """
        params: list = []
        if project:
            query += " AND p.name = ?"
            params.append(project)
        if tag:
            query += """ AND EXISTS (
                SELECT 1 FROM interaction_tags it
                JOIN tags t ON t.id = it.tag_id
                WHERE it.interaction_id = i.id AND t.name = ?
            )"""
            params.append(tag)
        query += " ORDER BY i.id DESC LIMIT ?"
        params.append(limit)
        return [dict(r) for r in self.conn.execute(query, params).fetchall()]

    # --- arquivos -----------------------------------------------------------

    def upsert_file(self, project_id: int, rel_path: str, file_hash: str) -> int:
        self.conn.execute(
            """INSERT INTO files (project_id, path, hash, last_modified)
               VALUES (?, ?, ?, datetime('now'))
               ON CONFLICT(project_id, path)
               DO UPDATE SET hash = excluded.hash, last_modified = excluded.last_modified""",
            (project_id, rel_path, file_hash),
        )
        self.conn.commit()
        row = self.conn.execute(
            "SELECT id FROM files WHERE project_id = ? AND path = ?",
            (project_id, rel_path),
        ).fetchone()
        return row["id"]

    def link_interaction_file(self, interaction_id: int, file_id: int) -> None:
        self.conn.execute(
            "INSERT OR IGNORE INTO interaction_files (interaction_id, file_id) VALUES (?, ?)",
            (interaction_id, file_id),
        )
        self.conn.commit()

    # --- busca textual (FTS5) -------------------------------------------------

    def fts_search(self, query: str, project: str | None = None, limit: int = 10) -> list[dict]:
        """Busca por palavra-chave em prompts/respostas, ordenada por relevância BM25."""
        sql = """
            SELECT i.*, p.name AS project_name, bm25(interactions_fts) AS rank
            FROM interactions_fts f
            JOIN interactions i ON i.id = f.rowid
            LEFT JOIN projects p ON p.id = i.project_id
            WHERE interactions_fts MATCH ?
        """
        params: list = [query]
        if project:
            sql += " AND p.name = ?"
            params.append(project)
        sql += " ORDER BY rank LIMIT ?"
        params.append(limit)
        try:
            return [dict(r) for r in self.conn.execute(sql, params).fetchall()]
        except sqlite3.OperationalError:
            # Query com sintaxe inválida para o FTS5 (aspas, operadores soltos…):
            # tenta de novo com o texto entre aspas, como frase literal
            escaped = '"' + query.replace('"', '""') + '"'
            params[0] = escaped
            return [dict(r) for r in self.conn.execute(sql, params).fetchall()]

    # --- estado de indexação vetorial ------------------------------------------

    def indexed_hash(self, project_id: int, rel_path: str) -> str | None:
        row = self.conn.execute(
            "SELECT hash FROM indexed_files WHERE project_id = ? AND path = ?",
            (project_id, rel_path),
        ).fetchone()
        return row["hash"] if row else None

    def mark_indexed(
        self, project_id: int, rel_path: str, file_hash: str, chunks: int, embedding_model: str
    ) -> None:
        self.conn.execute(
            """INSERT INTO indexed_files (project_id, path, hash, chunks, embedding_model, indexed_at)
               VALUES (?, ?, ?, ?, ?, datetime('now'))
               ON CONFLICT(project_id, path) DO UPDATE SET
                 hash = excluded.hash, chunks = excluded.chunks,
                 embedding_model = excluded.embedding_model, indexed_at = excluded.indexed_at""",
            (project_id, rel_path, file_hash, chunks, embedding_model),
        )
        self.conn.commit()

    def clear_index_state(self, project_id: int) -> None:
        self.conn.execute("DELETE FROM indexed_files WHERE project_id = ?", (project_id,))
        self.conn.commit()

    def index_summary(self, project_id: int) -> dict:
        row = self.conn.execute(
            "SELECT COUNT(*) AS files, COALESCE(SUM(chunks), 0) AS chunks "
            "FROM indexed_files WHERE project_id = ?",
            (project_id,),
        ).fetchone()
        return dict(row)

    # --- commits -----------------------------------------------------------------

    def record_commit(
        self,
        project_id: int,
        commit_hash: str,
        branch: str | None,
        message: str,
        interaction_id: int | None = None,
    ) -> int:
        cur = self.conn.execute(
            "INSERT INTO commits (project_id, interaction_id, hash, branch, message) "
            "VALUES (?, ?, ?, ?, ?)",
            (project_id, interaction_id, commit_hash, branch, message),
        )
        self.conn.commit()
        return cur.lastrowid

    # --- estatísticas (seção 18) ---------------------------------------------------

    def stats(self, project: str | None = None, since: str | None = None) -> dict:
        """Agregados para `coder-dev stats`. `since` é um timestamp ISO (inclusive)."""
        where, params = "WHERE 1=1", []
        if project:
            where += " AND p.name = ?"
            params.append(project)
        if since:
            where += " AND i.timestamp >= ?"
            params.append(since)
        base_from = "FROM interactions i LEFT JOIN projects p ON p.id = i.project_id "

        totals = dict(
            self.conn.execute(
                f"""SELECT COUNT(*) AS prompts,
                           COALESCE(SUM(i.input_tokens), 0) AS tokens_in,
                           COALESCE(SUM(i.output_tokens), 0) AS tokens_out,
                           COALESCE(SUM(i.cost_estimate), 0) AS cost
                    {base_from}{where}""",
                params,
            ).fetchone()
        )
        by_provider = [
            dict(r)
            for r in self.conn.execute(
                f"""SELECT i.provider, i.model, COUNT(*) AS uses,
                           CAST(AVG(i.duration_ms) AS INTEGER) AS avg_ms,
                           SUM(i.status IN ('ok', 'approved')) AS successes,
                           COALESCE(SUM(i.cost_estimate), 0) AS cost
                    {base_from}{where}
                    GROUP BY i.provider, i.model ORDER BY uses DESC""",
                params,
            ).fetchall()
        ]
        edits = dict(
            self.conn.execute(
                f"""SELECT SUM(i.task_type = 'edit') AS total_edits,
                           SUM(i.task_type = 'edit' AND i.status = 'approved') AS approved,
                           SUM(i.task_type = 'edit' AND i.status = 'rejected') AS rejected,
                           SUM(i.provider = 'claude') AS claude_calls
                    {base_from}{where}""",
                params,
            ).fetchone()
        )
        top_files = [
            dict(r)
            for r in self.conn.execute(
                f"""SELECT f.path, p.name AS project_name, COUNT(*) AS edits
                    FROM interaction_files link
                    JOIN files f ON f.id = link.file_id
                    JOIN interactions i ON i.id = link.interaction_id
                    LEFT JOIN projects p ON p.id = i.project_id
                    {where}
                    GROUP BY f.id ORDER BY edits DESC LIMIT 10""",
                params,
            ).fetchall()
        ]
        top_projects = [
            dict(r)
            for r in self.conn.execute(
                f"""SELECT p.name, COUNT(*) AS interactions
                    {base_from}{where} AND p.name IS NOT NULL
                    GROUP BY p.id ORDER BY interactions DESC LIMIT 10""",
                params,
            ).fetchall()
        ]
        return {
            "totals": totals,
            "by_provider": by_provider,
            "edits": edits,
            "top_files": top_files,
            "top_projects": top_projects,
        }

    # --- tags ---------------------------------------------------------------

    def add_tag(self, interaction_id: int, tag_name: str) -> None:
        self.conn.execute("INSERT OR IGNORE INTO tags (name) VALUES (?)", (tag_name,))
        tag_id = self.conn.execute(
            "SELECT id FROM tags WHERE name = ?", (tag_name,)
        ).fetchone()["id"]
        self.conn.execute(
            "INSERT OR IGNORE INTO interaction_tags (interaction_id, tag_id) VALUES (?, ?)",
            (interaction_id, tag_id),
        )
        self.conn.commit()

    def close(self) -> None:
        self.conn.close()
