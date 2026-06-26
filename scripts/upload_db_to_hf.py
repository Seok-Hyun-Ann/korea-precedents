"""갱신된 precedents.db를 HuggingFace 데이터셋에 업로드한다.

법령 버전(선고 당시 조문) 등 새 테이블을 반영한 DB를 배포 리포에 올릴 때 사용한다.
업로드 전에 WAL을 체크포인트하여 -wal에 남은 변경을 본 파일에 병합한다.

  python scripts/upload_db_to_hf.py
  PRECEDENTS_HF_REPO=내아이디/리포 python scripts/upload_db_to_hf.py
"""
from __future__ import annotations

import os
import sqlite3
from pathlib import Path

from huggingface_hub import HfApi

ROOT = Path(__file__).resolve().parent.parent
DB_PATH = ROOT / "data" / "precedents.db"
REPO = os.environ.get("PRECEDENTS_HF_REPO", "SH98/korea-precedents")
FILENAME = os.environ.get("PRECEDENTS_HF_FILE", "precedents.db")


def main() -> None:
    if not DB_PATH.exists():
        print(f"[오류] DB가 없습니다: {DB_PATH}")
        return

    # WAL 체크포인트 — 업로드 파일이 완전하도록 -wal 내용을 본 파일에 병합한다.
    conn = sqlite3.connect(str(DB_PATH))
    conn.execute("PRAGMA wal_checkpoint(TRUNCATE)")
    conn.close()

    size_mb = DB_PATH.stat().st_size / 1024 / 1024
    print(f"업로드 시작: {DB_PATH.name} ({size_mb:,.0f}MB) -> {REPO}/{FILENAME}")
    HfApi().upload_file(
        path_or_fileobj=str(DB_PATH),
        path_in_repo=FILENAME,
        repo_id=REPO,
        repo_type="dataset",
        commit_message="Add law version tables (선고 당시 조문 비교)",
    )
    print("업로드 완료")


if __name__ == "__main__":
    main()
