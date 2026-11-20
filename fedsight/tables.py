"""Structured federal data (OpenFEMA + CDC) loaded into an in-memory, read-only SQLite database."""
from __future__ import annotations

import re
import sqlite3
from pathlib import Path

import pandas as pd

from .config import settings

# table name -> (file, description shown to the model)
TABLES = {
    "fema_declarations": (
        "fema_declarations.csv.gz",
        "FEMA disaster declarations since 1953, one row per designated area (county or tribe), so count "
        "DISTINCT disaster_number to count disasters. declaration_type: DR = major disaster, EM = emergency, "
        "FM = fire management assistance. incident_type is a text label such as Hurricane or Fire; "
        "declaration_date is YYYY-MM-DD and declaration_year is its year.",
    ),
    "fema_disaster_totals": (
        "fema_disaster_totals.csv.gz",
        "One row per disaster number with dollars approved or obligated: total_amount_ihp_approved "
        "(Individuals and Households Program), total_obligated_amount_pa (Public Assistance), "
        "total_obligated_amount_hmgp (Hazard Mitigation). Join to fema_declarations on disaster_number for "
        "the state, title and date. Amounts are US dollars.",
    ),
    "cdc_overdose_deaths": (
        "cdc_overdose_deaths.csv.gz",
        "CDC provisional drug overdose death counts. Each row is a 12-month-ending total: reported_value is the "
        "count for the 12 months ending in period_end (YYYY-MM). state is a two-letter code; 'US' is the national "
        "total and 'YC' is New York City, so don't add them to the states. indicator is e.g. "
        "'Number of Drug Overdose Deaths' or 'Synthetic opioids, excl. methadone (T40.4)'. reported_value is empty "
        "when CDC suppressed it (suppressed = 1).",
    ),
}

# One plain sentence per table saying what the data is. It is attached to every query result as a
# citable text block, so labels like "provisional" or "Public Assistance" in an answer have a source.
PROVENANCE = {
    "fema_declarations": (
        "Dataset: OpenFEMA Disaster Declarations Summaries. It has one row per designated county or tribe, so a "
        "disaster is counted once by its disaster_number. declaration_type DR means major disaster, EM means "
        "emergency and FM means fire management assistance."
    ),
    "fema_disaster_totals": (
        "Dataset: OpenFEMA disaster totals. IHP is the Individuals and Households Program and PA is Public "
        "Assistance (categories A and B are emergency work, categories C through G are permanent work). "
        "HMGP is the Hazard Mitigation Grant Program. Amounts are US dollars."
    ),
    "cdc_overdose_deaths": (
        "Dataset: CDC provisional drug overdose death counts. Each value is a count for the 12 months ending in "
        "period_end. The counts are provisional. predicted_value adjusts reported_value for reporting delays. "
        "State 'US' is the national total and 'YC' is New York City, which is reported separately from New York State."
    ),
}

MAX_ROWS = 50
_ALLOWED_START = re.compile(r"^\s*(select|with)\b", re.I)


class ReadOnlyDB:
    def __init__(self, tables_dir: Path = settings.data_dir / "tables"):
        self.conn = sqlite3.connect(":memory:", check_same_thread=False)
        self.loaded = {}
        for name, (fname, _) in TABLES.items():
            path = tables_dir / fname
            if path.exists():
                df = pd.read_csv(path, low_memory=False)
                df.to_sql(name, self.conn, index=False)
                self.loaded[name] = list(df.columns)
        self.conn.execute("PRAGMA query_only = ON")
        self.conn.set_authorizer(self._authorize)

    def _authorize(self, action, arg1, arg2, db, trigger):
        if action in (sqlite3.SQLITE_SELECT, sqlite3.SQLITE_FUNCTION, sqlite3.SQLITE_RECURSIVE):
            return sqlite3.SQLITE_OK
        if action == sqlite3.SQLITE_READ and (arg1 in self.loaded or arg1 is None or arg1.startswith("sqlite_")):
            return sqlite3.SQLITE_OK
        return sqlite3.SQLITE_DENY

    def schema(self) -> str:
        lines = []
        for name, cols in self.loaded.items():
            lines.append(f"{name}: {TABLES[name][1]}\n  columns: {', '.join(cols)}")
        return "\n".join(lines)

    def run(self, sql: str) -> tuple[list[str], list[tuple]]:
        sql = sql.strip().rstrip(";")
        if not _ALLOWED_START.match(sql) or ";" in sql:
            raise ValueError("Only a single SELECT (or WITH ... SELECT) statement is allowed.")
        steps = {"n": 0}

        def guard():  # abort runaway queries
            steps["n"] += 1
            return 1 if steps["n"] > 2000 else 0

        self.conn.set_progress_handler(guard, 1000)
        try:
            cur = self.conn.execute(sql)
            rows = cur.fetchmany(MAX_ROWS)
            cols = [d[0] for d in cur.description or []]
        finally:
            self.conn.set_progress_handler(None, 0)
        return cols, rows
