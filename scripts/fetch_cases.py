from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Dict, List

from api_client import BASE_SEARCH_URL, BASE_SERVICE_URL, LawApiClient, build_request_url, parse_xml, save_text

ROOT = Path(__file__).resolve().parent.parent
RAW_DIR = ROOT / "data" / "raw" / "cases"
OUT_DIR = ROOT / "data" / "cases"
DEFAULT_DATA_SOURCE = '대법원'


def text_of(node, tag: str) -> str:
    child = node.find(tag)
    return child.text.strip() if child is not None and child.text else ""


def fetch_case_list(client: LawApiClient, page: int = 1, display: int = 20, dat_src_name: str = DEFAULT_DATA_SOURCE) -> List[Dict[str, str]]:
    xml_text = client.search('prec', page=page, display=display, datSrcNm=dat_src_name)
    timestamp = datetime.now(timezone.utc).isoformat()
    save_text(RAW_DIR / f"case-list-page-{page}.xml", xml_text)
    root = parse_xml(xml_text)
    rows = []
    for case in root.findall('.//prec'):
        precedent_id = text_of(case, '판례일련번호')
        rows.append({
            'precedent_id': precedent_id,
            'case_name': text_of(case, '사건명'),
            'case_number': text_of(case, '사건번호'),
            'court_name': text_of(case, '법원명'),
            'decision_date': text_of(case, '선고일자'),
            'case_type': text_of(case, '사건종류명'),
            'decision_type': text_of(case, '판결유형'),
            'data_source_name': text_of(case, '데이터출처명'),
            'detail_link': text_of(case, '판례상세링크'),
            'source_system': '국가법령정보센터',
            'api_target': 'prec',
            'request_type': 'list',
            'collected_at': timestamp,
            'source_url': build_request_url(BASE_SEARCH_URL, {'OC': client.oc, 'target': 'prec', 'type': client.response_type, 'page': page, 'display': display, 'datSrcNm': dat_src_name}),
        })
    return rows


def fetch_case_detail(client: LawApiClient, precedent_id: str) -> Dict[str, object]:
    xml_text = client.service('prec', ID=precedent_id)
    timestamp = datetime.now(timezone.utc).isoformat()
    save_text(RAW_DIR / f"case-{precedent_id}.xml", xml_text)
    root = parse_xml(xml_text)
    return {
        'precedent_id': precedent_id,
        'case_name': text_of(root, '사건명'),
        'case_number': text_of(root, '사건번호'),
        'court_name': text_of(root, '법원명'),
        'decision_date': text_of(root, '선고일자'),
        'decision_summary': text_of(root, '판결요지'),
        'decision_points': text_of(root, '판시사항'),
        'reference_articles': text_of(root, '참조조문'),
        'reference_cases': text_of(root, '참조판례'),
        'full_text': text_of(root, '판례내용'),
        'source_system': '국가법령정보센터',
        'api_target': 'prec',
        'request_type': 'detail',
        'collected_at': timestamp,
        'source_url': build_request_url(BASE_SERVICE_URL, {'OC': client.oc, 'target': 'prec', 'type': client.response_type, 'ID': precedent_id}),
    }


def main() -> None:
    client = LawApiClient()
    cases = fetch_case_list(client)
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    (OUT_DIR / 'case-list.json').write_text(json.dumps(cases, ensure_ascii=False, indent=2), encoding='utf-8')
    if cases:
        first = cases[0]['precedent_id']
        detail = fetch_case_detail(client, first)
        (OUT_DIR / f"{first}.json").write_text(json.dumps(detail, ensure_ascii=False, indent=2), encoding='utf-8')


if __name__ == '__main__':
    main()
