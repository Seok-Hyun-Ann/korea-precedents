"""HuggingFace에서 판례 데이터셋을 다운로드하여 JSON으로 저장한다.

데이터셋: joonhok-exo-ai/korean_law_open_data_precedents
- 법제처 국가법령정보센터 판례 전체 (2023년 6월 기준, 약 85,830건)
"""
from __future__ import annotations

import json
from pathlib import Path

from datasets import load_dataset

ROOT = Path(__file__).resolve().parent.parent
OUT_DIR = ROOT / "data" / "precedents_hf"

# HuggingFace 필드 → 프로젝트 통일 필드 매핑
FIELD_MAP = {
    "판례정보일련번호": "precedent_id",
    "사건명": "case_name",
    "사건번호": "case_number",
    "선고일자": "decision_date",
    "선고": "decision_type_label",
    "법원명": "court_name",
    "사건종류명": "case_type",
    "판결유형": "decision_type",
    "판시사항": "decision_points",
    "판결요지": "decision_summary",
    "참조조문": "reference_articles",
    "참조판례": "reference_cases",
    "전문": "full_text",
}


def normalize_row(row: dict) -> dict:
    out = {}
    for k_kr, k_en in FIELD_MAP.items():
        val = row.get(k_kr)
        if val is None:
            val = ""
        if k_en == "precedent_id":
            val = str(val)
        elif k_en == "decision_date":
            val = str(val) if val else ""
        else:
            val = str(val).strip() if val else ""
        out[k_en] = val
    out["source"] = "huggingface"
    return out


def main() -> None:
    print("HuggingFace 판례 데이터셋 다운로드 시작...")
    ds = load_dataset("joonhok-exo-ai/korean_law_open_data_precedents", split="train")
    print(f"총 {len(ds):,}건 로드 완료")

    OUT_DIR.mkdir(parents=True, exist_ok=True)

    rows = [normalize_row(row) for row in ds]

    # 중복 제거 (판례정보일련번호 기준)
    seen = set()
    deduped = []
    duplicates = 0
    for row in rows:
        pid = row["precedent_id"]
        if pid in seen:
            duplicates += 1
            continue
        seen.add(pid)
        deduped.append(row)

    print(f"중복 {duplicates}건 제거 → {len(deduped):,}건 저장")

    out_path = OUT_DIR / "all_precedents.json"
    out_path.write_text(
        json.dumps(deduped, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    print(f"저장 완료: {out_path}")

    # 요약 통계
    courts = {}
    case_types = {}
    for row in deduped:
        courts[row["court_name"]] = courts.get(row["court_name"], 0) + 1
        case_types[row["case_type"]] = case_types.get(row["case_type"], 0) + 1

    stats = {
        "total": len(deduped),
        "duplicates_removed": duplicates,
        "courts": dict(sorted(courts.items(), key=lambda x: -x[1])[:20]),
        "case_types": case_types,
        "source": "joonhok-exo-ai/korean_law_open_data_precedents",
    }
    stats_path = OUT_DIR / "stats.json"
    stats_path.write_text(
        json.dumps(stats, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    print(f"통계 저장: {stats_path}")


if __name__ == "__main__":
    main()
