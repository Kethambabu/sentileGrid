"""Chemical compatibility exact-match lookup. CLAUDE.md §7.8: this data does
NOT go through RAG/embeddings — it's loaded directly into DuckDB and queried
by exact match, since compatibility between two named components is a fact
lookup, not a semantic-similarity problem.
"""

from __future__ import annotations

from pathlib import Path

import duckdb

REPO_ROOT = Path(__file__).resolve().parents[2]
DEFAULT_CSV_PATH = REPO_ROOT / "backend" / "knowledge" / "chemical_compatibility.csv"


def get_connection(csv_path: Path = DEFAULT_CSV_PATH) -> duckdb.DuckDBPyConnection:
    con = duckdb.connect(database=":memory:")
    con.execute(
        "CREATE TABLE chemical_compatibility AS SELECT * FROM read_csv_auto(?, header=true)",
        [str(csv_path)],
    )
    return con


def lookup_compatibility(con: duckdb.DuckDBPyConnection, component_1: str, component_2: str) -> dict | None:
    row = con.execute(
        """
        SELECT component_1, component_2, compatible, hazard_note
        FROM chemical_compatibility
        WHERE (component_1 = ? AND component_2 = ?) OR (component_1 = ? AND component_2 = ?)
        """,
        [component_1, component_2, component_2, component_1],
    ).fetchone()
    if row is None:
        return None
    return {"component_1": row[0], "component_2": row[1], "compatible": bool(row[2]), "hazard_note": row[3]}
