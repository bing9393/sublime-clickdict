#!/usr/bin/env python3
"""Build the offline dictionary bundled with ClickDict.

Input : ECDICT ``ecdict.csv`` and optional ``lemma.en.txt``.
Output: ``dictionary.db`` in the repository root (SQLite, read-only at runtime).

The full ECDICT dump contains ~770k rows, including phrases and proper
nouns that can never be selected by a single mouse click.  We keep only
single-token English headwords that have a Chinese translation.  That is
roughly 400k entries and keeps the database around 30 MB while covering
technical vocabulary that rank/tag based filters tend to miss.

Usage:
    python3 tools/build_dictionary.py \
        --csv tools/package/assets/ecdict.csv \
        --lemma tools/package/assets/lemma.en.txt \
        --out dictionary.db
"""

import argparse
import csv
import os
import re
import sqlite3
import sys
import tempfile

WORD_RE = re.compile(r"^[A-Za-z][A-Za-z'’.\-]*$")

SCHEMA = """
CREATE TABLE entries (
    word        TEXT PRIMARY KEY,
    word_lower  TEXT NOT NULL,
    phonetic    TEXT NOT NULL DEFAULT '',
    translation TEXT NOT NULL,
    frq         INTEGER NOT NULL DEFAULT 0,
    collins     INTEGER NOT NULL DEFAULT 0
) WITHOUT ROWID;

CREATE TABLE lemmas (
    form TEXT PRIMARY KEY COLLATE NOCASE,
    lemma TEXT NOT NULL
) WITHOUT ROWID;
"""


def to_int(value):
    try:
        return int((value or "").strip())
    except (TypeError, ValueError):
        return 0


def clean_translation(value):
    value = (value or "").replace("\r\n", "\n").replace("\r", "\n")
    lines = [line.strip() for line in value.split("\n")]
    return "\n".join(line for line in lines if line)


def read_lemmas(path):
    """Parse ``lemma/freq -> form1,form2`` lines into {form: lemma}."""
    mapping = {}
    if not path or not os.path.exists(path):
        return mapping
    with open(path, encoding="utf-8", errors="replace") as handle:
        for line in handle:
            line = line.strip()
            if not line or line.startswith(";"):
                continue
            if "->" not in line:
                continue
            left, right = line.split("->", 1)
            lemma = left.split("/", 1)[0].strip()
            if not lemma:
                continue
            for form in right.split(","):
                form = form.strip()
                # Only single-token forms are reachable by a click.
                if not form or " " in form or len(form) > 64:
                    continue
                mapping.setdefault(form.lower(), lemma)
    return mapping


def build(csv_path, lemma_path, out_path, common_only=False):
    if not os.path.exists(csv_path):
        raise SystemExit("ECDICT csv not found: {}".format(csv_path))

    out_dir = os.path.dirname(os.path.abspath(out_path))
    os.makedirs(out_dir, exist_ok=True)
    fd, tmp_path = tempfile.mkstemp(prefix=".dictionary-", suffix=".db", dir=out_dir)
    os.close(fd)
    os.unlink(tmp_path)

    conn = sqlite3.connect(tmp_path)
    try:
        conn.executescript(
            "PRAGMA journal_mode=OFF;"
            "PRAGMA synchronous=OFF;"
            "PRAGMA temp_store=MEMORY;"
            "PRAGMA page_size=4096;"
        )
        conn.executescript(SCHEMA)

        rows = 0
        kept = 0
        batch = []
        seen = set()

        with open(csv_path, encoding="utf-8-sig", newline="") as handle:
            reader = csv.DictReader(handle)
            for row in reader:
                rows += 1
                word = (row.get("word") or "").strip()
                translation = clean_translation(row.get("translation"))
                if not word or not translation:
                    continue
                if len(word) > 64 or not WORD_RE.match(word):
                    continue
                if common_only:
                    marked = (
                        bool((row.get("tag") or "").strip())
                        or to_int(row.get("collins")) > 0
                        or to_int(row.get("oxford")) > 0
                        or to_int(row.get("bnc")) > 0
                        or to_int(row.get("frq")) > 0
                    )
                    if not marked:
                        continue
                key = word.lower()
                if key in seen:
                    continue
                seen.add(key)

                batch.append(
                    (
                        word,
                        key,
                        (row.get("phonetic") or "").strip(),
                        translation,
                        to_int(row.get("frq")),
                        to_int(row.get("collins")),
                    )
                )
                kept += 1
                if len(batch) >= 5000:
                    conn.executemany(
                        "INSERT INTO entries VALUES (?, ?, ?, ?, ?, ?)", batch
                    )
                    batch = []

        if batch:
            conn.executemany("INSERT INTO entries VALUES (?, ?, ?, ?, ?, ?)", batch)

        lemmas = read_lemmas(lemma_path)
        if lemmas:
            conn.executemany(
                "INSERT OR IGNORE INTO lemmas(form, lemma) VALUES (?, ?)",
                list(lemmas.items()),
            )

        conn.execute("CREATE INDEX idx_entries_lower ON entries(word_lower)")
        conn.commit()
        conn.execute("VACUUM")
        conn.commit()
    finally:
        conn.close()

    os.replace(tmp_path, out_path)
    size_mb = os.path.getsize(out_path) / (1024.0 * 1024.0)
    print(
        "rows={} kept={} lemmas={} size={:.1f}MB -> {}".format(
            rows, kept, len(lemmas), size_mb, out_path
        )
    )


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--csv", required=True, help="path to ecdict.csv")
    parser.add_argument("--lemma", default="", help="path to lemma.en.txt")
    parser.add_argument(
        "--out",
        default="dictionary.db",
        help="output SQLite path",
    )
    parser.add_argument(
        "--common-only",
        action="store_true",
        help="keep only rank/tag/collins/oxford marked words (~58k)",
    )
    args = parser.parse_args()
    build(args.csv, args.lemma, args.out, args.common_only)
    return 0


if __name__ == "__main__":
    sys.exit(main())
