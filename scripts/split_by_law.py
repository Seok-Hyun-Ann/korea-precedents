"""구조화된 판례를 법령별로 분리 저장한다.

data/structured/all_structured.json → data/by_law/{법령명}.json

각 법령 파일에는 해당 법령과 매칭된 판례만 포함된다.
하나의 판례가 여러 법령에 매칭되면 각 법령 파일에 모두 포함된다.
"""
from __future__ import annotations

import json
import re
from collections import defaultdict
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
STRUCTURED_PATH = ROOT / "data" / "structured" / "all_structured.json"
OUT_DIR = ROOT / "data" / "by_law"


def safe_filename(name: str) -> str:
    """법령명을 안전한 파일명으로 변환한다."""
    name = name.strip()
    # 파일명에 쓸 수 없는 문자 치환
    name = re.sub(r'[\\/:*?"<>|]', '_', name)
    return name


def main() -> None:
    print("데이터 로드 중...")
    data = json.loads(STRUCTURED_PATH.read_text(encoding="utf-8"))
    print(f"  전체 판례: {len(data):,}건")

    # 법령별 그룹핑
    by_law: dict[str, list[dict]] = defaultdict(list)
    no_law_count = 0

    for case in data:
        laws = case.get("matched_laws", [])
        if not laws:
            no_law_count += 1
            continue

        # 법령명만 추출 (끝의 조문번호 제거): "민법 제750조" → "민법"
        # 단, 법령명 자체에 "제N조"가 포함된 경우를 고려하여
        # "법/령/칙/규정/법률" 뒤의 마지막 " 제N조"만 제거
        seen_laws = set()
        for law_article in laws:
            # 마지막 " 제N조" 패턴 위치를 찾아서 제거 (법/령/칙 등 뒤에 오는 것만)
            m = re.search(r'(?:법|령|칙|규정|규칙|법률|약관|조례|헌법)\s+(제\d+조)', law_article)
            if m:
                # 매칭된 "제N조" 시작 위치에서 자름
                law_name = law_article[:m.start(1)].strip()
            else:
                law_name = law_article.strip()
            if law_name and law_name not in seen_laws:
                seen_laws.add(law_name)
                by_law[law_name].append(case)

    print(f"  법령 매칭 없음: {no_law_count:,}건")
    print(f"  분류된 법령 수: {len(by_law):,}개")

    # 사건번호 중복 제거 (precedent_id 기준, 같은 법령 파일 내에서)
    total_dupes = 0
    for law_name in by_law:
        seen_ids = set()
        deduped = []
        for case in by_law[law_name]:
            pid = case.get("precedent_id", "")
            if pid and pid in seen_ids:
                total_dupes += 1
                continue
            seen_ids.add(pid)
            deduped.append(case)
        by_law[law_name] = deduped
    print(f"  법령 파일 내 중복 제거: {total_dupes}건")

    # 건수 기준 정렬
    sorted_laws = sorted(by_law.items(), key=lambda x: -len(x[1]))

    # 저장
    OUT_DIR.mkdir(parents=True, exist_ok=True)

    index = []
    for law_name, cases in sorted_laws:
        filename = safe_filename(law_name) + ".json"
        out_path = OUT_DIR / filename
        out_path.write_text(
            json.dumps(cases, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
        index.append({
            "law_name": law_name,
            "case_count": len(cases),
            "filename": filename,
        })

    # 인덱스 파일 저장
    index_path = OUT_DIR / "_index.json"
    index_path.write_text(
        json.dumps(index, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )

    # 결과 출력
    print(f"\n저장 완료: {OUT_DIR}")
    print(f"  총 {len(index)}개 법령 파일 생성\n")
    print("상위 20개 법령:")
    for item in index[:20]:
        print(f"  {item['law_name']:30s} {item['case_count']:>6,}건  → {item['filename']}")


if __name__ == "__main__":
    main()
