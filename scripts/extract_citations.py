"""판례 간 인용 관계를 추출한다.

reference_cases 필드와 전문 텍스트에서 다른 판례 인용을 파싱하여
인용 네트워크(citation graph)를 생성한다.

출력:
  data/citations/citation_edges.json    — (citing, cited) 엣지 목록
  data/citations/citation_stats.json    — 통계 (최다 인용 판례 등)
  data/citations/most_cited_top200.json — 가장 많이 인용된 판례 200건
"""
from __future__ import annotations

import json
import re
from collections import Counter, defaultdict
from pathlib import Path
from typing import Dict, List, Set, Tuple

ROOT = Path(__file__).resolve().parent.parent
PRECEDENTS_PATH = ROOT / "data" / "precedents_merged" / "all_precedents.json"
OUT_DIR = ROOT / "data" / "citations"

# 유효한 사건 유형 코드 (선고, 판결 등 절차용어 제외)
VALID_CASE_TYPES = {
    "가", "나", "다", "라", "마", "바", "사", "아", "자", "차", "카", "타", "파", "하",
    "누", "두", "부", "수", "우", "주", "추", "투", "푸", "후",
    "도", "고", "노", "모", "보", "소", "오", "조", "초",
    "다카", "누카", "도카", "모카", "타카",
    "다나", "다가",
    "그", "느", "르", "므", "브", "스", "으",
    "허", "헌", "형", "행",
    "재", "감",
    # 복합 유형
    "형공", "민공", "행공",
    "선거", "재항",
}

# 판례번호 패턴: "84누135", "2019다12345", "2020도1234" 등
CASE_NUM_RE = re.compile(r'(\d{2,4})\s*([가-힣]+)\s*(\d+)')

# 전문 텍스트에서 판례 인용 패턴
# "대법원 2020. 3. 12. 선고 2019다12345 판결"
FULL_CITE_RE = re.compile(
    r'(?:대법원|대법|헌법재판소|헌재|서울고등법원|부산고등법원|[가-힣]+법원)\s*'
    r'\d{4}\s*[.\s]+\s*\d{1,2}\s*[.\s]+\s*\d{1,2}\s*[.\s]*선고\s*'
    r'(\d{2,4})\s*([가-힣]+)\s*(\d+)'
)

# 유효하지 않은 사건유형 (절차용어 등)
INVALID_TYPE_WORDS = {"선고", "판결", "결정", "전원합의체", "자판", "심판", "재판", "항고"}


def is_valid_case_type(type_code: str) -> bool:
    """사건유형 코드가 유효한지 검사한다."""
    tc = type_code.strip()
    if tc in INVALID_TYPE_WORDS:
        return False
    if tc in VALID_CASE_TYPES:
        return True
    # 2글자 이상이면서 알려진 무효 유형이 아닌 경우 허용
    if len(tc) >= 2 and tc not in INVALID_TYPE_WORDS:
        return True
    return False


def normalize_case_number(year: str, type_code: str, num: str) -> str:
    """판례번호를 정규화한다."""
    y = int(year)
    # 단기(檀紀) 연도 변환: 4200대 → 서기 (단기 - 2333 = 서기)
    if y >= 4200 and y <= 4400:
        y = y - 2333
        year = str(y)
    # 2자리 연도를 4자리로
    elif len(year) == 2:
        year = f"{'19' if y >= 50 else '20'}{year}"
    # 공백 제거
    type_code = type_code.strip()
    return f"{year}{type_code}{num}"


def parse_reference_cases(ref_text: str) -> List[str]:
    """reference_cases 필드에서 판례번호를 추출한다."""
    if not ref_text or not ref_text.strip():
        return []

    results = []
    for m in CASE_NUM_RE.finditer(ref_text):
        year, type_code, num = m.group(1), m.group(2), m.group(3)
        if not is_valid_case_type(type_code):
            continue
        normalized = normalize_case_number(year, type_code, num)
        results.append(normalized)

    return list(dict.fromkeys(results))  # 순서 유지하며 중복 제거


def parse_fulltext_citations(full_text: str) -> List[str]:
    """전문 텍스트에서 판례 인용을 추출한다."""
    if not full_text:
        return []

    results = []
    for m in FULL_CITE_RE.finditer(full_text):
        year, type_code, num = m.group(1), m.group(2), m.group(3)
        if not is_valid_case_type(type_code):
            continue
        normalized = normalize_case_number(year, type_code, num)
        results.append(normalized)

    return list(dict.fromkeys(results))


def main() -> None:
    print("=== citation extraction ===\n")

    print("loading data...")
    precedents = json.loads(PRECEDENTS_PATH.read_text(encoding="utf-8"))
    print(f"  precedents: {len(precedents):,}")

    # 전체 판례번호 인덱스 (존재하는 판례만 엣지에 포함)
    existing_cases: Dict[str, dict] = {}
    for p in precedents:
        cn = p.get("case_number", "")
        if cn:
            m = CASE_NUM_RE.search(cn)
            if m and is_valid_case_type(m.group(2)):
                norm = normalize_case_number(m.group(1), m.group(2), m.group(3))
                existing_cases[norm] = {
                    "precedent_id": p.get("precedent_id", ""),
                    "case_number": cn,
                    "case_name": p.get("case_name", ""),
                    "court_name": p.get("court_name", ""),
                    "decision_date": p.get("decision_date", ""),
                }

    print(f"  normalized: {len(existing_cases):,}")

    # 인용 관계 추출
    print("\nextracting citations...")
    edges: List[Dict[str, str]] = []
    cited_counter: Counter = Counter()
    citing_counter: Counter = Counter()

    cases_with_refs = 0
    total_citations = 0

    for i, p in enumerate(precedents):
        if (i + 1) % 20000 == 0:
            print(f"  {i+1:,}/{len(precedents):,}...")

        cn = p.get("case_number", "")
        if not cn:
            continue

        m = CASE_NUM_RE.search(cn)
        if not m or not is_valid_case_type(m.group(2)):
            continue
        citing_norm = normalize_case_number(m.group(1), m.group(2), m.group(3))

        # 1) reference_cases 필드에서 추출
        ref_cases = parse_reference_cases(p.get("reference_cases", ""))

        # 2) 전문에서 추출 (reference_cases에 없는 것만 추가)
        fulltext_cites = parse_fulltext_citations(p.get("full_text", ""))
        all_cited = list(dict.fromkeys(ref_cases + fulltext_cites))

        # 자기 자신 인용 제거
        all_cited = [c for c in all_cited if c != citing_norm]

        if not all_cited:
            continue

        cases_with_refs += 1

        for cited_norm in all_cited:
            total_citations += 1
            cited_counter[cited_norm] += 1
            citing_counter[citing_norm] += 1

            edge = {
                "citing": citing_norm,
                "cited": cited_norm,
                "citing_case_number": cn,
                "citing_case_name": p.get("case_name", ""),
            }

            if cited_norm in existing_cases:
                edge["cited_case_number"] = existing_cases[cited_norm]["case_number"]
                edge["cited_case_name"] = existing_cases[cited_norm]["case_name"]
                edge["cited_in_db"] = True
            else:
                edge["cited_case_number"] = cited_norm
                edge["cited_in_db"] = False

            edges.append(edge)

    print(f"\n=== results ===")
    print(f"  cases with citations: {cases_with_refs:,}")
    print(f"  total edges: {total_citations:,}")
    print(f"  in-DB edges: {sum(1 for e in edges if e.get('cited_in_db')):,}")
    print(f"  external edges: {sum(1 for e in edges if not e.get('cited_in_db')):,}")

    # 저장
    OUT_DIR.mkdir(parents=True, exist_ok=True)

    db_edges = [e for e in edges if e.get("cited_in_db")]
    (OUT_DIR / "citation_edges.json").write_text(
        json.dumps(db_edges, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    print(f"\nin-DB edges saved: {len(db_edges):,}")

    # 최다 인용 판례
    top_cited = cited_counter.most_common(200)
    most_cited = []
    for norm_cn, count in top_cited:
        info = existing_cases.get(norm_cn, {})
        most_cited.append({
            "normalized_case_number": norm_cn,
            "case_number": info.get("case_number", norm_cn),
            "case_name": info.get("case_name", ""),
            "court_name": info.get("court_name", ""),
            "decision_date": info.get("decision_date", ""),
            "cited_count": count,
            "in_db": norm_cn in existing_cases,
        })

    (OUT_DIR / "most_cited_top200.json").write_text(
        json.dumps(most_cited, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )

    # 최다 인용을 하는 판례
    top_citing = citing_counter.most_common(50)
    most_citing = []
    for norm_cn, count in top_citing:
        info = existing_cases.get(norm_cn, {})
        most_citing.append({
            "normalized_case_number": norm_cn,
            "case_number": info.get("case_number", norm_cn),
            "case_name": info.get("case_name", ""),
            "citing_count": count,
        })

    # 통계
    in_db_cited = {cn for cn, _ in cited_counter.items() if cn in existing_cases}
    stats = {
        "total_precedents": len(precedents),
        "cases_with_citations": cases_with_refs,
        "total_citation_edges": total_citations,
        "db_internal_edges": len(db_edges),
        "unique_cited_cases": len(cited_counter),
        "unique_cited_in_db": len(in_db_cited),
        "avg_citations_per_case": round(total_citations / cases_with_refs, 1) if cases_with_refs else 0,
        "top20_most_cited": [
            {"case_number": existing_cases.get(cn, {}).get("case_number", cn),
             "case_name": existing_cases.get(cn, {}).get("case_name", ""),
             "cited_count": count}
            for cn, count in top_cited[:20]
        ],
        "top10_most_citing": [
            {"case_number": existing_cases.get(cn, {}).get("case_number", cn),
             "case_name": existing_cases.get(cn, {}).get("case_name", ""),
             "citing_count": count}
            for cn, count in top_citing[:10]
        ],
    }
    (OUT_DIR / "citation_stats.json").write_text(
        json.dumps(stats, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    print("stats saved")

    # 결과 출력 (ASCII-safe)
    print(f"\n=== most cited TOP 20 ===")
    for item in most_cited[:20]:
        cn = item["case_number"]
        name = item["case_name"][:30] if item["case_name"] else ""
        db = "[O]" if item["in_db"] else "[ ]"
        print(f"  {db} {cn:20s} {item['cited_count']:>4}  {name}")

    print(f"\n=== most citing TOP 10 ===")
    for item in most_citing[:10]:
        cn = item["case_number"]
        name = item["case_name"][:30] if item["case_name"] else ""
        print(f"  {cn:20s} {item['citing_count']:>4}  {name}")


if __name__ == "__main__":
    main()
