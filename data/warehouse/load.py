# data/warehouse/load.py
"""Load corpus.jsonl + corpus_chunks.jsonl into DuckDB.
Run: python data/warehouse/load.py
"""
import duckdb
import json
from pathlib import Path
from datetime import datetime

ROOT = Path(__file__).resolve().parents[2]
DB_PATH = ROOT / "data" / "warehouse" / "corpus.db"
SCHEMA = Path(__file__).parent / "schema.sql"
CORPUS = ROOT / "data" / "processed" / "corpus.jsonl"
CHUNKS = ROOT / "data" / "processed" / "corpus_chunks.jsonl"

DB_PATH.parent.mkdir(parents=True, exist_ok=True)


def read_jsonl(path: Path):
    with open(path, "r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if line:
                yield json.loads(line)


def parse_date(v):
    if not v:
        return None
    s = str(v)[:10]
    try:
        return datetime.strptime(s, "%Y-%m-%d").date()
    except ValueError:
        return None


def pick(d, *keys, default=None):
    for k in keys:
        if k in d and d[k] is not None:
            return d[k]
    return default


def main():
    con = duckdb.connect(str(DB_PATH))
    con.execute(SCHEMA.read_text())
    print("[schema] applied")

    # --- incidents ---
    rows = []
    sources = set()
    skipped = 0
    for r in read_jsonl(CORPUS):
        inc_id = pick(r, "id", "incident_id", "doc_id")
        if not inc_id:
            skipped += 1
            continue
        body = pick(r, "body", "text", "content", default="") or ""
        src = pick(r, "source", default="unknown")
        sources.add(src)
        rows.append((
            str(inc_id),
            pick(r, "title", default=""),
            body,
            src,
            pick(r, "url", default=""),
            parse_date(pick(r, "published_date", "date", "published")),
            len(body),
        ))
    if skipped:
        print(f"[warn] skipped {skipped} incident rows (missing id)")

    # services
    con.execute("DELETE FROM dim_services")
    for i, s in enumerate(sorted(sources), start=1):
        con.execute("INSERT INTO dim_services VALUES (?, ?, ?)", [i, s, s])

    # incidents
    con.execute("DELETE FROM fact_incidents")
    con.executemany(
        "INSERT INTO fact_incidents "
        "(incident_id,title,body,source,url,published_date,body_char_len) "
        "VALUES (?,?,?,?,?,?,?)",
        rows,
    )
    # link service_id
    con.execute("""
        UPDATE fact_incidents
        SET service_id = (
            SELECT service_id FROM dim_services s
            WHERE s.service_source = fact_incidents.source
        )
    """)
    print(f"[fact_incidents] inserted {len(rows)} rows")

    # --- chunks ---
    crows = []
    for r in read_jsonl(CHUNKS):
        cid = pick(r, "chunk_id", "id")
        iid = pick(r, "incident_id", "parent_id", "doc_id")
        if not (cid and iid):
            continue
        crows.append((
            str(cid),
            str(iid),
            pick(r, "chunk_index", "index", default=0),
            pick(r, "chunk_text", "text", default=""),
            pick(r, "tokens", "chunk_tokens", default=None),
        ))
    con.execute("DELETE FROM fact_chunks")
    con.executemany(
        "INSERT INTO fact_chunks "
        "(chunk_id,incident_id,chunk_index,chunk_text,chunk_tokens) "
        "VALUES (?,?,?,?,?)",
        crows,
    )
    print(f"[fact_chunks] inserted {len(crows)} rows")

    # --- summary ---
    cnt_i = con.execute("SELECT COUNT(*) FROM fact_incidents").fetchone()[0]
    cnt_c = con.execute("SELECT COUNT(*) FROM fact_chunks").fetchone()[0]
    by_src = con.execute(
        "SELECT source, COUNT(*) FROM fact_incidents GROUP BY source ORDER BY 2 DESC"
    ).fetchall()
    print(f"\n== corpus.db ==  incidents={cnt_i}  chunks={cnt_c}")
    for s, n in by_src:
        print(f"    - {s}: {n}")
    con.close()


if __name__ == "__main__":
    main()