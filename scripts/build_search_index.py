"""구조화된 판례 데이터의 검색 인덱스를 생성한다.

역색인(inverted index) 방식으로 다양한 필드를 검색할 수 있다.
AI 없이 형태소 단위 분리(간이) + n-gram으로 구현한다.

출력:
  data/search/case_number_index.json  — 사건번호 → precedent_id
  data/search/law_index.json          — 법령명 → [precedent_id, ...]
  data/search/date_index.json         — 연도별 → [precedent_id, ...]
  data/search/court_index.json        — 법원별 → [precedent_id, ...]
  data/search/keyword_index.json      — 키워드(사건명 2-gram) → [precedent_id, ...]
  data/search/result_index.json       — 판결결과별 → [precedent_id, ...]
  data/search/search_meta.json        — 인덱스 메타정보
"""
from __future__ import annotations

import json
import re
from collections import defaultdict
from pathlib import Path
from typing import Dict, List, Set

ROOT = Path(__file__).resolve().parent.parent
STRUCTURED_PATH = ROOT / "data" / "structured" / "all_structured.json"
CITATIONS_PATH = ROOT / "data" / "citations" / "citation_edges.json"
OUT_DIR = ROOT / "data" / "search"


def extract_keywords(text: str) -> Set[str]:
    """텍스트에서 검색 키워드를 추출한다 (한글 2-gram + 단어)."""
    if not text:
        return set()

    keywords = set()

    # 한글만 추출
    korean = re.sub(r'[^가-힣\s]', ' ', text)
    words = korean.split()

    # 각 단어를 키워드로
    for w in words:
        if len(w) >= 2:
            keywords.add(w)
        # 2-gram
        for i in range(len(w) - 1):
            keywords.add(w[i:i+2])

    return keywords


def main() -> None:
    print("=== 검색 인덱스 생성 ===\n")

    print("데이터 로드 중...")
    data = json.loads(STRUCTURED_PATH.read_text(encoding="utf-8"))
    print(f"  판례: {len(data):,}건")

    # 인용 데이터 로드
    citations_by_id = defaultdict(list)
    cited_count = defaultdict(int)
    if CITATIONS_PATH.exists():
        citations = json.loads(CITATIONS_PATH.read_text(encoding="utf-8"))
        for edge in citations:
            citations_by_id[edge["citing"]].append(edge["cited"])
            cited_count[edge.get("cited_case_number", edge["cited"])] += 1
        print(f"  인용 관계: {len(citations):,}건")

    # 인덱스 생성
    print("\n인덱스 생성 중...")

    # 1. 사건번호 인덱스
    case_number_idx: Dict[str, str] = {}

    # 2. 법령 인덱스
    law_idx: Dict[str, List[str]] = defaultdict(list)

    # 3. 연도별 인덱스
    date_idx: Dict[str, List[str]] = defaultdict(list)

    # 4. 법원별 인덱스
    court_idx: Dict[str, List[str]] = defaultdict(list)

    # 5. 키워드 인덱스 (사건명 기반)
    keyword_idx: Dict[str, List[str]] = defaultdict(list)

    # 6. 판결결과별 인덱스
    result_idx: Dict[str, List[str]] = defaultdict(list)

    # 7. 사건유형별 인덱스
    type_idx: Dict[str, List[str]] = defaultdict(list)

    for i, case in enumerate(data):
        if (i + 1) % 20000 == 0:
            print(f"  {i+1:,}/{len(data):,}...")

        pid = case.get("precedent_id", "")
        if not pid:
            continue

        # 사건번호
        cn = case.get("case_number", "")
        if cn:
            case_number_idx[cn] = pid

        # 법령
        for law_article in case.get("matched_laws", []):
            # 법령명만 (조문 제거)
            law_name = re.sub(r'\s*제\d+조.*$', '', law_article).strip()
            if law_name:
                law_idx[law_name].append(pid)

        # 연도 (단기 연도 변환: 4289 → 1956 등)
        dd = case.get("decision_date", "")
        if dd and len(dd) >= 4:
            try:
                y = int(dd[:4])
                if 4200 <= y <= 4400:
                    y = y - 2333
                if 1940 <= y <= 2030:
                    date_idx[str(y)].append(pid)
            except ValueError:
                pass

        # 법원
        court = case.get("court_name", "")
        if court:
            court_idx[court].append(pid)

        # 판결결과
        rc = case.get("result_class", "")
        if rc:
            result_idx[rc].append(pid)

        # 사건유형
        ct = case.get("case_type", "")
        if ct:
            type_idx[ct].append(pid)

        # 키워드 (사건명에서)
        case_name = case.get("case_name", "")
        for kw in extract_keywords(case_name):
            keyword_idx[kw].append(pid)

    # 법령 인덱스 중복 제거
    for key in law_idx:
        law_idx[key] = list(dict.fromkeys(law_idx[key]))

    print(f"\n인덱스 생성 완료:")
    print(f"  사건번호: {len(case_number_idx):,}건")
    print(f"  법령: {len(law_idx):,}개")
    print(f"  연도: {len(date_idx):,}개")
    print(f"  법원: {len(court_idx):,}개")
    print(f"  판결결과: {len(result_idx):,}개")
    print(f"  사건유형: {len(type_idx):,}개")
    print(f"  키워드: {len(keyword_idx):,}개")

    # 저장
    OUT_DIR.mkdir(parents=True, exist_ok=True)

    # compact 저장 (인덱스용이므로 indent 없이)
    def save_json(filename: str, obj):
        path = OUT_DIR / filename
        path.write_text(json.dumps(obj, ensure_ascii=False), encoding="utf-8")
        size_mb = path.stat().st_size / 1024 / 1024
        print(f"  {filename}: {size_mb:.1f}MB")

    print("\n저장 중...")
    save_json("case_number_index.json", case_number_idx)
    save_json("law_index.json", dict(law_idx))
    save_json("date_index.json", dict(date_idx))
    save_json("court_index.json", dict(court_idx))
    save_json("result_index.json", dict(result_idx))
    save_json("type_index.json", dict(type_idx))
    save_json("keyword_index.json", dict(keyword_idx))

    # 메타 정보
    meta = {
        "total_cases": len(data),
        "index_counts": {
            "case_number": len(case_number_idx),
            "law": len(law_idx),
            "year": len(date_idx),
            "court": len(court_idx),
            "result_class": len(result_idx),
            "case_type": len(type_idx),
            "keyword": len(keyword_idx),
        },
        "year_distribution": {
            year: len(pids) for year, pids in sorted(date_idx.items())
        },
        "court_distribution": {
            court: len(pids) for court, pids
            in sorted(court_idx.items(), key=lambda x: -len(x[1]))[:20]
        },
        "type_distribution": {
            ct: len(pids) for ct, pids
            in sorted(type_idx.items(), key=lambda x: -len(x[1]))
        },
        "result_distribution": {
            rc: len(pids) for rc, pids
            in sorted(result_idx.items(), key=lambda x: -len(x[1]))
        },
        "top30_laws_by_cases": [
            {"law": law, "count": len(pids)}
            for law, pids in sorted(law_idx.items(), key=lambda x: -len(x[1]))[:30]
        ],
    }
    save_json("search_meta.json", meta)

    # 연도별 분포 출력
    print(f"\n=== 연도별 판례 분포 (10년 단위) ===")
    decade_counts = defaultdict(int)
    for year, pids in date_idx.items():
        try:
            decade = f"{int(year)//10*10}s"
            decade_counts[decade] += len(pids)
        except ValueError:
            pass
    for decade, count in sorted(decade_counts.items()):
        bar = "#" * (count // 500)
        print(f"  {decade}: {count:>6,}  {bar}")

    # 법원별 분포 출력
    print(f"\n=== 법원별 분포 (상위 10) ===")
    for court, pids in sorted(court_idx.items(), key=lambda x: -len(x[1]))[:10]:
        print(f"  {court:20s} {len(pids):>6,}건")


if __name__ == "__main__":
    main()
