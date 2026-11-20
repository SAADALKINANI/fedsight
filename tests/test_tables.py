import sqlite3

import pytest

from fedsight.tables import MAX_ROWS, ReadOnlyDB


@pytest.fixture
def db(tables_dir):
    return ReadOnlyDB(tables_dir)


def test_select_works(db):
    cols, rows = db.run("SELECT state, COUNT(DISTINCT disaster_number) AS n FROM fema_declarations GROUP BY state ORDER BY state")
    assert cols == ["state", "n"]
    assert rows == [("FL", 2), ("TX", 1)]


def test_with_clause_works(db):
    _, rows = db.run("WITH t AS (SELECT * FROM fema_declarations WHERE state='FL') SELECT COUNT(*) FROM t")
    assert rows == [(2,)]


@pytest.mark.parametrize("sql", [
    "DROP TABLE fema_declarations",
    "DELETE FROM fema_declarations",
    "UPDATE fema_declarations SET state='XX'",
    "INSERT INTO fema_declarations VALUES (9,'ZZ','DR','2020-01-01')",
    "SELECT 1; DROP TABLE fema_declarations",
    "PRAGMA table_info(fema_declarations)",
    "ATTACH DATABASE '/tmp/x.db' AS x",
    "CREATE TABLE evil (a int)",
])
def test_anything_but_a_single_select_is_refused(db, sql):
    with pytest.raises((ValueError, sqlite3.DatabaseError)):
        db.run(sql)
    # and the data is untouched
    assert db.run("SELECT COUNT(*) FROM fema_declarations")[1] == [(4,)]


def test_cannot_read_sqlite_internals_beyond_loaded_tables(db):
    with pytest.raises((ValueError, sqlite3.DatabaseError)):
        db.run("SELECT * FROM pragma_database_list")


def test_row_cap(db):
    _, rows = db.run("WITH RECURSIVE n(i) AS (SELECT 1 UNION ALL SELECT i+1 FROM n WHERE i < 500) SELECT i FROM n")
    assert len(rows) == MAX_ROWS


def test_runaway_query_is_stopped(db):
    with pytest.raises((ValueError, sqlite3.DatabaseError)):
        db.run("WITH RECURSIVE n(i) AS (SELECT 1 UNION ALL SELECT i+1 FROM n) SELECT MAX(i) FROM n")


def test_schema_lists_tables_and_columns(db):
    text = db.schema()
    assert "fema_declarations" in text and "declaration_date" in text
