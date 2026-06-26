"""판례가 참조하는 법령의 '선고 당시 조문 원문'을 국가법령정보 공동활용 API로 수집한다.

판례 상세의 "선고 당시 vs 현행 조문" 비교에서, 현행 조문(case_laws.article_text)과
대비할 '당시 시행 중이던 조문 원문'을 채운다.

경로:
  1. eflaw 목록으로 법령별 시행버전(시행일자·법령일련번호 MST) 수집  -> law_versions
  2. 각 판례 선고일 시점에 시행 중이던 버전을 골라, 그 버전의 참조 조문 원문 수집 -> law_articles

이미 수집된 법령/버전은 건너뛰어 재실행(resume)이 가능하다.

  python scripts/fetch_law_versions.py            # 전체
  python scripts/fetch_law_versions.py --limit 20 # 앞 20개 법령만 (테스트)
  python scripts/fetch_law_versions.py --law 민법  # 특정 법령만
"""
from __future__ import annotations

import argparse
import sqlite3
import xml.etree.ElementTree as ET
from pathlib import Path

from api_client import BASE_SEARCH_URL, BASE_SERVICE_URL, LawApiClient

ROOT = Path(__file__).resolve().parent.parent
DB_PATH = ROOT / "data" / "precedents.db"


def ensure_tables(conn: sqlite3.Connection) -> None:
    conn.executescript("""
        CREATE TABLE IF NOT EXISTS law_versions (
            law_id          TEXT,
            law_name        TEXT,
            effective_date  TEXT,   -- YYYYMMDD (시행일자)
            mst             TEXT,   -- 법령일련번호 (버전 식별자)
            history_code    TEXT,   -- 현행 / 연혁
            PRIMARY KEY (law_id, effective_date, mst)
        );
        CREATE TABLE IF NOT EXISTS law_articles (
            law_id          TEXT,
            mst             TEXT,
            effective_date  TEXT,
            article_label   TEXT,   -- 제750조 / 제750조의2
            article_title   TEXT,
            article_text    TEXT,
            PRIMARY KEY (law_id, mst, article_label)
        );
        CREATE INDEX IF NOT EXISTS idx_law_articles_lookup
            ON law_articles(law_id, article_label, effective_date);
        CREATE INDEX IF NOT EXISTS idx_law_versions_lookup
            ON law_versions(law_id, effective_date);
    """)


def make_label(unit: ET.Element) -> str:
    """조문단위 → '제750조' / '제750조의2' 라벨."""
    no = (unit.findtext("조문번호") or "").strip()
    if not no:
        return ""
    branch = (unit.findtext("조문가지번호") or "").strip()
    label = f"제{no}조"
    if branch and branch != "0":
        label += f"의{branch}"
    return label


def fetch_versions(client: LawApiClient, law_name: str, law_id: str) -> list[tuple]:
    """해당 법령ID의 모든 시행버전 (effective_date, mst, history_code)."""
    xml = client.search("eflaw", query=law_name, display=200)
    root = ET.fromstring(xml)
    out = []
    for law in root.findall("law"):
        if law.findtext("법령ID") != law_id or law.findtext("법령명한글") != law_name:
            continue
        eff = (law.findtext("시행일자") or "").strip()
        mst = (law.findtext("법령일련번호") or "").strip()
        code = (law.findtext("현행연혁코드") or "").strip()
        if eff and mst:
            out.append((eff, mst, code))
    return sorted(set(out))


def article_full_text(unit: ET.Element) -> str:
    """조문단위에서 제목·항·호·목을 합쳐 조문 전체 본문을 만든다.

    항(①②)이 있는 조문은 조문내용에 제목만 들어 있고 본문은 <항>/<항내용>에 있으므로
    이를 모두 모아야 한다.
    """
    parts = []
    head = (unit.findtext("조문내용") or "").strip()
    if head:
        parts.append(head)

    def collect(node, tag):
        for child in node.findall(tag):
            text = (child.findtext(tag + "내용") or "").strip()
            if text:
                parts.append(text)
            # 항 → 호 → 목 순으로 하위 항목을 이어 붙인다.
            for sub in ("항", "호", "목"):
                if sub != tag:
                    collect(child, sub)

    for top in ("항", "호"):
        collect(unit, top)
    return "\n".join(parts)


def fetch_articles(client: LawApiClient, mst: str, wanted: set[str]) -> list[tuple]:
    """target=law&MST 본문에서 원하는 라벨의 조문 원문을 추출한다."""
    xml = client.service("law", MST=mst)
    root = ET.fromstring(xml)
    rows = []
    for unit in root.findall("./조문/조문단위"):
        if unit.findtext("조문여부") != "조문":
            continue
        label = make_label(unit)
        if label and label in wanted:
            rows.append((
                label,
                (unit.findtext("조문제목") or "").strip(),
                article_full_text(unit),
            ))
    return rows


def in_force_mst(versions: list[tuple], decision_date: str) -> tuple | None:
    """선고일에 시행 중이던 버전 (effective_date, mst). versions는 시행일 오름차순."""
    cand = [v for v in versions if v[0] <= decision_date]
    if cand:
        return cand[-1][0], cand[-1][1]
    return (versions[0][0], versions[0][1]) if versions else None


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--limit", type=int, default=0, help="앞 N개 법령만 처리 (0=전체)")
    ap.add_argument("--top", type=int, default=0, help="판례 참조가 많은 상위 N개 법령만 처리")
    ap.add_argument("--law", type=str, default="", help="특정 법령명만 처리")
    args = ap.parse_args()

    if not DB_PATH.exists():
        print(f"[오류] DB가 없습니다: {DB_PATH}")
        return

    client = LawApiClient()  # .env / LAW_GO_KR_OC
    conn = sqlite3.connect(str(DB_PATH))
    conn.row_factory = sqlite3.Row
    ensure_tables(conn)

    # 대상: 판례가 참조하면서 law_id를 아는 법령
    where = "AND l.law_name = ?" if args.law else ""
    params = (args.law,) if args.law else ()
    order = "ref_count DESC" if args.top else "l.law_name"
    targets = conn.execute(
        f"""SELECT l.law_id AS law_id, l.law_name AS law_name, COUNT(*) AS ref_count
            FROM case_laws cl JOIN laws l ON l.law_name = cl.law_name
            WHERE l.law_id != '' {where}
            GROUP BY l.law_id, l.law_name
            ORDER BY {order}""",
        params,
    ).fetchall()
    cut = args.top or args.limit
    if cut:
        targets = targets[:cut]
    print(f"대상 법령: {len(targets):,}개")

    done_laws = {r[0] for r in conn.execute("SELECT DISTINCT law_id FROM law_versions")}
    done_msts = {r[0] for r in conn.execute("SELECT DISTINCT mst FROM law_articles")}

    for i, t in enumerate(targets, 1):
        law_id, law_name = t["law_id"], t["law_name"]
        try:
            # 1) 버전 목록
            if law_id in done_laws:
                versions = sorted(
                    (r["effective_date"], r["mst"], r["history_code"])
                    for r in conn.execute(
                        "SELECT effective_date, mst, history_code FROM law_versions WHERE law_id = ?",
                        (law_id,),
                    )
                )
            else:
                versions = fetch_versions(client, law_name, law_id)
                conn.executemany(
                    "INSERT OR IGNORE INTO law_versions "
                    "(law_id, law_name, effective_date, mst, history_code) VALUES (?,?,?,?,?)",
                    [(law_id, law_name, eff, mst, code) for eff, mst, code in versions],
                )
                conn.commit()
            if not versions:
                continue
            current_mst = versions[-1][1]

            # 2) 이 법령의 (선고일 시점 버전 mst -> 참조 조문) 집합
            needed: dict[str, set[str]] = {}
            mst_eff: dict[str, str] = {}
            for r in conn.execute(
                """SELECT cl.article_label AS lbl, c.decision_date AS dd
                   FROM case_laws cl JOIN cases c ON c.precedent_id = cl.precedent_id
                   WHERE cl.law_name = ? AND cl.article_label != ''""",
                (law_name,),
            ):
                dd = (r["dd"] or "").strip()
                if not (len(dd) == 8 and dd.isdigit()):
                    continue
                sel = in_force_mst(versions, dd)
                if not sel:
                    continue
                eff, mst = sel
                if mst == current_mst:
                    continue  # 현행과 동일 버전이면 case_laws.article_text로 충분
                needed.setdefault(mst, set()).add(r["lbl"])
                mst_eff[mst] = eff

            # 3) 필요한 과거 버전 본문에서 참조 조문 원문 수집
            for mst, labels in needed.items():
                if mst in done_msts:
                    continue
                rows = fetch_articles(client, mst, labels)
                conn.executemany(
                    "INSERT OR IGNORE INTO law_articles "
                    "(law_id, mst, effective_date, article_label, article_title, article_text) "
                    "VALUES (?,?,?,?,?,?)",
                    [(law_id, mst, mst_eff[mst], lbl, title, text) for lbl, title, text in rows],
                )
                conn.commit()
                done_msts.add(mst)

            print(f"  [{i}/{len(targets)}] {law_name}: 버전 {len(versions)} · 과거버전 {len(needed)}건 수집")
        except Exception as e:
            print(f"  [{i}/{len(targets)}] {law_name}: 실패 — {e}")
            continue

    nv = conn.execute("SELECT COUNT(*) FROM law_versions").fetchone()[0]
    na = conn.execute("SELECT COUNT(*) FROM law_articles").fetchone()[0]
    conn.close()
    print(f"\n완료: law_versions {nv:,}행 · law_articles {na:,}행")


if __name__ == "__main__":
    main()
