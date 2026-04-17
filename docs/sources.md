# Sources

## Primary source

### National Law Information Center Open API

Base pattern:
- `http://www.law.go.kr/DRF/lawSearch.do`
- `http://www.law.go.kr/DRF/lawService.do`

OC (access ID):
- Read from environment variable `LAW_GO_KR_OC` or `.env` file
- Apply for your own OC at https://open.law.go.kr/LSO/openApi/guideList.do
- Never commit OC values to version control

Planned endpoints:
- `target=law` for law list and law detail
- `target=prec` for precedent list and precedent detail
- `target=detc` for constitutional decisions later

## Data handling policy

- Keep provenance for every stored record
- Keep official URLs when available
- Prefer metadata-first ingestion
- Add new sources only after documenting terms and attribution
