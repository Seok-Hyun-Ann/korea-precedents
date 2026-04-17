"""legalize-kr repo의 법령 Markdown 파일을 파싱하여 JSON 인덱스를 생성한다.

각 법령의 메타데이터(frontmatter)와 조문 목록을 추출한다.
"""
from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Dict, List, Optional

ROOT = Path(__file__).resolve().parent.parent
LAWS_REPO = ROOT / "data" / "legalize-kr" / "kr"
OUT_DIR = ROOT / "data" / "laws_parsed"

# frontmatter 파싱
FRONTMATTER_RE = re.compile(r"^---\s*\n(.*?)\n---\s*\n", re.DOTALL)

# 조문 패턴: ##### 제123조 (제목) 또는 ##### 제123조의2 (제목)
ARTICLE_RE = re.compile(
    r"^#{1,6}\s*제(?P<num>\d+)조(?P<branch>의\d+)?\s*(?:\((?P<title>[^)]*)\))?\s*$",
    re.MULTILINE,
)


def parse_frontmatter(text: str) -> Dict[str, str]:
    m = FRONTMATTER_RE.match(text)
    if not m:
        return {}
    meta = {}
    for line in m.group(1).split("\n"):
        line = line.strip()
        if not line or line.startswith("-"):
            continue
        if ":" in line:
            key, _, val = line.partition(":")
            val = val.strip().strip("'\"")
            meta[key.strip()] = val
    return meta


def parse_articles(text: str) -> List[Dict[str, str]]:
    """Markdown에서 조문을 추출한다."""
    matches = list(ARTICLE_RE.finditer(text))
    articles = []
    for i, m in enumerate(matches):
        start = m.end()
        end = matches[i + 1].start() if i + 1 < len(matches) else len(text)
        body = text[start:end].strip()
        # 다음 섹션 헤더(#으로 시작하는 줄) 이전까지만 본문으로 취급
        body_lines = []
        for line in body.split("\n"):
            if re.match(r"^#{1,4}\s+제\d+", line):
                break
            if re.match(r"^#{1,3}\s+", line) and not line.strip().startswith("#####"):
                break
            body_lines.append(line)
        body_text = "\n".join(body_lines).strip()
        # bold 마크다운 제거 (항 번호 등)
        body_text = re.sub(r"\*\*([^*]+)\*\*", r"\1", body_text)

        num = m.group("num")
        branch = m.group("branch") or ""
        title = m.group("title") or ""
        article_label = f"제{num}조{branch}"

        articles.append({
            "article_label": article_label,
            "article_num": num,
            "article_branch": branch,
            "article_title": title,
            "article_text": body_text,
        })
    return articles


def parse_law_file(path: Path) -> Optional[Dict]:
    text = path.read_text(encoding="utf-8")
    meta = parse_frontmatter(text)
    if not meta.get("제목"):
        return None

    articles = parse_articles(text)
    law_type = path.stem  # 법률, 시행령, 시행규칙 등
    dir_name = path.parent.name

    return {
        "law_name": meta.get("제목", dir_name),
        "law_dir": dir_name,
        "law_type": law_type,
        "law_id": meta.get("법령ID", ""),
        "law_mst": meta.get("법령MST", ""),
        "law_category": meta.get("법령구분", ""),
        "ministry": meta.get("소관부처", ""),
        "promulgation_date": meta.get("공포일자", ""),
        "effective_date": meta.get("시행일자", ""),
        "status": meta.get("상태", ""),
        "source_url": meta.get("출처", ""),
        "article_count": len(articles),
        "articles": articles,
    }


def main() -> None:
    OUT_DIR.mkdir(parents=True, exist_ok=True)

    if not LAWS_REPO.exists():
        print(f"법령 데이터 없음: {LAWS_REPO}")
        print("먼저 legalize-kr repo를 clone하세요.")
        return

    law_dirs = sorted([d for d in LAWS_REPO.iterdir() if d.is_dir()])
    print(f"법령 디렉토리 수: {len(law_dirs)}")

    all_laws = []
    total_articles = 0
    errors = 0

    for law_dir in law_dirs:
        md_files = list(law_dir.glob("*.md"))
        for md_file in md_files:
            try:
                law = parse_law_file(md_file)
                if law:
                    all_laws.append(law)
                    total_articles += law["article_count"]
            except Exception as e:
                errors += 1
                if errors <= 5:
                    print(f"  오류: {md_file.name} in {law_dir.name}: {e}")

    print(f"파싱 완료: {len(all_laws)}개 법령, {total_articles:,}개 조문 (오류: {errors})")

    # 법령명 → 조문 인덱스 (매칭용)
    law_index = {}
    for law in all_laws:
        name = law["law_name"]
        if name not in law_index:
            law_index[name] = []
        for art in law["articles"]:
            law_index[name].append({
                "article_label": art["article_label"],
                "article_title": art["article_title"],
                "article_text": art["article_text"][:500],  # 인덱스용 요약
            })

    # 전체 법령 저장 (조문 본문 포함)
    out_path = OUT_DIR / "all_laws.json"
    out_path.write_text(
        json.dumps(all_laws, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    print(f"전체 법령 저장: {out_path}")

    # 법령명 인덱스 저장 (매칭용, 가벼움)
    index_path = OUT_DIR / "law_article_index.json"
    index_path.write_text(
        json.dumps(law_index, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    print(f"법령 인덱스 저장: {index_path}")

    # 통계
    types = {}
    statuses = {}
    for law in all_laws:
        types[law["law_category"]] = types.get(law["law_category"], 0) + 1
        statuses[law["status"]] = statuses.get(law["status"], 0) + 1

    stats = {
        "total_laws": len(all_laws),
        "total_articles": total_articles,
        "law_types": types,
        "statuses": statuses,
        "errors": errors,
    }
    stats_path = OUT_DIR / "stats.json"
    stats_path.write_text(
        json.dumps(stats, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    print(f"통계 저장: {stats_path}")


if __name__ == "__main__":
    main()
