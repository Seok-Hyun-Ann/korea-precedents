"""판례 전문을 규칙 기반으로 구조화 분석한다.

AI 없이 정규식과 패턴 매칭으로 판례에서 핵심 정보를 추출한다:
- 당사자 (원고/피고/피고인)
- 주문 (판결 결과)
- 판결 결과 분류 (기각/파기환송/취소/무죄 등)
- 이유 요약
- 쟁점 법률
- 쉬운 설명 (템플릿 기반)

사용법:
  python structurize_cases.py [--limit 1000] [--law 민법]
"""
from __future__ import annotations

import argparse
import json
import re
from collections import Counter
from pathlib import Path
from typing import Dict, List, Optional, Tuple

ROOT = Path(__file__).resolve().parent.parent
PRECEDENTS_PATH = ROOT / "data" / "precedents_merged" / "all_precedents.json"
MATCHED_PATH = ROOT / "data" / "matched" / "all_links.json"
LAWS_INDEX_PATH = ROOT / "data" / "laws_parsed" / "law_article_index.json"
OUT_DIR = ROOT / "data" / "structured"

# ── 섹션 추출 패턴 ──
SECTION_RE = re.compile(r'【([^】]+)】')

# ── 당사자 역할 분류 ──
PLAINTIFF_KEYWORDS = ("원고", "상고인", "항소인", "재항고인", "신청인", "채권자", "출원인")
DEFENDANT_KEYWORDS = ("피고", "피상고인", "피항소인", "상대방", "피신청인", "채무자", "피고인")

# ── 판결 결과 분류 ──
RESULT_PATTERNS = [
    ("파기환송", re.compile(r"파기.*환송|파기하고.*환송")),
    ("파기자판", re.compile(r"파기.*자판")),
    ("파기", re.compile(r"파기")),
    ("상고기각", re.compile(r"상고.*기각")),
    ("항소기각", re.compile(r"항소.*기각")),
    ("기각", re.compile(r"기각")),
    ("각하", re.compile(r"각하")),
    ("취소", re.compile(r"취소")),
    ("무죄", re.compile(r"무죄")),
    ("징역", re.compile(r"징역\s*(\d+)\s*[년월]")),
    ("벌금", re.compile(r"벌금\s*([\d,]+)\s*원")),
    ("인용", re.compile(r"인용")),
]

# ── 금액 추출 ──
MONEY_RE = re.compile(r"금?\s*([\d,]+)\s*원")

# ── 쉬운 설명 템플릿 ──
TEMPLATES = {
    "민사": {
        "상고기각": "이 사건은 {plaintiff}이(가) {defendant}을(를) 상대로 {case_name} 관련 소송을 제기한 사건입니다. 대법원은 하급심 판결이 옳다고 보고 상고를 기각했습니다. 즉, {ruling_for}의 손을 들어준 것입니다.",
        "파기환송": "이 사건은 {plaintiff}이(가) {defendant}을(를) 상대로 {case_name} 관련 소송을 제기한 사건입니다. 대법원은 하급심 판결에 문제가 있다고 보고 사건을 다시 심리하도록 돌려보냈습니다.",
        "기각": "이 사건은 {plaintiff}이(가) {defendant}을(를) 상대로 {case_name} 관련 소송을 제기한 사건입니다. 법원은 {plaintiff}의 청구를 받아들이지 않았습니다.",
        "default": "이 사건은 {plaintiff}이(가) {defendant}을(를) 상대로 {case_name} 관련 소송을 제기한 사건입니다.",
    },
    "형사": {
        "상고기각": "이 사건은 {defendant}이(가) {case_name}(으)로 기소된 형사 사건입니다. 대법원은 하급심의 판결이 타당하다고 보고 상고를 기각했습니다.",
        "파기환송": "이 사건은 {defendant}이(가) {case_name}(으)로 기소된 형사 사건입니다. 대법원은 하급심 판결에 잘못이 있다고 판단하여 다시 재판하도록 했습니다.",
        "무죄": "이 사건은 {defendant}이(가) {case_name}(으)로 기소되었으나 법원이 무죄를 선고한 사건입니다.",
        "default": "이 사건은 {defendant}이(가) {case_name}(으)로 기소된 형사 사건입니다.",
    },
    "일반행정": {
        "상고기각": "이 사건은 {plaintiff}이(가) {defendant}의 행정처분에 불복하여 소송을 제기한 사건입니다. 대법원은 하급심 판결을 유지하고 상고를 기각했습니다.",
        "취소": "이 사건은 {plaintiff}이(가) {defendant}의 행정처분에 불복하여 소송을 제기한 사건입니다. 법원은 해당 행정처분을 취소하라고 판결했습니다.",
        "default": "이 사건은 {plaintiff}이(가) {defendant}의 행정처분에 불복하여 소송을 제기한 사건입니다.",
    },
    "세무": {
        "상고기각": "이 사건은 {plaintiff}이(가) {defendant}의 세금 부과 처분에 불복하여 소송을 제기한 사건입니다. 대법원은 하급심 판결을 유지했습니다.",
        "취소": "이 사건은 {plaintiff}이(가) {defendant}의 세금 부과 처분에 불복하여 소송을 제기한 사건입니다. 법원은 해당 과세 처분을 취소하라고 판결했습니다.",
        "default": "이 사건은 {plaintiff}이(가) {defendant}의 세금 부과 처분에 불복하여 소송을 제기한 사건입니다.",
    },
}


def normalize_date(date_str: str) -> str:
    """단기(檀紀) 연도를 서기로 변환한다. 4289 → 1956 등."""
    if not date_str or len(date_str) < 4:
        return date_str
    try:
        y = int(date_str[:4])
        if 4200 <= y <= 4400:
            y -= 2333
            return str(y) + date_str[4:]
    except ValueError:
        pass
    return date_str


def extract_sections(full_text: str) -> Dict[str, str]:
    """전문에서 【】로 구분된 섹션을 추출한다."""
    sections = {}
    matches = list(SECTION_RE.finditer(full_text))
    for i, m in enumerate(matches):
        key = m.group(1).strip()
        start = m.end()
        end = matches[i + 1].start() if i + 1 < len(matches) else len(full_text)
        value = full_text[start:end].strip()
        # 키 정규화 (띄어쓰기 제거)
        norm_key = re.sub(r'\s+', '', key)
        sections[norm_key] = value
    return sections


def classify_party_role(section_key: str) -> Optional[str]:
    """섹션 키에서 당사자 역할을 분류한다.

    【원고, 피상고인】처럼 원고/피고 + 소송상 지위가 결합된 경우,
    첫 번째 키워드(원고/피고)가 실제 역할이다.
    쉼표로 분리하여 첫 번째 토큰의 역할을 우선한다.
    """
    # 쉼표/공백 구분으로 첫 번째 토큰 추출
    first_token = re.split(r'[,\s]+', section_key)[0].strip()

    # 첫 번째 토큰으로 판단
    if first_token in ("원고", "신청인", "채권자", "출원인", "항소인", "재항고인"):
        return "plaintiff"
    if first_token in ("피고", "피고인", "피신청인", "채무자", "상대방"):
        return "defendant"

    # 첫 토큰이 "상고인" 같은 지위만 있는 경우, 전체 키에서 원고/피고 포함 여부 확인
    if "원고" in section_key:
        return "plaintiff"
    if "피고" in section_key or "피고인" in section_key:
        return "defendant"

    # 상고인만 있는 경우 (원고/피고 명시 없음)
    for kw in PLAINTIFF_KEYWORDS:
        if kw in section_key:
            return "plaintiff"

    return None


def clean_party_name(raw: str) -> str:
    """당사자 이름에서 소송대리인 등 부가 정보를 제거한다."""
    name = raw.split("\n")[0].strip()
    # "소송대리인", "변호사", "변리사", "법무법인" 이전까지만
    for marker in ("소송대리인", "소송수행자", "변호사", "변리사", "법무법인", "담당변호사"):
        idx = name.find(marker)
        if idx > 0:
            name = name[:idx].strip().rstrip(",").rstrip()
            break
    return name[:100]


def extract_parties(sections: Dict[str, str]) -> Dict[str, str]:
    """당사자 정보를 추출한다."""
    parties = {"plaintiff": "", "defendant": "", "plaintiff_role": "", "defendant_role": ""}

    for key, value in sections.items():
        role = classify_party_role(key)
        if role == "plaintiff" and not parties["plaintiff"]:
            parties["plaintiff"] = clean_party_name(value)
            parties["plaintiff_role"] = key
        elif role == "defendant" and not parties["defendant"]:
            parties["defendant"] = clean_party_name(value)
            parties["defendant_role"] = key

    return parties


def extract_ruling(sections: Dict[str, str]) -> str:
    """주문(판결 결과)을 추출한다."""
    for key in ("주문", "주 문"):
        norm = key.replace(" ", "")
        if norm in sections:
            return sections[norm].strip()
    return ""


def extract_reasoning(sections: Dict[str, str]) -> str:
    """이유를 추출한다."""
    for key in ("이유", "이 유"):
        norm = key.replace(" ", "")
        if norm in sections:
            return sections[norm].strip()
    return ""


def classify_result(ruling: str) -> Tuple[str, str]:
    """판결 결과를 분류한다. (분류, 상세설명)을 반환."""
    if not ruling:
        return ("불명", "")
    for label, pattern in RESULT_PATTERNS:
        m = pattern.search(ruling)
        if m:
            detail = m.group(0)
            return (label, detail)
    return ("기타", ruling[:100])


def determine_ruling_for(result_class: str, case_type: str) -> str:
    """누가 이겼는지 판단한다."""
    if case_type == "형사":
        if result_class == "무죄":
            return "피고인(승)"
        elif result_class in ("상고기각",):
            return "판단불가(원심 확인 필요)"
        elif result_class in ("파기환송", "파기자판", "파기"):
            return "판단불가(재심리)"
        else:
            return ""
    else:
        if result_class == "상고기각":
            # 상고인이 진 것
            return "상고인 패소(원심 유지)"
        elif result_class in ("파기환송", "파기자판", "파기"):
            return "원심 파기(재심리)"
        elif result_class == "기각":
            return "원고 패소"
        elif result_class in ("취소", "인용"):
            return "원고 승소"
        elif result_class == "각하":
            return "소 각하(본안 판단 없음)"
        return ""


def extract_key_reasoning(reasoning: str, max_len: int = 2000) -> str:
    """이유 텍스트에서 핵심 부분을 추출한다."""
    if not reasoning:
        return ""

    # "따라서", "그러므로" 등 결론 부분 찾기
    conclusion_markers = ["따라서", "그러므로", "결국", "이상과 같은", "위와 같은 이유로",
                          "이 점을 지적하는", "논지는 이유 있다", "논지는 이유 없다",
                          "원심판결을 파기", "상고를 기각"]

    for marker in conclusion_markers:
        idx = reasoning.rfind(marker)
        if idx >= 0:
            excerpt = reasoning[max(0, idx - 300):idx + 1200].strip()
            if len(excerpt) > max_len:
                excerpt = excerpt[:max_len] + "..."
            return excerpt

    # 결론 마커를 못 찾으면 마지막 부분
    if len(reasoning) > max_len:
        return "..." + reasoning[-max_len:].strip()
    return reasoning


def build_easy_explanation(case: Dict, parties: Dict, result_class: str,
                           ruling_for: str, matched_laws: List[str]) -> str:
    """템플릿 기반으로 쉬운 설명을 생성한다."""
    case_type = case.get("case_type", "")
    templates = TEMPLATES.get(case_type, TEMPLATES.get("민사", {}))
    template = templates.get(result_class, templates.get("default", ""))

    plaintiff = parties.get("plaintiff", "원고") or "원고"
    defendant = parties.get("defendant", "피고") or "피고"
    case_name = case.get("case_name", "")

    # 이름이 너무 길면 줄이기
    if len(plaintiff) > 30:
        plaintiff = plaintiff[:30] + "..."
    if len(defendant) > 30:
        defendant = defendant[:30] + "..."

    explanation = template.format(
        plaintiff=plaintiff,
        defendant=defendant,
        case_name=case_name,
        ruling_for=ruling_for,
    )

    # 관련 법률 정보 추가
    if matched_laws:
        law_str = ", ".join(matched_laws[:3])
        explanation += f" 이 사건에서는 {law_str} 등이 적용되었습니다."

    return explanation


def structurize_case(case: Dict, links_by_id: Dict, law_index: Dict) -> Dict:
    """판례 1건을 구조화한다."""
    full_text = case.get("full_text", "")
    sections = extract_sections(full_text) if full_text else {}
    parties = extract_parties(sections)
    ruling = extract_ruling(sections)
    reasoning = extract_reasoning(sections)
    result_class, result_detail = classify_result(ruling)
    ruling_for = determine_ruling_for(result_class, case.get("case_type", ""))
    key_reasoning = extract_key_reasoning(reasoning)

    # 매칭된 법령 정보
    pid = str(case.get("precedent_id", ""))
    case_links = links_by_id.get(pid, [])
    matched_laws = []
    matched_articles_detail = []
    for link in case_links:
        if link.get("law_matched"):
            law_name = link.get("matched_law_name", "")
            art_label = link.get("ref_article_label", "")
            if law_name:
                matched_laws.append(f"{law_name} {art_label}")
                # 조문 텍스트 가져오기
                art_text = link.get("matched_article_text", "")
                art_title = link.get("matched_article_title", "")
                matched_articles_detail.append({
                    "law_name": law_name,
                    "article_label": art_label,
                    "article_title": art_title,
                    "article_text": art_text[:300] if art_text else "",
                })

    easy_explanation = build_easy_explanation(
        case, parties, result_class, ruling_for, matched_laws
    )

    # 판결요지를 쉬운 설명에 추가
    decision_summary = case.get("decision_summary", "")
    decision_points = case.get("decision_points", "")

    # 단기 연도 변환
    decision_date = normalize_date(case.get("decision_date", ""))

    # attribution 필드 구성
    source = case.get("source", "")
    precedent_id_str = str(case.get("precedent_id", ""))
    source_url = case.get("source_url", "")
    if not source_url and precedent_id_str:
        source_url = f"https://www.law.go.kr/판례/{precedent_id_str}"

    return {
        # 기본 정보
        "precedent_id": pid,
        "case_number": case.get("case_number", ""),
        "case_name": case.get("case_name", ""),
        "court_name": case.get("court_name", ""),
        "decision_date": decision_date,
        "case_type": case.get("case_type", ""),
        "decision_type": case.get("decision_type", ""),

        # 당사자
        "plaintiff": parties["plaintiff"],
        "plaintiff_role": parties["plaintiff_role"],
        "defendant": parties["defendant"],
        "defendant_role": parties["defendant_role"],

        # 판결 결과
        "ruling": ruling,
        "result_class": result_class,
        "result_detail": result_detail,
        "ruling_for": ruling_for,

        # 쟁점 및 판단
        "decision_points": decision_points or "",
        "decision_summary": decision_summary or "",
        "key_reasoning": key_reasoning,

        # 관련 법령
        "matched_laws": matched_laws,
        "matched_articles": matched_articles_detail[:10],

        # 쉬운 설명
        "easy_explanation": easy_explanation,

        # attribution (docs/attribution.md 준수)
        "source_system": case.get("source_system", "") or "국가법령정보센터",
        "source_url": source_url,
        "collected_at": case.get("collected_at", ""),
        "source": source or "법제처 국가법령정보 공동활용",
        "api_target": "prec",
        "request_type": "precedent_detail",
    }


def main() -> None:
    parser = argparse.ArgumentParser(description="판례 규칙 기반 구조화")
    parser.add_argument("--limit", type=int, default=0, help="처리할 최대 건수 (0=전체)")
    parser.add_argument("--law", type=str, help="특정 법령 관련 판례만 처리")
    args = parser.parse_args()

    print("=== 판례 규칙 기반 구조화 시작 ===\n")

    # 데이터 로드
    print("데이터 로드 중...")
    precedents = json.loads(PRECEDENTS_PATH.read_text(encoding="utf-8"))
    print(f"  판례: {len(precedents):,}건")

    links = []
    if MATCHED_PATH.exists():
        links = json.loads(MATCHED_PATH.read_text(encoding="utf-8"))
        print(f"  매칭 링크: {len(links):,}건")

    law_index = {}
    if LAWS_INDEX_PATH.exists():
        law_index = json.loads(LAWS_INDEX_PATH.read_text(encoding="utf-8"))
        print(f"  법령 인덱스: {len(law_index):,}건")

    # 링크를 판례ID별로 그룹핑
    links_by_id = {}
    for link in links:
        pid = str(link.get("precedent_id", ""))
        if pid not in links_by_id:
            links_by_id[pid] = []
        links_by_id[pid].append(link)

    # 특정 법령 필터링
    if args.law:
        target_ids = set()
        for link in links:
            if link.get("matched_law_name") == args.law and link.get("law_matched"):
                target_ids.add(str(link.get("precedent_id", "")))
        precedents = [p for p in precedents if str(p.get("precedent_id", "")) in target_ids]
        print(f"  '{args.law}' 관련 판례: {len(precedents):,}건")

    if args.limit > 0:
        precedents = precedents[:args.limit]
        print(f"  처리 대상: {len(precedents):,}건 (limit)")

    # 구조화
    print("\n구조화 진행 중...")
    results = []
    result_stats = Counter()

    for i, case in enumerate(precedents):
        if (i + 1) % 10000 == 0:
            print(f"  {i+1:,}/{len(precedents):,}...")
        structured = structurize_case(case, links_by_id, law_index)
        results.append(structured)
        result_stats[structured["result_class"]] += 1

    print(f"\n구조화 완료: {len(results):,}건")

    # 저장
    OUT_DIR.mkdir(parents=True, exist_ok=True)

    out_path = OUT_DIR / "all_structured.json"
    out_path.write_text(
        json.dumps(results, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    print(f"저장: {out_path}")

    # 통계
    has_plaintiff = sum(1 for r in results if r["plaintiff"])
    has_defendant = sum(1 for r in results if r["defendant"])
    has_ruling = sum(1 for r in results if r["ruling"])
    has_reasoning = sum(1 for r in results if r["key_reasoning"])
    has_matched = sum(1 for r in results if r["matched_laws"])

    stats = {
        "total": len(results),
        "has_plaintiff": has_plaintiff,
        "has_defendant": has_defendant,
        "has_ruling": has_ruling,
        "has_key_reasoning": has_reasoning,
        "has_matched_laws": has_matched,
        "result_classes": dict(result_stats.most_common()),
    }
    stats_path = OUT_DIR / "stats.json"
    stats_path.write_text(
        json.dumps(stats, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    print(f"통계: {stats_path}")

    # 판결 결과 분류 분포
    print("\n판결 결과 분류:")
    for cls, cnt in result_stats.most_common():
        print(f"  {cls}: {cnt:,}건")

    # 샘플 출력
    print("\n=== 샘플 출력 (첫 3건) ===")
    for r in results[:3]:
        print(f"\n--- {r['case_number']} ({r['case_name']}) ---")
        print(f"  원고: {r['plaintiff'][:50]}")
        print(f"  피고: {r['defendant'][:50]}")
        print(f"  결과: {r['result_class']} ({r['ruling_for']})")
        print(f"  관련법: {', '.join(r['matched_laws'][:3])}")
        print(f"  설명: {r['easy_explanation'][:150]}")


if __name__ == "__main__":
    main()
