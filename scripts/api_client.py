from __future__ import annotations

import os
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict
from urllib.parse import urlencode
import xml.etree.ElementTree as ET

import requests

BASE_SEARCH_URL = "http://www.law.go.kr/DRF/lawSearch.do"
BASE_SERVICE_URL = "http://www.law.go.kr/DRF/lawService.do"
DEFAULT_TYPE = "XML"
DEFAULT_TIMEOUT = 30
DEFAULT_SLEEP_SECONDS = 0.5


def _load_oc() -> str:
    """환경변수에서 국가법령정보센터 OC(접속 ID)를 읽는다.

    우선순위: LAW_GO_KR_OC > .env 파일
    신청: https://open.law.go.kr/LSO/openApi/guideList.do
    """
    oc = os.environ.get("LAW_GO_KR_OC", "").strip()
    if oc:
        return oc

    # .env 파일 자동 로드 (python-dotenv 없이 간이 파싱)
    env_path = Path(__file__).resolve().parent.parent / ".env"
    if env_path.exists():
        for line in env_path.read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if not line or line.startswith("#"):
                continue
            if "=" not in line:
                continue
            k, v = line.split("=", 1)
            if k.strip() == "LAW_GO_KR_OC":
                return v.strip().strip('"').strip("'")
    return ""


@dataclass
class LawApiClient:
    oc: str = field(default_factory=_load_oc)
    response_type: str = DEFAULT_TYPE
    timeout: int = DEFAULT_TIMEOUT
    sleep_seconds: float = DEFAULT_SLEEP_SECONDS

    def __post_init__(self) -> None:
        if not self.oc:
            raise RuntimeError(
                "국가법령정보센터 OC(접속 ID)가 설정되지 않았습니다.\n"
                "  1. https://open.law.go.kr/LSO/openApi/guideList.do 에서 신청\n"
                "  2. 환경변수 설정: export LAW_GO_KR_OC=your_id\n"
                "     또는 .env 파일에 LAW_GO_KR_OC=your_id 추가\n"
                "  * 앱 실행만 원한다면 OC 키는 필요 없습니다. "
                "HuggingFace에서 사전 수집된 DB를 자동 다운로드합니다."
            )

    def _request(self, base_url: str, params: Dict[str, Any]) -> str:
        merged = {"OC": self.oc, "type": self.response_type, **params}
        response = requests.get(base_url, params=merged, timeout=self.timeout)
        response.raise_for_status()
        time.sleep(self.sleep_seconds)
        return response.text

    def search(self, target: str, **params: Any) -> str:
        return self._request(BASE_SEARCH_URL, {"target": target, **params})

    def service(self, target: str, **params: Any) -> str:
        return self._request(BASE_SERVICE_URL, {"target": target, **params})


def parse_xml(xml_text: str) -> ET.Element:
    return ET.fromstring(xml_text)


def save_text(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")


def build_request_url(base_url: str, params: Dict[str, Any]) -> str:
    return f"{base_url}?{urlencode(params, doseq=True)}"
