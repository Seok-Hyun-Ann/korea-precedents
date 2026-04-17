"""HuggingFace 판례 + Open API 판례를 병합하고 중복을 제거한다.

사용법:
  1. 먼저 download_hf_precedents.py 실행 (HuggingFace 다운로드)
  2. 그 다음 fetch_cases_all.py 실행 (Open API 추가 수집)
  3. 이 스크립트 실행 → data/precedents_merged/ 에 최종 결과 생성
"""
from __future__ import annotations

import json
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
HF_DIR = ROOT / "data" / "precedents_hf"
API_DIR = ROOT / "data" / "precedents_api"
OUT_DIR = ROOT / "data" / "precedents_merged"


def load_json(path: Path) -> list[dict]:
    if not path.exists():
        print(f"  [건너뜀] {path} 없음")
        return []
    data = json.loads(path.read_text(encoding="utf-8"))
    if isinstance(data, list):
        return data
    return []


def merge_row(existing: dict, new: dict) -> dict:
    """두 레코드를 병합한다. 빈 필드를 새 데이터로 채운다."""
    merged = dict(existing)
    for k, v in new.items():
        if k == "source":
            continue
        if v and (not merged.get(k)):
            merged[k] = v
    # source 태그 병합
    sources = set()
    for src_str in [existing.get("source", ""), new.get("source", "")]:
        for s in src_str.split(","):
            s = s.strip()
            if s:
                sources.add(s)
    merged["source"] = ",".join(sorted(sources))
    return merged


def main() -> None:
    print("=== 판례 데이터 병합 시작 ===\n")

    # 1) HuggingFace 데이터 로드
    hf_rows = load_json(HF_DIR / "all_precedents.json")
    print(f"HuggingFace: {len(hf_rows):,}건")

    # 2) Open API 데이터 로드
    api_rows = load_json(API_DIR / "all_precedents.json")
    print(f"Open API:    {len(api_rows):,}건")

    # 3) 병합 (precedent_id 기준)
    by_id: dict[str, dict] = {}
    for row in hf_rows:
        pid = str(row.get("precedent_id", ""))
        if pid:
            by_id[pid] = row

    hf_count = len(by_id)
    new_from_api = 0
    updated_from_api = 0

    for row in api_rows:
        pid = str(row.get("precedent_id", ""))
        if not pid:
            continue
        if pid in by_id:
            by_id[pid] = merge_row(by_id[pid], row)
            updated_from_api += 1
        else:
            by_id[pid] = row
            new_from_api += 1

    merged = sorted(by_id.values(), key=lambda x: str(x.get("precedent_id", "")))

    print(f"\n병합 결과:")
    print(f"  HuggingFace 원본:     {hf_count:,}건")
    print(f"  API에서 신규 추가:    {new_from_api:,}건")
    print(f"  API에서 보충 업데이트: {updated_from_api:,}건")
    print(f"  최종 합계:            {len(merged):,}건")

    # 4) 저장
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    out_path = OUT_DIR / "all_precedents.json"
    out_path.write_text(
        json.dumps(merged, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    print(f"\n저장 완료: {out_path}")

    # 5) 통계
    courts: dict[str, int] = {}
    case_types: dict[str, int] = {}
    sources: dict[str, int] = {}
    for row in merged:
        courts[row.get("court_name", "")] = courts.get(row.get("court_name", ""), 0) + 1
        case_types[row.get("case_type", "")] = case_types.get(row.get("case_type", ""), 0) + 1
        for s in row.get("source", "").split(","):
            s = s.strip()
            if s:
                sources[s] = sources.get(s, 0) + 1

    stats = {
        "total": len(merged),
        "new_from_api": new_from_api,
        "updated_from_api": updated_from_api,
        "courts_top20": dict(sorted(courts.items(), key=lambda x: -x[1])[:20]),
        "case_types": case_types,
        "sources": sources,
    }
    stats_path = OUT_DIR / "stats.json"
    stats_path.write_text(
        json.dumps(stats, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    print(f"통계 저장: {stats_path}")


if __name__ == "__main__":
    main()
