"""이미 수집된 `data/` 하위 파일에서 개인 OC 값을 `YOUR_OC`로 치환한다.

HuggingFace 업로드 전 정리나, 과거 raw 덤프의 개인 OC 제거용 일회성 도구다.
JSON·XML·텍스트 파일을 모두 대상으로 하며, 변경이 있었던 경우에만 파일을 덮어쓴다.
"""
from __future__ import annotations

import argparse
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
DEFAULT_TARGET = ROOT / "data"
PLACEHOLDER = "YOUR_OC"
OC_PATTERN = re.compile(r"([?&])OC=[^&\"'<>\s]+")
TARGET_SUFFIXES = {".json", ".xml", ".txt", ".csv", ".jsonl"}


def sanitize_text(text: str) -> tuple[str, int]:
    new_text, count = OC_PATTERN.subn(lambda m: f"{m.group(1)}OC={PLACEHOLDER}", text)
    return new_text, count


def iter_files(root: Path):
    for path in root.rglob("*"):
        if not path.is_file():
            continue
        if path.suffix.lower() not in TARGET_SUFFIXES:
            continue
        yield path


def main() -> None:
    parser = argparse.ArgumentParser(description="data/ 하위의 OC 값 치환")
    parser.add_argument("--target", type=Path, default=DEFAULT_TARGET, help="스캔할 루트 디렉터리")
    parser.add_argument("--dry-run", action="store_true", help="변경 없이 파일별 예상 치환 수만 출력")
    args = parser.parse_args()

    if not args.target.exists():
        raise SystemExit(f"대상 디렉터리가 없습니다: {args.target}")

    total_files = 0
    total_occurrences = 0
    changed_files = 0

    for path in iter_files(args.target):
        total_files += 1
        try:
            original = path.read_text(encoding="utf-8")
        except UnicodeDecodeError:
            continue
        new_text, count = sanitize_text(original)
        if count == 0:
            continue
        total_occurrences += count
        changed_files += 1
        print(f"  [{count:5d}] {path.relative_to(ROOT)}")
        if not args.dry_run:
            path.write_text(new_text, encoding="utf-8")

    mode = "dry-run" if args.dry_run else "적용"
    print(
        f"\n{mode} 완료: 스캔 파일 {total_files}개, 변경 대상 {changed_files}개, "
        f"치환된 OC 점유 {total_occurrences}건."
    )


if __name__ == "__main__":
    main()
