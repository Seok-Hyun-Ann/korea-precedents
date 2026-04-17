"""구조화된 판례 데이터를 SQLite DB로 변환한다.

JSON 파일들을 읽어 정규화된 테이블에 저장하고,
FTS5 전문검색 인덱스를 생성한다.

출력: data/precedents.db
"""
from __future__ import annotations

import json
import re
import sqlite3
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
STRUCTURED_PATH = ROOT / "data" / "structured" / "all_structured.json"
CITATIONS_PATH = ROOT / "data" / "citations" / "citation_edges.json"
PRECEDENTS_PATH = ROOT / "data" / "precedents_merged" / "all_precedents.json"
DB_PATH = ROOT / "data" / "precedents.db"


def create_tables(conn: sqlite3.Connection) -> None:
    conn.executescript("""
        -- 판례 기본 정보
        CREATE TABLE IF NOT EXISTS cases (
            precedent_id    TEXT PRIMARY KEY,
            case_number     TEXT NOT NULL,
            case_name       TEXT NOT NULL,
            court_name      TEXT,
            decision_date   TEXT,
            case_type       TEXT,
            decision_type   TEXT,
            plaintiff       TEXT,
            plaintiff_role  TEXT,
            defendant       TEXT,
            defendant_role  TEXT,
            ruling          TEXT,
            result_class    TEXT,
            result_detail   TEXT,
            ruling_for      TEXT,
            decision_points TEXT,
            decision_summary TEXT,
            key_reasoning   TEXT,
            easy_explanation TEXT,
            full_text       TEXT
        );

        -- 법령 매칭 (판례 ↔ 법령 N:M)
        CREATE TABLE IF NOT EXISTS case_laws (
            id              INTEGER PRIMARY KEY AUTOINCREMENT,
            precedent_id    TEXT NOT NULL,
            law_name        TEXT NOT NULL,
            article_label   TEXT,
            article_title   TEXT,
            article_text    TEXT,
            FOREIGN KEY (precedent_id) REFERENCES cases(precedent_id)
        );

        -- 인용 관계 (판례 → 판례)
        CREATE TABLE IF NOT EXISTS citations (
            id                  INTEGER PRIMARY KEY AUTOINCREMENT,
            citing              TEXT NOT NULL,
            cited               TEXT NOT NULL,
            citing_case_number  TEXT,
            citing_case_name    TEXT,
            cited_case_number   TEXT,
            cited_case_name     TEXT
        );

        -- 인덱스
        CREATE INDEX IF NOT EXISTS idx_cases_case_number ON cases(case_number);
        CREATE INDEX IF NOT EXISTS idx_cases_decision_date ON cases(decision_date);
        CREATE INDEX IF NOT EXISTS idx_cases_case_type ON cases(case_type);
        CREATE INDEX IF NOT EXISTS idx_cases_result_class ON cases(result_class);
        CREATE INDEX IF NOT EXISTS idx_cases_court_name ON cases(court_name);
        CREATE INDEX IF NOT EXISTS idx_case_laws_precedent_id ON case_laws(precedent_id);
        CREATE INDEX IF NOT EXISTS idx_case_laws_law_name ON case_laws(law_name);
        CREATE INDEX IF NOT EXISTS idx_citations_citing ON citations(citing);
        CREATE INDEX IF NOT EXISTS idx_citations_cited ON citations(cited);
    """)


def create_fts(conn: sqlite3.Connection) -> None:
    """FTS5 전문검색 인덱스를 생성한다."""
    conn.executescript("""
        -- 기존 FTS 테이블 삭제 후 재생성
        DROP TABLE IF EXISTS cases_fts;

        CREATE VIRTUAL TABLE cases_fts USING fts5(
            case_number,
            case_name,
            court_name,
            decision_points,
            decision_summary,
            key_reasoning,
            easy_explanation,
            content=cases,
            content_rowid=rowid,
            tokenize='unicode61'
        );

        -- FTS 인덱스 채우기
        INSERT INTO cases_fts(rowid, case_number, case_name, court_name,
                              decision_points, decision_summary, key_reasoning, easy_explanation)
        SELECT rowid, case_number, case_name, court_name,
               decision_points, decision_summary, key_reasoning, easy_explanation
        FROM cases;
    """)


def main() -> None:
    print("=== SQLite DB 생성 ===\n")

    # 기존 DB 삭제
    if DB_PATH.exists():
        try:
            DB_PATH.unlink()
            print(f"기존 DB 삭제: {DB_PATH}")
        except PermissionError:
            print(f"[오류] DB 파일이 다른 프로세스에 의해 잠겨 있습니다: {DB_PATH}")
            print("  Streamlit 앱 등 DB를 사용하는 프로세스를 먼저 종료해주세요.")
            print("  (예: taskkill /F /IM streamlit.exe)")
            return

    conn = sqlite3.connect(str(DB_PATH))
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA synchronous=NORMAL")
    conn.execute("PRAGMA cache_size=-64000")  # 64MB cache

    create_tables(conn)

    # 1) 판례 데이터 로드
    print("구조화 데이터 로드 중...")
    structured = json.loads(STRUCTURED_PATH.read_text(encoding="utf-8"))
    print(f"  구조화 판례: {len(structured):,}건")

    # 전문(full_text)을 원본에서 가져오기 위해 인덱스 구축
    print("원본 판례 로드 중 (전문 포함)...")
    raw_precedents = json.loads(PRECEDENTS_PATH.read_text(encoding="utf-8"))
    fulltext_map = {}
    for p in raw_precedents:
        pid = str(p.get("precedent_id", ""))
        ft = p.get("full_text", "")
        if pid and ft:
            fulltext_map[pid] = ft
    del raw_precedents  # 메모리 해제
    print(f"  전문 보유: {len(fulltext_map):,}건")

    # 2) cases 테이블 INSERT
    print("\ncases 테이블 INSERT 중...")
    case_rows = []
    law_rows = []

    for i, case in enumerate(structured):
        if (i + 1) % 20000 == 0:
            print(f"  {i+1:,}/{len(structured):,}...")

        pid = case.get("precedent_id", "")
        full_text = fulltext_map.get(pid, "")

        case_rows.append((
            pid,
            case.get("case_number", ""),
            case.get("case_name", ""),
            case.get("court_name", ""),
            case.get("decision_date", ""),
            case.get("case_type", ""),
            case.get("decision_type", ""),
            case.get("plaintiff", ""),
            case.get("plaintiff_role", ""),
            case.get("defendant", ""),
            case.get("defendant_role", ""),
            case.get("ruling", ""),
            case.get("result_class", ""),
            case.get("result_detail", ""),
            case.get("ruling_for", ""),
            case.get("decision_points", ""),
            case.get("decision_summary", ""),
            case.get("key_reasoning", ""),
            case.get("easy_explanation", ""),
            full_text,
        ))

        # 법령 매칭
        for art in case.get("matched_articles", []):
            law_rows.append((
                pid,
                art.get("law_name", ""),
                art.get("article_label", ""),
                art.get("article_title", ""),
                art.get("article_text", ""),
            ))

        # matched_articles에 없지만 matched_laws에만 있는 것도 추가
        existing_laws = {(a.get("law_name", ""), a.get("article_label", ""))
                        for a in case.get("matched_articles", [])}
        for law_str in case.get("matched_laws", []):
            law_name = re.sub(r'\s*제\d+조.*$', '', law_str).strip()
            art_label = ""
            m = re.search(r'(제\d+조(?:의\d+)?)', law_str)
            if m:
                art_label = m.group(1)
            if law_name and (law_name, art_label) not in existing_laws:
                law_rows.append((pid, law_name, art_label, "", ""))

    conn.executemany(
        "INSERT OR IGNORE INTO cases VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
        case_rows,
    )
    print(f"  cases: {len(case_rows):,}건 삽입")

    conn.executemany(
        "INSERT INTO case_laws (precedent_id, law_name, article_label, article_title, article_text) "
        "VALUES (?,?,?,?,?)",
        law_rows,
    )
    print(f"  case_laws: {len(law_rows):,}건 삽입")

    del case_rows, law_rows, fulltext_map, structured  # 메모리 해제

    # 3) 인용 관계
    print("\n인용 관계 로드 중...")
    if CITATIONS_PATH.exists():
        citations = json.loads(CITATIONS_PATH.read_text(encoding="utf-8"))
        cite_rows = [
            (
                e.get("citing", ""),
                e.get("cited", ""),
                e.get("citing_case_number", ""),
                e.get("citing_case_name", ""),
                e.get("cited_case_number", ""),
                e.get("cited_case_name", ""),
            )
            for e in citations
        ]
        conn.executemany(
            "INSERT INTO citations (citing, cited, citing_case_number, citing_case_name, "
            "cited_case_number, cited_case_name) VALUES (?,?,?,?,?,?)",
            cite_rows,
        )
        print(f"  citations: {len(cite_rows):,}건 삽입")
        del citations, cite_rows

    conn.commit()

    # 4) FTS 인덱스 생성
    print("\nFTS5 전문검색 인덱스 생성 중...")
    create_fts(conn)
    conn.commit()

    # 5) VACUUM으로 최적화
    print("DB 최적화 (VACUUM)...")
    conn.execute("VACUUM")
    conn.close()

    # 결과 출력
    size_mb = DB_PATH.stat().st_size / 1024 / 1024
    print(f"\n=== 완료 ===")
    print(f"DB 경로: {DB_PATH}")
    print(f"DB 크기: {size_mb:.1f}MB")

    # 간단한 검증
    conn = sqlite3.connect(str(DB_PATH))
    for table in ("cases", "case_laws", "citations"):
        count = conn.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0]
        print(f"  {table}: {count:,}건")
    conn.close()


if __name__ == "__main__":
    main()
