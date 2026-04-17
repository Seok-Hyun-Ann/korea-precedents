"""법령과 판례를 매칭한다.

판례의 '참조조문' 필드를 파싱하여 법령명+조문번호를 추출하고,
laws_parsed/law_article_index.json과 매칭하여 최종 결과를 생성한다.
"""
from __future__ import annotations

import json
import re
from collections import defaultdict
from pathlib import Path
from typing import Dict, List, Optional, Tuple

ROOT = Path(__file__).resolve().parent.parent
PRECEDENTS_PATH = ROOT / "data" / "precedents_merged" / "all_precedents.json"
LAW_INDEX_PATH = ROOT / "data" / "laws_parsed" / "law_article_index.json"
OUT_DIR = ROOT / "data" / "matched"

# 법령명 패턴: 한글+숫자+특수문자로 구성된 법령명 (법/령/칙/규정/헌법 등으로 끝남)
# (?=[^가-힣]|$) lookahead로 "공익법인의..." 중간의 "법"에서 끊기지 않도록 방지
LAW_NAME_RE = re.compile(
    r'((?:구\s+)?[가-힣A-Za-z0-9][가-힣A-Za-z0-9\s·ㆍ\-]*?'
    r'(?:기본법|특별법|특례법|촉진법|지원법|보호법|육성법|관리법|처벌법|단속법|규제법|'
    r'보장법|예방법|금지법|방지법|이행법|조정법|설치법|운영법|조직법|'
    r'시행규칙|시행령|헌법|법률|법|령|칙|규정|규칙|명령|조례|약관))'
    r'(?=[^가-힣]|$)'
)

# "시행령"/"시행규칙"만 단독으로 나온 경우 감지
STANDALONE_DECREE_RE = re.compile(r'^(시행령|시행규칙)\s')

# 폐지/개명된 법령 → 현행 법령명 매핑
ABOLISHED_LAW_ALIASES: Dict[str, str] = {
    # 민사/상사
    "경매법": "민사집행법",
    "파산법": "채무자 회복 및 파산에 관한 법률",
    "회사정리법": "채무자 회복 및 파산에 관한 법률",
    "호적법": "가족관계의 등록 등에 관한 법률",
    "섭외사법": "국제사법",
    "이자제한법": "이자제한법",

    # 부동산/토지
    "농지개혁법": "농지법",
    "토지수용법": "공익사업을 위한 토지 등의 취득 및 보상에 관한 법률",
    "도시계획법": "국토의 계획 및 이용에 관한 법률",
    "국토이용관리법": "국토의 계획 및 이용에 관한 법률",
    "토지구획정리사업법": "도시개발법",
    "도시재개발법": "도시 및 주거환경정비법",
    "지적법": "공간정보의 구축 및 관리 등에 관한 법률",
    "부동산중개업법": "공인중개사법",
    "공공용지의취득및손실보상에관한특례법": "공익사업을 위한 토지 등의 취득 및 보상에 관한 법률",
    "공유수면매립법": "공유수면 관리 및 매립에 관한 법률",
    "지가공시및토지등의평가에관한법률": "부동산 가격공시에 관한 법률",
    "택지소유상한에관한법률": "택지소유상한에관한법률",  # 폐지 but 자기 자신

    # 세금/관세
    "상속세법": "상속세 및 증여세법",
    "조세감면규제법": "조세특례제한법",
    "토지초과이득세법": "토지초과이득세법",  # 폐지

    # 노동
    "노동조합법": "노동조합 및 노동관계조정법",
    "노동쟁의조정법": "노동조합 및 노동관계조정법",

    # 형사/사회
    "사회보호법": "사회보호법",  # 폐지
    "사법서사법": "법무사법",

    # 선거/행정
    "공직선거및선거부정방지법": "공직선거법",

    # 산업/경제
    "증권거래법": "자본시장과 금융투자업에 관한 법률",
    "주택건설촉진법": "주택법",
    "의장법": "디자인보호법",
    "자동차운수사업법": "여객자동차 운수사업법",
    "건설업법": "건설산업기본법",
    "석유사업법": "석유 및 석유대체연료 사업법",
    "공중위생법": "공중위생관리법",
    "산림법": "산림자원의 조성 및 관리에 관한 법률",
    "부정경쟁방지법": "부정경쟁방지 및 영업비밀보호에 관한 법률",
    "상호신용금고법": "상호저축은행법",
    "교육법": "교육기본법",
    "문화재보호법": "문화재보호법",  # 현행 유지
    "불교재산관리법": "불교재산관리법",  # 현행명 동일
    "전기용품안전관리법": "전기용품 및 생활용품 안전관리법",
    "외국환관리법": "외국환거래법",
    "공장저당법": "공장 및 광업재단 저당법",
    "예산회계법": "국가재정법",
    "공동주택관리령": "공동주택관리법",
    "재판소법": "법원조직법",

    # 띄어쓰기 없는 형태도 추가
    "부동산소유권이전등기등에관한특별조치법": "부동산소유권 이전등기 등에 관한 특별조치법",
}

# 조문 패턴: 제N조, 제N조의M
ARTICLE_RE = re.compile(r'제(\d+)조(의\d+)?')

# 항 패턴: 제N항
PARAGRAPH_RE = re.compile(r'제(\d+)항')


def normalize_law_name(name: str) -> str:
    """법령명을 정규화한다 (공백/특수문자 통일)."""
    name = name.strip()
    name = name.replace("ㆍ", "·")
    name = re.sub(r'\s+', '', name)  # 공백 제거
    return name


def build_name_lookup(law_index: Dict[str, list]) -> Dict[str, str]:
    """정규화된 법령명 → 원래 법령명 매핑을 만든다."""
    lookup = {}
    for name in law_index:
        normalized = normalize_law_name(name)
        lookup[normalized] = name
    return lookup


def preprocess_ref_text(ref_text: str) -> str:
    """참조조문 원문을 전처리한다."""
    text = ref_text

    # 1) 괄호 안 부연설명 제거: "구 법인세법(1980.12.13. 법률 제3270호로 개정되기 전의 법)"
    text = re.sub(r'\([^)]*(?:개정|시행|폐지|제정|법률|대통령령|호)[^)]*\)', '', text)

    # 2) 공백형 조문 정규화: "제 12 조" → "제12조", "제 1 항" → "제1항"
    text = re.sub(r'제\s+(\d+)\s+조', r'제\1조', text)
    text = re.sub(r'제\s+(\d+)\s+항', r'제\1항', text)
    text = re.sub(r'제\s+(\d+)\s+호', r'제\1호', text)

    # 3) "조의 제" → "조의" (비표준 표기: "제17조의 제1항" → "제17조의" + "제1항")
    text = re.sub(r'조의\s+제(\d+)항', r'조 제\1항', text)

    return text


def extract_references(ref_text: str) -> List[Dict[str, str]]:
    """참조조문 문자열에서 (법령명, 조문번호) 쌍을 추출한다."""
    if not ref_text or not ref_text.strip():
        return []

    text = preprocess_ref_text(ref_text)

    refs = []
    current_law: Optional[str] = None
    prev_explicit_law: Optional[str] = None  # "같은 법" 해소용

    # 쉼표, 슬래시, 세미콜론으로 분리
    segments = re.split(r'[,/;]', text)

    for segment in segments:
        segment = segment.strip()
        if not segment:
            continue

        # "같은 법", "동법" 처리 → 이전 명시 법령으로 대체
        same_law = re.match(r'(같은\s*법|동법)\s*(시행령|시행규칙)?', segment)
        if same_law and prev_explicit_law:
            suffix = same_law.group(2) or ""
            if suffix:
                current_law = prev_explicit_law + suffix
            else:
                current_law = prev_explicit_law
        # "시행령 제X조", "시행규칙 제X조" 단독 → 이전 법령 + 시행령/시행규칙
        elif STANDALONE_DECREE_RE.match(segment) and prev_explicit_law:
            suffix = STANDALONE_DECREE_RE.match(segment).group(1)
            # 이전 법령이 이미 시행령/시행규칙으로 끝나면 그대로
            if not prev_explicit_law.endswith(suffix):
                current_law = prev_explicit_law + suffix
            else:
                current_law = prev_explicit_law
        else:
            # 법령명 찾기
            law_matches = list(LAW_NAME_RE.finditer(segment))
            if law_matches:
                # 가장 긴 매칭을 선택 (짧은 오매칭 방지)
                best = max(law_matches, key=lambda m: len(m.group(1)))
                raw_name = best.group(1).strip()
                # "구" 접두어 제거하여 저장
                clean = re.sub(r'^구\s*', '', raw_name)
                # 단독 "시행령"/"시행규칙"이 법령명으로 잡힌 경우 → 이전 법령 상속
                if clean in ("시행령", "시행규칙") and prev_explicit_law:
                    if not prev_explicit_law.endswith(clean):
                        current_law = prev_explicit_law + clean
                    else:
                        current_law = prev_explicit_law
                else:
                    current_law = clean
                    # 시행령/시행규칙이면 base 법령을 prev로 유지
                    base = re.sub(r'(시행령|시행규칙)$', '', clean)
                    if base:
                        prev_explicit_law = base
                    else:
                        prev_explicit_law = clean

        if not current_law:
            continue

        # 조문 찾기
        for m in ARTICLE_RE.finditer(segment):
            article_num = m.group(1)
            branch = m.group(2) or ""
            article_label = f"제{article_num}조{branch}"

            # 항 정보
            paragraph = ""
            para_match = PARAGRAPH_RE.search(segment[m.end():m.end() + 20])
            if para_match:
                paragraph = f"제{para_match.group(1)}항"

            refs.append({
                "law_name": current_law,
                "article_label": article_label,
                "paragraph": paragraph,
            })

    # 중복 제거
    seen = set()
    deduped = []
    for ref in refs:
        key = (ref["law_name"], ref["article_label"])
        if key not in seen:
            seen.add(key)
            deduped.append(ref)
    return deduped


def fuzzy_find_law(law_name: str, name_lookup: Dict[str, str]) -> Optional[str]:
    """법령명을 정규화하여 인덱스에서 찾는다."""
    normalized = normalize_law_name(law_name)

    # 정확히 일치
    if normalized in name_lookup:
        return name_lookup[normalized]

    # 약칭 처리: "같은 법", "동법" 등은 건너뜀 (extract_references에서 처리)
    if normalized in ("같은법", "동법", "같은법시행령", "동법시행령"):
        return None

    # 헌법: "대한민국헌법" 매칭
    if normalized == "헌법":
        if "대한민국헌법" in name_lookup:
            return name_lookup["대한민국헌법"]
        for k, v in name_lookup.items():
            if "헌법" in k:
                return v

    # "구" 접두어 제거 후 재시도 (구 소득세법 → 소득세법)
    if normalized.startswith("구"):
        stripped = normalized[1:]
        if stripped in name_lookup:
            return name_lookup[stripped]

    # "현행" 접두어 제거
    if normalized.startswith("현행"):
        stripped = normalized[2:]
        if stripped in name_lookup:
            return name_lookup[stripped]

    # 괄호 안 내용 제거 후 재시도
    no_paren = re.sub(r'\([^)]*\)', '', normalized)
    no_paren = normalize_law_name(no_paren)
    if no_paren and no_paren in name_lookup:
        return name_lookup[no_paren]

    # 폐지/개명 법령 별칭 매핑
    for old_name, new_name in ABOLISHED_LAW_ALIASES.items():
        old_norm = normalize_law_name(old_name)
        if normalized == old_norm:
            new_norm = normalize_law_name(new_name)
            if new_norm in name_lookup:
                return name_lookup[new_norm]
            # 별칭 자체가 인덱스에 없어도 매핑 정보는 반환 (폐지법령 표시용)
            return new_name

    # 띄어쓰기 변형 매칭: "관한법률" vs "관한 법률" 등
    # normalized에서 "에관한", "의", "및", "등에" 등 조사 앞뒤 공백 변형 시도
    for norm_key, orig_name in name_lookup.items():
        # 둘 다 공백 완전 제거 후 비교
        if normalized.replace(" ", "") == norm_key.replace(" ", "") and len(norm_key) >= 3:
            return orig_name

    # 부분 매칭: 인덱스 키가 입력의 접미사인 경우 (가장 긴 매칭 우선)
    candidates = []
    for norm_key, orig_name in name_lookup.items():
        if normalized.endswith(norm_key) and len(norm_key) >= 3:
            candidates.append((len(norm_key), orig_name))
    if candidates:
        candidates.sort(reverse=True)
        return candidates[0][1]

    return None


def main() -> None:
    print("=== 법령-판례 매칭 시작 ===\n")

    # 데이터 로드
    print("데이터 로드 중...")
    precedents = json.loads(PRECEDENTS_PATH.read_text(encoding="utf-8"))
    law_index = json.loads(LAW_INDEX_PATH.read_text(encoding="utf-8"))
    print(f"  판례: {len(precedents):,}건")
    print(f"  법령: {len(law_index):,}건")

    name_lookup = build_name_lookup(law_index)

    # 매칭 수행
    print("\n매칭 수행 중...")
    matched_links = []  # 개별 매칭 레코드
    law_to_cases = defaultdict(list)  # 법령명 → 판례 목록
    case_to_laws = defaultdict(list)  # 판례번호 → 법령 목록

    total_refs = 0
    matched_refs = 0
    unmatched_laws = defaultdict(int)

    for prec in precedents:
        ref_text = prec.get("reference_articles", "")
        if not ref_text or not ref_text.strip():
            continue

        refs = extract_references(ref_text)
        total_refs += len(refs)

        for ref in refs:
            orig_name = fuzzy_find_law(ref["law_name"], name_lookup)

            link = {
                "precedent_id": prec.get("precedent_id", ""),
                "case_number": prec.get("case_number", ""),
                "case_name": prec.get("case_name", ""),
                "court_name": prec.get("court_name", ""),
                "decision_date": prec.get("decision_date", ""),
                "case_type": prec.get("case_type", ""),
                "ref_law_name": ref["law_name"],
                "ref_article_label": ref["article_label"],
                "ref_paragraph": ref.get("paragraph", ""),
                "law_matched": orig_name is not None,
                "matched_law_name": orig_name or "",
            }

            # 매칭된 경우 조문 텍스트 첨부
            if orig_name and orig_name in law_index:
                for art in law_index[orig_name]:
                    if art["article_label"] == ref["article_label"]:
                        link["matched_article_title"] = art.get("article_title", "")
                        link["matched_article_text"] = art.get("article_text", "")[:300]
                        break

            matched_links.append(link)

            if orig_name:
                matched_refs += 1
                law_to_cases[orig_name].append({
                    "precedent_id": prec.get("precedent_id", ""),
                    "case_number": prec.get("case_number", ""),
                    "case_name": prec.get("case_name", ""),
                    "article_label": ref["article_label"],
                })
                case_to_laws[prec.get("case_number", "")].append({
                    "law_name": orig_name,
                    "article_label": ref["article_label"],
                })
            else:
                if ref["law_name"] not in ("같은 법", "동법", "같은법", "같은 법 시행령"):
                    unmatched_laws[ref["law_name"]] += 1

    print(f"\n=== 매칭 결과 ===")
    print(f"  총 참조 추출: {total_refs:,}건")
    print(f"  매칭 성공:    {matched_refs:,}건 ({matched_refs/total_refs*100:.1f}%)" if total_refs else "")
    print(f"  매칭 실패:    {total_refs - matched_refs:,}건")
    print(f"  매칭된 법령:  {len(law_to_cases):,}개")
    print(f"  매칭된 판례:  {len(case_to_laws):,}건")

    # 저장
    OUT_DIR.mkdir(parents=True, exist_ok=True)

    # 1) 전체 매칭 링크
    (OUT_DIR / "all_links.json").write_text(
        json.dumps(matched_links, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    print(f"\n전체 링크 저장: {OUT_DIR / 'all_links.json'}")

    # 2) 법령별 판례 인덱스 (상위 100개 법령)
    top_laws = sorted(law_to_cases.items(), key=lambda x: -len(x[1]))[:100]
    law_case_index = {
        name: {
            "case_count": len(cases),
            "cases": cases[:50],  # 법령당 상위 50건만
        }
        for name, cases in top_laws
    }
    (OUT_DIR / "law_to_cases_top100.json").write_text(
        json.dumps(law_case_index, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )

    # 3) 매칭 안 된 법령명 (상위 50개)
    top_unmatched = sorted(unmatched_laws.items(), key=lambda x: -x[1])[:50]
    (OUT_DIR / "unmatched_laws_top50.json").write_text(
        json.dumps(dict(top_unmatched), ensure_ascii=False, indent=2),
        encoding="utf-8",
    )

    # 4) 통계
    stats = {
        "total_precedents": len(precedents),
        "precedents_with_refs": sum(1 for p in precedents if p.get("reference_articles", "").strip()),
        "total_refs_extracted": total_refs,
        "matched_refs": matched_refs,
        "match_rate": f"{matched_refs/total_refs*100:.1f}%" if total_refs else "0%",
        "unique_laws_matched": len(law_to_cases),
        "unique_cases_matched": len(case_to_laws),
        "top10_laws": [(name, len(cases)) for name, cases in top_laws[:10]],
        "top10_unmatched": top_unmatched[:10],
    }
    (OUT_DIR / "stats.json").write_text(
        json.dumps(stats, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    print(f"통계 저장: {OUT_DIR / 'stats.json'}")


if __name__ == "__main__":
    main()
