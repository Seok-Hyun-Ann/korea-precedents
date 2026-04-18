from __future__ import annotations

import os
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict
import re
from urllib.parse import urlencode
import xml.etree.ElementTree as ET

import requests

BASE_SEARCH_URL = "http://www.law.go.kr/DRF/lawSearch.do"
BASE_SERVICE_URL = "http://www.law.go.kr/DRF/lawService.do"
DEFAULT_TYPE = "XML"
DEFAULT_TIMEOUT = 30
DEFAULT_SLEEP_SECONDS = 0.5
PUBLIC_OC_PLACEHOLDER = "YOUR_OC"


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


def save_text_sanitized(path: Path, text: str) -> None:
    """응답 본문에 섞여 오는 OC 파라미터를 치환한 뒤 저장한다.

    법제처 API는 응답 XML 안의 `판례상세링크`·`법령상세링크` 등에 요청 시 사용한
    OC 값을 그대로 echo한다. 원본 그대로 저장하면 raw 덤프에도 OC가 남으므로,
    파일로 쓰기 전에 `mask_oc_in_url`의 규칙으로 치환한다.
    """
    sanitized = _OC_PARAM_PATTERN.sub(
        lambda m: f"{m.group(1)}OC={PUBLIC_OC_PLACEHOLDER}", text
    )
    save_text(path, sanitized)


def build_request_url(base_url: str, params: Dict[str, Any]) -> str:
    return f"{base_url}?{urlencode(params, doseq=True)}"


def build_public_url(base_url: str, params: Dict[str, Any]) -> str:
    """OC 값을 마스킹한 공개용 URL.

    수집 기록(`source_url`)은 provenance 식별에만 쓰이므로 개인 OC를 남길 이유가 없다.
    실제 요청은 `LawApiClient._request`가 수행하며, 이 함수가 만드는 URL은 저장 전용이다.
    """
    public_params = {**params, "OC": PUBLIC_OC_PLACEHOLDER}
    return f"{base_url}?{urlencode(public_params, doseq=True)}"


_OC_PARAM_PATTERN = re.compile(r"([?&])OC=[^&]*")


def mask_oc_in_url(url: str) -> str:
    """URL 문자열에서 `OC=...` 파라미터 값을 `YOUR_OC`로 치환한다.

    API 응답이 자체적으로 돌려주는 `detail_link` 같은 문자열에 개인 OC가 섞여 들어오는
    경우를 막기 위해 저장 직전에 호출한다.
    """
    if not url:
        return url
    return _OC_PARAM_PATTERN.sub(lambda m: f"{m.group(1)}OC={PUBLIC_OC_PLACEHOLDER}", url)
