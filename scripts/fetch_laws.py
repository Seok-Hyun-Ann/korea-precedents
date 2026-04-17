from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Dict, List

from api_client import BASE_SEARCH_URL, BASE_SERVICE_URL, LawApiClient, build_request_url, parse_xml, save_text

ROOT = Path(__file__).resolve().parent.parent
RAW_DIR = ROOT / "data" / "raw" / "laws"
OUT_DIR = ROOT / "data" / "laws"


def text_of(node, tag: str) -> str:
    child = node.find(tag)
    return child.text.strip() if child is not None and child.text else ""


def fetch_law_list(client: LawApiClient, page: int = 1, display: int = 20) -> List[Dict[str, str]]:
    xml_text = client.search("law", page=page, display=display)
    timestamp = datetime.now(timezone.utc).isoformat()
    save_text(RAW_DIR / f"law-list-page-{page}.xml", xml_text)
    root = parse_xml(xml_text)
    rows = []
    for law in root.findall('.//law'):
        law_id = text_of(law, '법령ID')
        rows.append({
            'law_id': law_id,
            'law_mst': text_of(law, '법령일련번호'),
            'name_ko': text_of(law, '법령명한글') or text_of(law, '법령명'),
            'promulgation_date': text_of(law, '공포일자'),
            'effective_date': text_of(law, '시행일자'),
            'ministry': text_of(law, '소관부처명'),
            'law_type': text_of(law, '법령구분명'),
            'detail_link': text_of(law, '법령상세링크'),
            'source_system': '국가법령정보센터',
            'api_target': 'law',
            'request_type': 'list',
            'collected_at': timestamp,
            'source_url': build_request_url(BASE_SEARCH_URL, {'OC': client.oc, 'target': 'law', 'type': client.response_type, 'page': page, 'display': display}),
        })
    return rows


def fetch_law_detail(client: LawApiClient, law_id: str) -> Dict[str, object]:
    xml_text = client.service('eflaw', ID=law_id)
    timestamp = datetime.now(timezone.utc).isoformat()
    save_text(RAW_DIR / f"law-{law_id}.xml", xml_text)
    root = parse_xml(xml_text)
    basic = root.find('기본정보')
    articles = []
    for article in root.findall('./조문/조문단위'):
        articles.append({
            'article_key': article.attrib.get('조문키', ''),
            'article_no': text_of(article, '조문번호'),
            'article_title': text_of(article, '조문제목'),
            'article_text': text_of(article, '조문내용'),
            'article_effective_date': text_of(article, '조문시행일자'),
        })
    return {
        'law_id': law_id,
        'law_name': text_of(basic, '법령명_한글') if basic is not None else '',
        'promulgation_date': text_of(basic, '공포일자') if basic is not None else '',
        'effective_date': text_of(basic, '시행일자') if basic is not None else '',
        'law_type': text_of(basic, '법종구분') if basic is not None else '',
        'ministry': text_of(basic, '소관부처') if basic is not None else '',
        'source_system': '국가법령정보센터',
        'api_target': 'eflaw',
        'request_type': 'detail',
        'collected_at': timestamp,
        'source_url': build_request_url(BASE_SERVICE_URL, {'OC': client.oc, 'target': 'eflaw', 'type': client.response_type, 'ID': law_id}),
        'articles': articles,
    }


def main() -> None:
    client = LawApiClient()
    laws = fetch_law_list(client)
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    (OUT_DIR / 'law-list.json').write_text(json.dumps(laws, ensure_ascii=False, indent=2), encoding='utf-8')
    if laws:
        first = laws[0]['law_id']
        detail = fetch_law_detail(client, first)
        (OUT_DIR / f"{first}.json").write_text(json.dumps(detail, ensure_ascii=False, indent=2), encoding='utf-8')


if __name__ == '__main__':
    main()
