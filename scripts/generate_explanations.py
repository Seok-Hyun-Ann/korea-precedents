"""판례를 구조화 분석하고 일반인이 이해하기 쉬운 해설을 생성한다.

Claude API를 사용하여 판례를 분석하고 쉬운 언어로 변환한다.

사용법:
  # 민법 관련 판례 5건 해설 생성
  python generate_explanations.py --law 민법 --limit 5

  # 특정 판례 1건 해설 생성
  python generate_explanations.py --case-number "2020다12345"

환경변수:
  ANTHROPIC_API_KEY: Claude API 키 (필수)
"""
from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path
from typing import Dict, List, Optional

ROOT = Path(__file__).resolve().parent.parent
MATCHED_DIR = ROOT / "data" / "matched"
PRECEDENTS_PATH = ROOT / "data" / "precedents_merged" / "all_precedents.json"
OUT_DIR = ROOT / "data" / "explanations"

SYSTEM_PROMPT = """\
당신은 한국 법률 전문가이면서 동시에 일반인에게 법률 지식을 쉽게 전달하는 교육자입니다.
주어진 판례 정보를 분석하여, 법을 전혀 모르는 일반인도 이해할 수 있도록 쉬운 말로 설명해 주세요.

반드시 아래 JSON 형식으로만 응답하세요 (다른 텍스트 없이):
{
  "title": "한 줄로 요약한 사건 제목 (일반인이 이해하기 쉽게)",
  "category": "사건 분류 (예: 계약분쟁, 손해배상, 이혼, 임대차, 상속, 사기, 폭행 등)",
  "story": "이 사건이 어떻게 시작되었고 무슨 일이 있었는지를 이야기처럼 설명 (3-5문장)",
  "issue": "핵심 쟁점이 무엇이었는지 쉬운 말로 설명 (1-2문장)",
  "related_law": "어떤 법 조항이 적용되었는지와 그 조항이 무슨 뜻인지 쉬운 설명",
  "result": "판결 결과 (누가 이겼는지, 어떤 판결이 내려졌는지)",
  "reasoning": "법원이 왜 그렇게 판결했는지 핵심 논리를 쉬운 말로 설명 (2-3문장)",
  "lesson": "이 판례에서 일반인이 알아두면 좋은 교훈이나 시사점 (1-2문장)",
  "difficulty": "상/중/하 (법률 지식 필요 수준)"
}
"""


def build_prompt(case: Dict, matched_law_info: Optional[Dict] = None) -> str:
    parts = [f"## 판례 정보\n"]
    parts.append(f"- 사건번호: {case.get('case_number', '없음')}")
    parts.append(f"- 사건명: {case.get('case_name', '없음')}")
    parts.append(f"- 법원: {case.get('court_name', '없음')}")
    parts.append(f"- 선고일자: {case.get('decision_date', '없음')}")
    parts.append(f"- 사건종류: {case.get('case_type', '없음')}")
    parts.append(f"- 판결유형: {case.get('decision_type', '없음')}")

    if case.get("decision_points"):
        parts.append(f"\n## 판시사항\n{case['decision_points']}")

    if case.get("decision_summary"):
        parts.append(f"\n## 판결요지\n{case['decision_summary']}")

    if case.get("reference_articles"):
        parts.append(f"\n## 참조조문\n{case['reference_articles']}")

    if case.get("reference_cases"):
        parts.append(f"\n## 참조판례\n{case['reference_cases']}")

    if case.get("full_text"):
        # 전문이 너무 길면 앞부분만
        full = case["full_text"]
        if len(full) > 4000:
            full = full[:4000] + "\n\n... (이하 생략)"
        parts.append(f"\n## 판결 전문 (일부)\n{full}")

    if matched_law_info:
        parts.append(f"\n## 관련 법령 조문")
        parts.append(f"- 법령명: {matched_law_info.get('law_name', '')}")
        parts.append(f"- 조문: {matched_law_info.get('article_label', '')}")
        if matched_law_info.get("article_text"):
            parts.append(f"- 조문 내용: {matched_law_info['article_text']}")

    parts.append("\n위 판례를 분석하여 JSON 형식으로 응답해 주세요.")
    return "\n".join(parts)


def call_claude(prompt: str, api_key: str) -> Dict:
    """Claude API를 호출하여 판례 해설을 생성한다."""
    import anthropic

    client = anthropic.Anthropic(api_key=api_key)
    message = client.messages.create(
        model="claude-sonnet-4-20250514",
        max_tokens=2000,
        system=SYSTEM_PROMPT,
        messages=[{"role": "user", "content": prompt}],
    )
    text = message.content[0].text.strip()

    # JSON 파싱 (코드블록 안에 있을 수 있음)
    if text.startswith("```"):
        text = text.split("\n", 1)[1]
        text = text.rsplit("```", 1)[0]
    return json.loads(text)


def find_cases_for_law(law_name: str, precedents: List[Dict], links: List[Dict], limit: int) -> List[Dict]:
    """특정 법령과 매칭된 판례를 찾는다."""
    matched_ids = set()
    matched_articles = {}
    for link in links:
        if link.get("matched_law_name") == law_name and link.get("law_matched"):
            pid = link["precedent_id"]
            matched_ids.add(pid)
            if pid not in matched_articles:
                matched_articles[pid] = {
                    "law_name": law_name,
                    "article_label": link.get("ref_article_label", ""),
                    "article_text": link.get("matched_article_text", ""),
                }

    # 판례 찾기 (판시사항/판결요지가 있는 것 우선)
    results = []
    prec_by_id = {str(p.get("precedent_id", "")): p for p in precedents}
    for pid in matched_ids:
        p = prec_by_id.get(str(pid))
        if p and (p.get("decision_points") or p.get("decision_summary")):
            results.append((p, matched_articles.get(pid)))
            if len(results) >= limit:
                break

    return results


def find_case_by_number(case_number: str, precedents: List[Dict]) -> Optional[Dict]:
    for p in precedents:
        if p.get("case_number") == case_number:
            return p
    return None


def main() -> None:
    parser = argparse.ArgumentParser(description="판례 해설 생성")
    parser.add_argument("--law", type=str, help="특정 법령 관련 판례 해설 (예: 민법)")
    parser.add_argument("--case-number", type=str, help="특정 사건번호 (예: 2020다12345)")
    parser.add_argument("--limit", type=int, default=5, help="생성할 해설 수 (기본: 5)")
    parser.add_argument("--dry-run", action="store_true", help="API 호출 없이 프롬프트만 출력")
    args = parser.parse_args()

    api_key = os.environ.get("ANTHROPIC_API_KEY", "")
    if not api_key and not args.dry_run:
        print("오류: ANTHROPIC_API_KEY 환경변수를 설정해 주세요.")
        print("  export ANTHROPIC_API_KEY='sk-ant-...'")
        sys.exit(1)

    if not args.dry_run:
        try:
            import anthropic
        except ImportError:
            print("오류: anthropic 패키지를 설치해 주세요.")
            print("  pip install anthropic")
            sys.exit(1)

    # 데이터 로드
    print("데이터 로드 중...")
    precedents = json.loads(PRECEDENTS_PATH.read_text(encoding="utf-8"))
    links_path = MATCHED_DIR / "all_links.json"
    links = json.loads(links_path.read_text(encoding="utf-8")) if links_path.exists() else []
    print(f"  판례: {len(precedents):,}건, 링크: {len(links):,}건")

    # 대상 판례 선정
    targets = []
    if args.case_number:
        case = find_case_by_number(args.case_number, precedents)
        if case:
            targets.append((case, None))
        else:
            print(f"사건번호 '{args.case_number}'를 찾을 수 없습니다.")
            sys.exit(1)
    elif args.law:
        targets = find_cases_for_law(args.law, precedents, links, args.limit)
        if not targets:
            print(f"'{args.law}' 관련 판례를 찾을 수 없습니다.")
            sys.exit(1)
        print(f"  '{args.law}' 관련 판례 {len(targets)}건 선정")
    else:
        # 기본: 주요 법령에서 골고루 선택
        for law_name in ["민법", "형법", "근로기준법", "상법", "행정소송법"]:
            found = find_cases_for_law(law_name, precedents, links, 1)
            targets.extend(found)
        targets = targets[:args.limit]

    OUT_DIR.mkdir(parents=True, exist_ok=True)
    results = []

    for i, (case, law_info) in enumerate(targets, 1):
        case_num = case.get("case_number", "unknown")
        print(f"\n[{i}/{len(targets)}] {case_num}: {case.get('case_name', '')}")

        prompt = build_prompt(case, law_info)

        if args.dry_run:
            print(f"  프롬프트 길이: {len(prompt)}자")
            print(f"  --- 프롬프트 미리보기 (처음 500자) ---")
            print(prompt[:500])
            print("  --- (이하 생략) ---")
            continue

        try:
            explanation = call_claude(prompt, api_key)
            result = {
                "case_number": case_num,
                "case_name": case.get("case_name", ""),
                "court_name": case.get("court_name", ""),
                "decision_date": case.get("decision_date", ""),
                "case_type": case.get("case_type", ""),
                "related_law": law_info.get("law_name", "") if law_info else "",
                "related_article": law_info.get("article_label", "") if law_info else "",
                "explanation": explanation,
            }
            results.append(result)

            # 개별 파일 저장
            safe_name = case_num.replace("/", "_").replace(" ", "_")
            (OUT_DIR / f"{safe_name}.json").write_text(
                json.dumps(result, ensure_ascii=False, indent=2),
                encoding="utf-8",
            )
            print(f"  -> {explanation.get('title', '(제목 없음)')}")
        except Exception as e:
            print(f"  오류: {e}")

    if results:
        # 전체 결과 저장
        (OUT_DIR / "all_explanations.json").write_text(
            json.dumps(results, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
        print(f"\n총 {len(results)}건 해설 생성 완료 → {OUT_DIR}")


if __name__ == "__main__":
    main()
