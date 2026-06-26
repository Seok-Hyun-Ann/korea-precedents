"""기존 precedents.db에 법령 메타(laws) 테이블을 추가한다.

판례 상세의 "선고 당시 / 현행 조문" 비교에서, 조문 단위 개정 마커가 없는
전부개정 등을 잡아내기 위해 법령별 현행 시행일자를 적재한다.
전체 DB 재빌드 없이 빠르게 보강하는 용도다.

  python scripts/add_law_meta.py
"""
from __future__ import annotations

import json
import sqlite3
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
DB_PATH = ROOT / "data" / "precedents.db"
LAWS_PATH = ROOT / "data" / "laws_parsed" / "all_laws.json"


def to_yyyymmdd(s: str) -> str:
    """'2026-03-17' / '2026.3.17' → '20260317'. 형식이 다르면 빈 문자열."""
    s = (s or "").replace("-", "").replace(".", "").strip()
    return s if len(s) == 8 and s.isdigit() else ""


def load_law_meta() -> list[tuple]:
    """법령명별로 현행(시행일 최신) 한 건만 남겨 행 리스트를 만든다."""
    laws = json.loads(LAWS_PATH.read_text(encoding="utf-8"))
    best: dict[str, dict] = {}
    for x in laws:
        name = x.get("law_name", "")
        if not name:
            continue
        eff = to_yyyymmdd(x.get("effective_date", ""))
        cur = best.get(name)
        if cur is None or eff > cur["eff"]:
            best[name] = {
                "eff": eff,
                "row": (
                    name,
                    x.get("law_id", ""),
                    x.get("law_mst", ""),
                    x.get("law_type", ""),
                    to_yyyymmdd(x.get("promulgation_date", "")),
                    eff,
                ),
            }
    return [v["row"] for v in best.values()]


def main() -> None:
    if not DB_PATH.exists():
        print(f"[오류] DB가 없습니다: {DB_PATH}")
        return
    if not LAWS_PATH.exists():
        print(f"[오류] 법령 파싱 결과가 없습니다: {LAWS_PATH}")
        return

    rows = load_law_meta()
    try:
        conn = sqlite3.connect(str(DB_PATH))
        conn.executescript("""
            CREATE TABLE IF NOT EXISTS laws (
                law_name          TEXT PRIMARY KEY,
                law_id            TEXT,
                law_mst           TEXT,
                law_type          TEXT,
                promulgation_date TEXT,
                effective_date    TEXT
            );
        """)
        conn.executemany(
            "INSERT OR REPLACE INTO laws "
            "(law_name, law_id, law_mst, law_type, promulgation_date, effective_date) "
            "VALUES (?,?,?,?,?,?)",
            rows,
        )
        conn.commit()
        n = conn.execute("SELECT COUNT(*) FROM laws").fetchone()[0]
        conn.close()
    except sqlite3.OperationalError as e:
        print(f"[오류] DB 작업 실패: {e}")
        print("  Streamlit 앱이 DB를 잠그고 있을 수 있습니다. 앱을 종료하고 다시 실행하세요.")
        return

    print(f"laws 테이블 보강 완료: {n:,}개 법령")


if __name__ == "__main__":
    main()
