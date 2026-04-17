from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Dict, List, Optional

ROOT = Path(__file__).resolve().parent.parent
CASES_DIR = ROOT / 'data' / 'cases'
LINKS_DIR = ROOT / 'data' / 'links'

LAW_NAME_PATTERN = re.compile(
    r'([가-힣A-Za-z0-9][가-힣A-Za-z0-9\s·ㆍ\-]*?(?:법|시행령|시행규칙|규칙|명령))'
)
ARTICLE_ONLY_PATTERN = re.compile(r'제(?P<article>\d+)조(?P<branch>의\d+)?')


def normalize_article_id(law_name: str, article_no: str, branch: str) -> str:
    slug = law_name.strip().replace(' ', '-').replace('ㆍ', '-').replace('·', '-')
    article = article_no.zfill(4)
    branch_suffix = branch.replace('의', '-') if branch else ''
    return f'{slug}-article-{article}{branch_suffix}'


def make_link(law_name: str, article_no: str, branch: str) -> Dict[str, str]:
    return {
        'law_name': law_name,
        'article_label': f'제{article_no}조{branch}',
        'article_id': normalize_article_id(law_name, article_no, branch),
        'source_confidence': 'api-reference-article',
    }


def extract_links(reference_articles: str) -> List[Dict[str, str]]:
    links: List[Dict[str, str]] = []
    current_law: Optional[str] = None
    segments = [segment.strip() for segment in re.split(r'[,/]', reference_articles or '') if segment.strip()]

    for segment in segments:
        law_names = [match.group(1).strip() for match in LAW_NAME_PATTERN.finditer(segment)]
        if law_names:
            current_law = law_names[-1]
        if not current_law:
            continue
        for match in ARTICLE_ONLY_PATTERN.finditer(segment):
            links.append(make_link(current_law, match.group('article'), match.group('branch') or ''))

    deduped: List[Dict[str, str]] = []
    seen = set()
    for link in links:
        key = (link['law_name'], link['article_label'])
        if key in seen:
            continue
        seen.add(key)
        deduped.append(link)
    return deduped


def main() -> None:
    LINKS_DIR.mkdir(parents=True, exist_ok=True)
    index = []
    for path in sorted(CASES_DIR.glob('*.json')):
        if path.name == 'case-list.json':
            continue
        case = json.loads(path.read_text(encoding='utf-8'))
        for link in extract_links(case.get('reference_articles', '')):
            index.append({
                'precedent_id': case.get('precedent_id'),
                'case_number': case.get('case_number'),
                'court_name': case.get('court_name'),
                'decision_date': case.get('decision_date'),
                **link,
            })
    (LINKS_DIR / 'article-to-case.json').write_text(json.dumps(index, ensure_ascii=False, indent=2), encoding='utf-8')


if __name__ == '__main__':
    main()
