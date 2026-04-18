"""국가법령정보센터 Open API로 판례를 수집한다.

HuggingFace 데이터셋(2023년 6월 기준)에 없는 최신 판례를 보충 수집하는 용도.
기존 HuggingFace 데이터가 있으면 이미 수집된 판례는 상세만 보충한다.

사용법:
  python fetch_cases_all.py [--pages 10] [--display 100]
"""
from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Dict, List

from api_client import LawApiClient, mask_oc_in_url, parse_xml, save_text_sanitized

ROOT = Path(__file__).resolve().parent.parent
RAW_DIR = ROOT / "data" / "raw" / "cases_api"
OUT_DIR = ROOT / "data" / "precedents_api"
HF_DIR = ROOT / "data" / "precedents_hf"


def text_of(node, tag: str) -> str:
    child = node.find(tag)
    return child.text.strip() if child is not None and child.text else ""


def load_existing_ids() -> set[str]:
    """이미 HuggingFace에서 받은 판례 ID 목록을 로드한다."""
    hf_path = HF_DIR / "all_precedents.json"
    if not hf_path.exists():
        return set()
    data = json.loads(hf_path.read_text(encoding="utf-8"))
    return {str(row.get("precedent_id", "")) for row in data}


def fetch_case_list(client: LawApiClient, page: int = 1, display: int = 100) -> List[Dict[str, str]]:
    xml_text = client.search("prec", page=page, display=display)
    save_text_sanitized(RAW_DIR / f"case-list-page-{page}.xml", xml_text)
    timestamp = datetime.now(timezone.utc).isoformat()
    root = parse_xml(xml_text)

    total_count = text_of(root, "totalCnt") or text_of(root, "totalcount")
    if page == 1 and total_count:
        print(f"  API 전체 판례 수: {total_count}")

    rows = []
    for case in root.findall(".//prec"):
        precedent_id = text_of(case, "판례일련번호")
        rows.append({
            "precedent_id": precedent_id,
            "case_name": text_of(case, "사건명"),
            "case_number": text_of(case, "사건번호"),
            "court_name": text_of(case, "법원명"),
            "decision_date": text_of(case, "선고일자"),
            "case_type": text_of(case, "사건종류명"),
            "decision_type": text_of(case, "판결유형"),
            "detail_link": mask_oc_in_url(text_of(case, "판례상세링크")),
            "collected_at": timestamp,
            "source": "open_api",
        })
    return rows


def fetch_case_detail(client: LawApiClient, precedent_id: str) -> Dict[str, str]:
    xml_text = client.service("prec", ID=precedent_id)
    save_text_sanitized(RAW_DIR / f"case-{precedent_id}.xml", xml_text)
    timestamp = datetime.now(timezone.utc).isoformat()
    root = parse_xml(xml_text)
    return {
        "precedent_id": precedent_id,
        "case_name": text_of(root, "사건명"),
        "case_number": text_of(root, "사건번호"),
        "court_name": text_of(root, "법원명"),
        "decision_date": text_of(root, "선고일자"),
        "decision_type_label": text_of(root, "선고"),
        "case_type": text_of(root, "사건종류명"),
        "decision_type": text_of(root, "판결유형"),
        "decision_points": text_of(root, "판시사항"),
        "decision_summary": text_of(root, "판결요지"),
        "reference_articles": text_of(root, "참조조문"),
        "reference_cases": text_of(root, "참조판례"),
        "full_text": text_of(root, "판례내용"),
        "collected_at": timestamp,
        "source": "open_api",
    }


def main() -> None:
    parser = argparse.ArgumentParser(description="Open API 판례 수집")
    parser.add_argument("--pages", type=int, default=5, help="수집할 페이지 수 (기본: 5)")
    parser.add_argument("--display", type=int, default=100, help="페이지당 건수 (기본: 100)")
    parser.add_argument("--fetch-details", action="store_true", help="상세 정보도 수집 (느림)")
    args = parser.parse_args()

    client = LawApiClient()
    existing_ids = load_existing_ids()
    print(f"기존 HuggingFace 판례: {len(existing_ids):,}건")

    all_rows: list[dict] = []
    new_ids: list[str] = []

    for page in range(1, args.pages + 1):
        print(f"페이지 {page}/{args.pages} 수집 중...")
        rows = fetch_case_list(client, page=page, display=args.display)
        if not rows:
            print("  더 이상 결과 없음. 중단.")
            break
        all_rows.extend(rows)
        for row in rows:
            if row["precedent_id"] not in existing_ids:
                new_ids.append(row["precedent_id"])

    print(f"\n목록 수집 완료: {len(all_rows):,}건 (신규: {len(new_ids):,}건)")

    # 신규 판례 상세 수집
    if args.fetch_details and new_ids:
        print(f"\n신규 {len(new_ids)}건 상세 수집 중...")
        details = []
        for i, pid in enumerate(new_ids, 1):
            print(f"  [{i}/{len(new_ids)}] {pid}")
            try:
                detail = fetch_case_detail(client, pid)
                details.append(detail)
            except Exception as e:
                print(f"    오류: {e}")
        # 상세가 있는 건은 목록 데이터를 대체
        detail_by_id = {d["precedent_id"]: d for d in details}
        all_rows = [detail_by_id.get(r["precedent_id"], r) for r in all_rows]

    OUT_DIR.mkdir(parents=True, exist_ok=True)
    out_path = OUT_DIR / "all_precedents.json"
    out_path.write_text(
        json.dumps(all_rows, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    print(f"\n저장 완료: {out_path}")
    print(f"다음 단계: python merge_precedents.py 실행하여 HuggingFace 데이터와 병합")


if __name__ == "__main__":
    main()
