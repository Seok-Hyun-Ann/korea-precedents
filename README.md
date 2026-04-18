# 한국 판례 검색기 (Korea Precedent Search)

대한민국 판례 **85,960건**을 검색·분석·탐색할 수 있는 **오프라인 검색 도구**입니다.

AI 없이 정규식과 패턴 매칭만으로 판례를 구조화하고, SQLite + FTS5 전문검색으로 빠르게 검색할 수 있습니다.

## 주요 기능

- **판례 검색** — 전문검색(FTS5), 사건번호, 사건명 + 법원/유형/결과/연도 필터
- **법령별 조회** — 1,180개 법령별 판례 목록, 복수 법령 AND 필터
- **판례 비교** — 두 판례를 나란히 놓고 판결결과·적용법령·본문을 병렬 비교
- **유사 판례 추천** — BM25 기반, 같은 법령 판례 우선 가중
- **인용 관계** — 139,028건 인용 엣지, 최다 인용 판례 탐색
- **통계** — 연도별/법원별/유형별/결과별 분포, 법령 TOP 30

## 빠른 시작 (3줄로 끝)

```bash
git clone https://github.com/Seok-Hyun-Ann/korea-precedents.git
cd korea-precedents
pip install -r requirements.txt
streamlit run app.py
```

> **첫 실행 시** 판례 DB(약 1.4GB)를 HuggingFace에서 자동으로 다운로드합니다.
> 국가법령정보센터 API 키, 회원가입, 별도 스크립트 실행 모두 필요 없습니다.

브라우저에서 `http://localhost:8501` 로 접속하면 끝입니다.

### `streamlit: command not found` / `'streamlit'은(는) 인식할 수 없는 명령입니다`가 뜨면

`pip install -r requirements.txt`는 Streamlit을 설치하지만, 환경에 따라 실행 파일이 PATH에 추가되지 않아 `streamlit` 명령을 직접 찾지 못하는 경우가 있습니다. 다음처럼 실행하면 PATH와 무관하게 동작합니다.

```bash
python -m streamlit run app.py
```

같은 이유로 설치도 `python -m pip install -r requirements.txt`로 하는 편이 여러 파이썬 버전이 섞인 환경에서 더 안전합니다. 그래도 안 되면 Python 3.10 이상이 설치되어 있는지(`python --version`), `pip`가 원하는 파이썬과 연결돼 있는지(`python -m pip --version`) 확인하세요.

## 시스템 요구사항

- Python 3.10 이상
- 디스크 여유 공간 약 2GB (DB 1.4GB + 인덱스)
- 메모리 1GB+ 권장

## 데이터 소스 커스터마이즈

기본값은 공식 HuggingFace 리포에서 받지만, 환경변수로 바꿀 수 있습니다.

**Linux / macOS (bash/zsh)**
```bash
export PRECEDENTS_HF_REPO=your-id/your-dataset
export PRECEDENTS_HF_FILE=precedents.db
streamlit run app.py
```

**Windows (PowerShell)**
```powershell
$env:PRECEDENTS_HF_REPO = "your-id/your-dataset"
$env:PRECEDENTS_HF_FILE = "precedents.db"
streamlit run app.py
```

**Windows (cmd)**
```cmd
set PRECEDENTS_HF_REPO=your-id/your-dataset
set PRECEDENTS_HF_FILE=precedents.db
streamlit run app.py
```

또는 OS 무관하게 `.env.example`을 `.env`로 복사한 뒤 값을 넣으세요.

수동으로 받으려면 [HuggingFace 페이지](https://huggingface.co/datasets/SH98/korea-precedents)에서 `precedents.db`를 받아 `data/` 폴더에 두세요.

## 고급: 데이터 재가공 / 업데이트

**앱 실행만 하실 거면 이 섹션은 건너뛰세요.** 이 섹션은 새 판례를 추가하거나 파이프라인을 수정하고 싶은 개발자용입니다.

### 1. 국가법령정보센터 API 키 신청

[open.law.go.kr](https://open.law.go.kr/LSO/openApi/guideList.do)에서 신청 후:
```bash
cp .env.example .env
# .env 파일의 LAW_GO_KR_OC= 뒤에 받은 ID 입력
```

### 2. 파이프라인 실행

```
1. 판례 수집       scripts/download_hf_precedents.py (HF) + fetch_cases_all.py (신규)
2. 판례 병합       scripts/merge_precedents.py
3. 법령 수집/파싱  scripts/fetch_laws.py, parse_laws.py
4. 법령-판례 매칭  scripts/match_law_case.py        (매칭률 92.5%)
5. 인용 관계 추출  scripts/extract_citations.py
6. 구조화 분석     scripts/structurize_cases.py
7. 법령별 분리     scripts/split_by_law.py
8. 검색 인덱스     scripts/build_search_index.py
9. SQLite DB 생성  scripts/build_db.py
```

## 기술 스택

| 구분 | 기술 |
|------|------|
| 데이터 수집 | 국가법령정보센터 API, HuggingFace datasets |
| 분석 | 정규식 기반 패턴 매칭 (AI 미사용) |
| 데이터베이스 | SQLite + FTS5 전문검색 |
| 유사도 | FTS5 내장 BM25 |
| 검색 앱 | Streamlit |
| 언어 | Python 3.10+ |

## 프로젝트 구조

```
.
├── app.py                    # Streamlit 앱
├── requirements.txt
├── .env.example              # 환경변수 템플릿
├── scripts/                  # 데이터 파이프라인
│   ├── api_client.py
│   ├── match_law_case.py
│   ├── extract_citations.py
│   ├── structurize_cases.py
│   ├── build_db.py
│   └── ...
├── docs/                     # 문서
└── data/                     # 자동 생성 (gitignore)
    └── precedents.db         # 첫 실행 시 자동 다운로드
```

## 데이터 출처 및 라이선스

### 소프트웨어
코드는 [MIT License](LICENSE)로 배포됩니다.

### 판례 데이터
- **출처**: 법제처 국가법령정보센터 (공공저작물)
- 판례 원문은 **저작권법 제7조**에 의해 보호 대상에서 제외됩니다
- 재배포 시 각 출처 시스템의 이용약관·공공누리 조건을 개별 확인하시기 바랍니다
- 사전 수집된 HuggingFace 데이터셋을 함께 사용한다면 해당 데이터셋 페이지의 라이선스를 따르세요

### 법령 데이터
- **출처**: 국가법령정보센터 Open API (법제처 국가법령정보 공동활용)
- 법령 파싱 참조: [lbox-open/legalize-kr](https://github.com/lbox-open/legalize-kr) (MIT License)

자세한 내용은 [docs/attribution.md](docs/attribution.md)를 참고하세요.

## 주의사항

- 이 도구는 **법률 연구 및 참고 목적**으로 제공됩니다
- 공식 법령 원문이나 법률 자문을 대체하지 않습니다
- 법적 효력은 정부 공식 간행물에 있습니다
- 데이터는 수집 시점 기준이므로 최신 판례를 반영하지 않을 수 있습니다

## 기여

버그 리포트, 기능 제안, PR 모두 환영합니다.

## 전체 삭제 방법

이 도구는 세 곳에 파일을 남깁니다. 아래 순서대로 지우면 완전히 제거됩니다.

### 1. 리포 폴더 삭제 (DB 1.4GB 포함)

`data/precedents.db`는 리포 폴더 안에 있으므로 폴더째 지우면 같이 삭제됩니다.

**Linux / macOS**
```bash
rm -rf korea-precedents
```

**Windows (PowerShell)**
```powershell
Remove-Item -Recurse -Force korea-precedents
```

**Windows (cmd)**
```cmd
rmdir /s /q korea-precedents
```

### 2. HuggingFace 캐시 삭제

`huggingface_hub`가 다운로드 과정에서 별도 캐시를 만들 수 있습니다. 다른 HF 도구를 쓰지 않는다면 캐시 전체를 지워도 안전합니다.

**Linux / macOS**
```bash
rm -rf ~/.cache/huggingface
```

**Windows (PowerShell)**
```powershell
Remove-Item -Recurse -Force "$env:USERPROFILE\.cache\huggingface"
```

이 프로젝트의 캐시만 골라 지우고 싶다면 `~/.cache/huggingface/hub/` 아래 `datasets--SH98--korea-precedents` 폴더만 삭제하세요.

### 3. pip 패키지 제거 (선택)

가상환경(`venv` 등)에 설치했다면 가상환경 폴더만 지우면 끝입니다. 시스템 전역에 설치했다면 다음 명령으로 제거할 수 있습니다.

```bash
python -m pip uninstall -y streamlit pandas huggingface_hub requests datasets
```

다른 프로젝트에서 같은 패키지를 쓰고 있다면 이 단계는 건너뛰세요.
