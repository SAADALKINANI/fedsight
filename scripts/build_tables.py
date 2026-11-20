"""Download the structured datasets (OpenFEMA + CDC) and save cleaned copies under data/tables.

    python scripts/build_tables.py            # download fresh copies
    python scripts/build_tables.py --raw DIR  # reuse CSVs already on disk (declarations.csv, ...)

The output files are small, gzipped CSVs with snake_case column names. They are what the
`query_data` tool in the agent runs SQL against.
"""
from __future__ import annotations

import argparse
import re
import sys
from pathlib import Path

import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "data" / "tables"

SOURCES = {
    "declarations": "https://www.fema.gov/api/open/v2/DisasterDeclarationsSummaries.csv",
    "disaster_summaries": "https://www.fema.gov/api/open/v1/FemaWebDisasterSummaries.csv",
    "overdose": "https://data.cdc.gov/resource/xkb8-kh2a.csv?$limit=500000",
}

MONTHS = {m: i for i, m in enumerate(
    ["January", "February", "March", "April", "May", "June", "July",
     "August", "September", "October", "November", "December"], start=1)}


def snake(name: str) -> str:
    name = re.sub(r"(?<=[a-z0-9])(?=[A-Z])", "_", name)
    name = re.sub(r"(?<=[A-Z])(?=[A-Z][a-z])", "_", name)
    return name.lower()


def fetch(key: str, raw_dir: Path | None) -> pd.DataFrame:
    if raw_dir is not None:
        return pd.read_csv(raw_dir / f"{key}.csv", low_memory=False)
    print(f"downloading {key} ...", flush=True)
    return pd.read_csv(SOURCES[key], low_memory=False)


def clean_declarations(df: pd.DataFrame) -> pd.DataFrame:
    df = df.rename(columns={c: snake(c) for c in df.columns})
    df = df.drop(columns=["hash", "id", "last_refresh", "incident_id", "declaration_request_number"], errors="ignore")
    # these come through as ISO timestamps, the time part is always midnight
    for col in ["declaration_date", "incident_begin_date", "incident_end_date",
                "disaster_closeout_date", "declaration_request_date", "last_ia_filing_date"]:
        if col in df:
            df[col] = df[col].astype("string").str.slice(0, 10)
    for col in ["ih_program_declared", "ia_program_declared", "pa_program_declared", "hm_program_declared",
                "tribal_request"]:
        if col in df:
            df[col] = df[col].astype("Int64")
    df["declaration_year"] = pd.to_numeric(df["declaration_date"].str.slice(0, 4), errors="coerce").astype("Int64")
    return df.sort_values(["declaration_date", "disaster_number"]).reset_index(drop=True)


def clean_disaster_totals(df: pd.DataFrame) -> pd.DataFrame:
    df = df.rename(columns={c: snake(c) for c in df.columns})
    df = df.drop(columns=["hash", "id", "last_refresh", "pa_load_date", "ia_load_date"], errors="ignore")
    return df.sort_values("disaster_number").reset_index(drop=True)


def clean_overdose(df: pd.DataFrame) -> pd.DataFrame:
    df = df.copy()
    df["month_number"] = df["month"].map(MONTHS)
    df["period_end"] = df["year"].astype(str) + "-" + df["month_number"].astype(str).str.zfill(2)
    # the source marks suppressed cells with an empty value and a footnote
    df["suppressed"] = df["data_value"].isna().astype(int)
    keep = ["state", "state_name", "year", "month", "month_number", "period_end", "indicator",
            "data_value", "predicted_value", "percent_complete", "percent_pending_investigation", "suppressed"]
    df = df[keep].rename(columns={"data_value": "reported_value"})
    df["reported_value"] = pd.to_numeric(df["reported_value"], errors="coerce")
    df["predicted_value"] = pd.to_numeric(df["predicted_value"], errors="coerce")
    return df.sort_values(["state", "indicator", "period_end"]).reset_index(drop=True)


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--raw", type=Path, help="folder with declarations.csv, disaster_summaries.csv, overdose.csv")
    args = ap.parse_args()
    OUT.mkdir(parents=True, exist_ok=True)

    jobs = [
        ("declarations", "fema_declarations.csv.gz", clean_declarations),
        ("disaster_summaries", "fema_disaster_totals.csv.gz", clean_disaster_totals),
        ("overdose", "cdc_overdose_deaths.csv.gz", clean_overdose),
    ]
    for key, fname, cleaner in jobs:
        df = cleaner(fetch(key, args.raw))
        df.to_csv(OUT / fname, index=False)
        print(f"{fname}: {len(df):,} rows, {len(df.columns)} columns")
    return 0


if __name__ == "__main__":
    sys.exit(main())
