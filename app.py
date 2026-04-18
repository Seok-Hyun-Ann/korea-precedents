"""한국 판례 검색기 — Streamlit 앱

사용법:
  pip install -r requirements.txt
  streamlit run app.py

첫 실행 시 HuggingFace에서 판례 DB(1.4GB)를 자동 다운로드합니다.
"""
from __future__ import annotations

import os
import re
import sqlite3
from pathlib import Path

import pandas as pd
import streamlit as st

DB_PATH = Path(__file__).resolve().parent / "data" / "precedents.db"

# HuggingFace에 업로드된 DB 위치.
# 환경변수로 오버라이드 가능 (예: 포크한 사용자가 자기 리포를 쓰고 싶을 때)
HF_REPO = os.environ.get("PRECEDENTS_HF_REPO", "SH98/korea-precedents")
HF_FILENAME = os.environ.get("PRECEDENTS_HF_FILE", "precedents.db")

# ── 페이지 설정 ──
st.set_page_config(
    page_title="한국 판례 검색기",
    page_icon="⚖️",
    layout="wide",
    initial_sidebar_state="expanded",
)


# ── DB 자동 다운로드 (첫 실행) ──
def ensure_db() -> None:
    """DB 파일이 없으면 HuggingFace에서 다운로드한다."""
    if DB_PATH.exists() and DB_PATH.stat().st_size > 1_000_000:
        return

    st.title("⚖️ 한국 판례 검색기")
    st.info(
        "최초 실행입니다. 판례 DB를 HuggingFace에서 다운로드합니다.\n\n"
        "- 크기: 약 1.4GB\n"
        "- 소요 시간: 네트워크 속도에 따라 1~5분\n"
        "- 다음 실행부터는 이 단계를 건너뜁니다."
    )

    try:
        from huggingface_hub import hf_hub_download
    except ImportError:
        st.error(
            "`huggingface_hub` 패키지가 필요합니다.\n\n"
            "터미널에서 실행하세요: `pip install huggingface_hub`"
        )
        st.stop()

    DB_PATH.parent.mkdir(parents=True, exist_ok=True)

    if not st.button("📥 DB 다운로드 시작", type="primary"):
        st.caption(f"다운로드 소스: `{HF_REPO}` / `{HF_FILENAME}`")
        st.caption(
            "다른 소스에서 받고 싶다면 환경변수 `PRECEDENTS_HF_REPO`, "
            "`PRECEDENTS_HF_FILE`을 설정하세요."
        )
        st.stop()

    with st.spinner("다운로드 중... (창을 닫지 마세요)"):
        try:
            hf_hub_download(
                repo_id=HF_REPO,
                repo_type="dataset",
                filename=HF_FILENAME,
                local_dir=str(DB_PATH.parent),
            )
        except Exception as e:
            st.error(f"다운로드 실패: {e}")
            st.caption(
                "네트워크를 확인하거나, [HuggingFace 페이지](https://huggingface.co/datasets/"
                f"{HF_REPO})에서 직접 받아 `data/precedents.db`로 저장하세요."
            )
            st.stop()

    # 파일명이 다르게 저장된 경우 처리
    downloaded = DB_PATH.parent / HF_FILENAME
    if downloaded.exists() and downloaded != DB_PATH:
        downloaded.rename(DB_PATH)

    if not DB_PATH.exists():
        st.error("다운로드된 파일을 찾을 수 없습니다. 다시 시도해주세요.")
        st.stop()

    st.success("✅ 다운로드 완료! 페이지를 새로고침합니다...")
    st.rerun()


ensure_db()


@st.cache_resource
def get_db():
    """SQLite 연결을 캐시하여 재사용한다."""
    conn = sqlite3.connect(str(DB_PATH), check_same_thread=False)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA cache_size=-32000")
    return conn


def query(sql: str, params: tuple = ()) -> list[dict]:
    conn = get_db()
    rows = conn.execute(sql, params).fetchall()
    return [dict(r) for r in rows]


def query_one(sql: str, params: tuple = ()) -> dict | None:
    conn = get_db()
    row = conn.execute(sql, params).fetchone()
    return dict(row) if row else None


def fmt_date(dd: str) -> str:
    """'20200312' → '2020.03.12'"""
    if dd and len(dd) == 8:
        return f"{dd[:4]}.{dd[4:6]}.{dd[6:]}"
    return dd or ""


# ── 유사 판례 추천 (BM25 기반) ──
STOP_WORDS = {
    "사건", "사안", "판결", "청구", "소송", "관련", "관한", "대한",
    "여부", "경우", "대법원", "원심", "판단", "법원", "기타",
}


def _extract_query_terms(case: dict, max_terms: int = 12) -> list[str]:
    """판례에서 FTS5 검색에 쓸 핵심 단어를 뽑는다 (한글 2+글자, 불용어 제거)."""
    text = " ".join([
        case.get("case_name", "") or "",
        case.get("decision_points", "") or "",
    ])
    words = re.findall(r"[가-힣]{2,}", text)
    seen: dict[str, int] = {}
    for w in words:
        if w in STOP_WORDS:
            continue
        seen[w] = seen.get(w, 0) + 1
    ranked = sorted(seen.items(), key=lambda x: -x[1])
    return [w for w, _ in ranked[:max_terms]]


@st.cache_data(ttl=600, show_spinner=False)
def find_similar_cases(pid: str, limit: int = 8) -> list[dict]:
    """현재 판례와 유사한 판례를 BM25로 추천한다.

    전략: case_name + decision_points에서 핵심 단어 추출 → FTS5 OR 쿼리 →
    같은 법령을 적용한 판례는 우선 가중. 각 추천 건에는 공통 법령·사건유형·
    판결결과·인용 관계 등 '추천 근거'를 함께 담아 반환한다.
    """
    case = query_one(
        "SELECT case_name, decision_points, case_number, case_type, result_class "
        "FROM cases WHERE precedent_id = ?",
        (pid,),
    )
    if not case:
        return []

    terms = _extract_query_terms(case)
    if not terms:
        return []

    fts_query = " OR ".join(f'"{t}"' for t in terms)

    # 같은 법령을 적용한 판례 목록 (AND 매칭 가중치용)
    laws = [
        r["law_name"] for r in query(
            "SELECT DISTINCT law_name FROM case_laws WHERE precedent_id = ?", (pid,)
        )
    ]
    src_laws_full = {
        (r["law_name"], r["article_label"]) for r in query(
            "SELECT law_name, article_label FROM case_laws WHERE precedent_id = ?", (pid,)
        )
    }
    src_case_number = case.get("case_number", "") or ""
    src_case_type = (case.get("case_type") or "").strip()
    src_result_class = (case.get("result_class") or "").strip()

    # 1차: 같은 법령 교집합 + BM25
    primary: list[dict] = []
    if laws:
        placeholders = ",".join(["?"] * len(laws))
        sql = f"""
            SELECT c.precedent_id, c.case_number, c.case_name, c.court_name,
                   c.decision_date, c.case_type, c.result_class, c.ruling_for,
                   c.easy_explanation,
                   bm25(cases_fts) as rank
            FROM cases_fts fts
            JOIN cases c ON c.rowid = fts.rowid
            WHERE cases_fts MATCH ?
              AND c.precedent_id != ?
              AND c.precedent_id IN (
                  SELECT precedent_id FROM case_laws WHERE law_name IN ({placeholders})
              )
            ORDER BY rank
            LIMIT ?
        """
        primary = query(sql, tuple([fts_query, pid] + laws + [limit]))

    # 2차: 1차가 부족하면 법령 제약 없이 BM25로 보충
    if len(primary) < limit:
        seen_ids = {r["precedent_id"] for r in primary}
        need = limit - len(primary)
        sql = """
            SELECT c.precedent_id, c.case_number, c.case_name, c.court_name,
                   c.decision_date, c.case_type, c.result_class, c.ruling_for,
                   c.easy_explanation,
                   bm25(cases_fts) as rank
            FROM cases_fts fts
            JOIN cases c ON c.rowid = fts.rowid
            WHERE cases_fts MATCH ?
              AND c.precedent_id != ?
            ORDER BY rank
            LIMIT ?
        """
        # 여유분 더 가져와서 중복 제거
        extra = query(sql, (fts_query, pid, need * 3))
        for r in extra:
            if r["precedent_id"] not in seen_ids:
                primary.append(r)
                seen_ids.add(r["precedent_id"])
                if len(primary) >= limit:
                    break

    # ── 추천 근거 계산 (공통 법령, 동일 사건유형/판결결과, 인용 관계) ──
    if primary:
        pids = [r["precedent_id"] for r in primary]
        placeholders = ",".join(["?"] * len(pids))
        cand_laws_map: dict[str, set[tuple[str, str]]] = {}
        for r in query(
            f"SELECT precedent_id, law_name, article_label FROM case_laws "
            f"WHERE precedent_id IN ({placeholders})",
            tuple(pids),
        ):
            cand_laws_map.setdefault(r["precedent_id"], set()).add(
                (r["law_name"], r["article_label"])
            )

        cand_case_numbers = [r.get("case_number", "") for r in primary if r.get("case_number")]
        cites_from_src: set[str] = set()
        cited_by_src: set[str] = set()
        if src_case_number and cand_case_numbers:
            cn_placeholders = ",".join(["?"] * len(cand_case_numbers))
            for r in query(
                f"SELECT cited_case_number FROM citations "
                f"WHERE citing_case_number = ? AND cited_case_number IN ({cn_placeholders})",
                tuple([src_case_number] + cand_case_numbers),
            ):
                cites_from_src.add(r["cited_case_number"])
            for r in query(
                f"SELECT citing_case_number FROM citations "
                f"WHERE cited_case_number = ? AND citing_case_number IN ({cn_placeholders})",
                tuple([src_case_number] + cand_case_numbers),
            ):
                cited_by_src.add(r["citing_case_number"])

        for r in primary:
            cand_laws = cand_laws_map.get(r["precedent_id"], set())
            common = src_laws_full & cand_laws
            shared = sorted(
                f"{ln} {al}".strip() for ln, al in common if ln
            )
            r["shared_laws"] = shared[:3]
            r["shared_laws_count"] = len(common)
            r["same_case_type"] = bool(
                src_case_type and (r.get("case_type") or "").strip() == src_case_type
            )
            r["same_result_class"] = bool(
                src_result_class and (r.get("result_class") or "").strip() == src_result_class
            )
            cand_cn = r.get("case_number", "")
            if cand_cn and cand_cn in cites_from_src:
                r["citation_relation"] = "cites"  # 원본이 이 판례를 인용
            elif cand_cn and cand_cn in cited_by_src:
                r["citation_relation"] = "cited_by"  # 이 판례가 원본을 인용
            else:
                r["citation_relation"] = None

    return primary


# ── 공통: 판례 상세 보기 ──
def show_case_detail(pid: str) -> None:
    """precedent_id로 판례 상세 정보를 표시한다."""
    case = query_one("SELECT * FROM cases WHERE precedent_id = ?", (pid,))
    if not case:
        st.warning("판례를 찾을 수 없습니다.")
        return

    st.subheader(f"{case['case_number']} — {case['case_name']}")

    # 기본 정보
    info_cols = st.columns(3)
    with info_cols[0]:
        st.markdown("**법원**")
        st.write(case.get("court_name", ""))
        st.markdown("**선고일**")
        st.write(fmt_date(case.get("decision_date", "")))
    with info_cols[1]:
        st.markdown("**사건유형**")
        st.write(case.get("case_type", ""))
        st.markdown("**판결결과**")
        rc = case.get("result_class", "")
        rf = case.get("ruling_for", "")
        st.write(f"{rc} ({rf})" if rf else rc)
    with info_cols[2]:
        st.markdown("**원고**")
        st.write(case.get("plaintiff", "") or "-")
        st.markdown("**피고**")
        st.write(case.get("defendant", "") or "-")

    # 쉬운 설명
    if case.get("easy_explanation"):
        st.info(case["easy_explanation"])

    # 관련 법령
    laws = query(
        "SELECT DISTINCT law_name, article_label FROM case_laws WHERE precedent_id = ?",
        (pid,),
    )
    if laws:
        st.markdown("**관련 법령**")
        law_tags = [f"`{l['law_name']} {l['article_label']}`" for l in laws]
        st.markdown(" ".join(law_tags))

    # 판시사항
    if case.get("decision_points"):
        with st.expander("판시사항", expanded=True):
            st.write(case["decision_points"])

    # 판결요지
    if case.get("decision_summary"):
        with st.expander("판결요지", expanded=True):
            st.write(case["decision_summary"])

    # 핵심 판단
    if case.get("key_reasoning"):
        with st.expander("핵심 판단 (이유 발췌)"):
            st.write(case["key_reasoning"])

    # 주문
    if case.get("ruling"):
        with st.expander("주문"):
            st.write(case["ruling"])

    # 인용 관계
    citing = query(
        "SELECT cited_case_number, cited_case_name FROM citations WHERE citing_case_number = ?",
        (case["case_number"],),
    )
    cited_by = query(
        "SELECT citing_case_number, citing_case_name FROM citations WHERE cited_case_number = ?",
        (case["case_number"],),
    )
    if citing or cited_by:
        st.markdown("**인용 관계**")
        c1, c2 = st.columns(2)
        with c1:
            st.markdown(f"이 판례가 인용한 판례 ({len(citing)}건)")
            for c in citing[:30]:
                st.caption(f"→ {c['cited_case_number']}  {c.get('cited_case_name','')}")
        with c2:
            st.markdown(f"이 판례를 인용한 판례 ({len(cited_by)}건)")
            for c in cited_by[:30]:
                st.caption(f"← {c['citing_case_number']}  {c.get('citing_case_name','')}")

    # 유사 판례 추천
    st.markdown("---")
    st.markdown("**🔎 유사 판례 추천**")
    st.caption(
        "사건명·판시사항의 핵심 단어 BM25 점수로 정렬하고, "
        "각 추천 건에 **추천 근거**(공통 법령·동일 사건유형/판결결과·인용 관계)를 함께 표시합니다."
    )
    similar = find_similar_cases(pid, limit=8)
    if not similar:
        st.caption("유사 판례를 찾을 수 없습니다.")
    else:
        for s in similar:
            with st.container(border=True):
                cols = st.columns([4, 1, 1])
                with cols[0]:
                    st.markdown(f"**{s['case_number']}** — {s['case_name']}")
                    st.caption(
                        f"{s.get('court_name', '')} · "
                        f"{fmt_date(s.get('decision_date', ''))} · "
                        f"{s.get('result_class', '')}"
                    )
                with cols[1]:
                    st.caption(f"관련도 {abs(s['rank']):.2f}")
                with cols[2]:
                    if st.button("보기", key=f"sim_{pid}_{s['precedent_id']}"):
                        st.session_state["detail_id"] = s["precedent_id"]
                        st.rerun()

                # 추천 근거 배지
                chips: list[str] = []
                cr = s.get("citation_relation")
                if cr == "cites":
                    chips.append("🔗 이 판례를 인용함")
                elif cr == "cited_by":
                    chips.append("🔗 이 판례가 원본을 인용")
                if s.get("shared_laws_count", 0) > 0:
                    preview = ", ".join(s.get("shared_laws") or [])
                    more = s["shared_laws_count"] - len(s.get("shared_laws") or [])
                    label = f"⚖️ 공통 법령 {s['shared_laws_count']}개"
                    if preview:
                        label += f" ({preview}"
                        if more > 0:
                            label += f" 외 {more}"
                        label += ")"
                    chips.append(label)
                if s.get("same_case_type"):
                    chips.append(f"📁 같은 사건유형: {s.get('case_type', '')}")
                if s.get("same_result_class"):
                    chips.append(f"🎯 같은 판결결과: {s.get('result_class', '')}")
                if chips:
                    st.caption(" · ".join(chips))
                else:
                    st.caption("📝 본문 키워드 유사도 기반 (공통 법령·인용 관계 없음)")

    # 전문
    if case.get("full_text"):
        with st.expander("전문 보기"):
            st.text(case["full_text"])


# ── FTS5 snippet: 매칭 위치 주변 본문에서 키워드에 <mark> 태그를 두른다 ──
# cases_fts 컬럼 순서(build_db.py): 0=case_number, 1=case_name, 2=court_name,
# 3=decision_points, 4=decision_summary, 5=key_reasoning, 6=easy_explanation
SNIPPET_COLUMNS: list[tuple[int, str]] = [
    (3, "판시사항"),
    (4, "판결요지"),
    (5, "핵심 판단"),
    (6, "쉬운 설명"),
    (1, "사건명"),
]
SNIPPET_SELECT = ",\n".join(
    f"snippet(cases_fts, {idx}, '<mark>', '</mark>', '…', 20) AS snip_{idx}"
    for idx, _ in SNIPPET_COLUMNS
)


def best_snippet(case: dict) -> tuple[str, str] | None:
    """FTS 결과 row에서 가장 먼저 매칭이 발견된 snippet과 그 컬럼 라벨을 반환한다."""
    for idx, label in SNIPPET_COLUMNS:
        snip = case.get(f"snip_{idx}")
        if snip and "<mark>" in snip:
            return label, snip
    return None


def highlight_like(text: str, query_str: str) -> str:
    """LIKE 모드에서 매칭 토큰을 <mark>로 감싼다. 단순 부분일치."""
    if not text or not query_str:
        return text or ""
    pattern = re.compile(re.escape(query_str), re.IGNORECASE)
    return pattern.sub(lambda m: f"<mark>{m.group(0)}</mark>", text)


# ── 공통: 판례 카드 (목록에서 사용) ──
def show_case_card(case: dict, key_prefix: str, query_str: str = "") -> None:
    """판례 1건을 카드 형태로 표시한다. 상세 보기 버튼 포함.

    case에 `snip_*` 필드가 있으면 FTS snippet을 하이라이트해 보여주고,
    없으면 `query_str`로 사건명/쉬운 설명에 하이라이트를 적용한다.
    """
    with st.container(border=True):
        cols = st.columns([4, 1])
        with cols[0]:
            case_name_disp = highlight_like(case.get("case_name", ""), query_str) if query_str else case.get("case_name", "")
            st.markdown(
                f"**{case['case_number']}** — {case_name_disp}",
                unsafe_allow_html=bool(query_str),
            )
            st.caption(
                f"{case.get('court_name', '')} · "
                f"{fmt_date(case.get('decision_date', ''))} · "
                f"{case.get('case_type', '')}"
            )
        with cols[1]:
            rc = case.get("result_class", "")
            icon = {"상고기각": "🔴", "파기환송": "🟢", "파기": "🟢",
                    "기각": "🔴", "취소": "🟡", "각하": "⚪",
                    "무죄": "🟢", "항소기각": "🔴"}.get(rc, "⚪")
            st.markdown(f"{icon} **{rc}**")

        snip = best_snippet(case)
        if snip:
            label, html = snip
            st.markdown(
                f"<span style='color:#888;font-size:0.85em'>[{label}]</span> {html}",
                unsafe_allow_html=True,
            )
        elif case.get("easy_explanation"):
            exp = highlight_like(case["easy_explanation"], query_str) if query_str else case["easy_explanation"]
            if query_str:
                st.markdown(f"<em>{exp}</em>", unsafe_allow_html=True)
            else:
                st.markdown(f"_{exp}_")

        btn_cols = st.columns([1, 1, 4])
        with btn_cols[0]:
            if st.button("상세 보기", key=f"{key_prefix}_{case['precedent_id']}"):
                st.session_state["detail_id"] = case["precedent_id"]
                st.session_state["detail_back"] = key_prefix
                st.rerun()
        with btn_cols[1]:
            cart = st.session_state.get("compare_cart", [])
            in_cart = case["precedent_id"] in cart
            label = "✓ 비교중" if in_cart else "비교 추가"
            if st.button(label, key=f"cmp_{key_prefix}_{case['precedent_id']}"):
                if in_cart:
                    cart.remove(case["precedent_id"])
                else:
                    if len(cart) >= 2:
                        cart.pop(0)  # 가장 오래된 것 제거 (2개까지만 유지)
                    cart.append(case["precedent_id"])
                st.session_state["compare_cart"] = cart
                st.rerun()


# ── 사이드바 ──
st.sidebar.title("⚖️ 한국 판례 검색기")
st.sidebar.caption("85,960건 대법원 판례 · 1,180개 법령 · 141,443건 인용관계")

page = st.sidebar.radio(
    "메뉴",
    ["🔍 판례 검색", "📚 법령별 조회", "⚖️ 판례 비교", "🔗 인용 관계", "📊 통계"],
    label_visibility="collapsed",
)

# ── 사이드바: 비교 카트 상태 ──
_cart = st.session_state.get("compare_cart", [])
if _cart:
    st.sidebar.divider()
    st.sidebar.caption(f"📋 비교 카트 ({len(_cart)}/2)")
    for _pid in _cart:
        _c = query_one("SELECT case_number, case_name FROM cases WHERE precedent_id = ?", (_pid,))
        if _c:
            st.sidebar.caption(f"· {_c['case_number']}")
    if st.sidebar.button("카트 비우기", key="clear_cart"):
        st.session_state["compare_cart"] = []
        st.rerun()

# ── 상세 보기 모드 ──
if "detail_id" in st.session_state:
    if st.button("← 목록으로 돌아가기"):
        del st.session_state["detail_id"]
        if "detail_back" in st.session_state:
            del st.session_state["detail_back"]
        st.rerun()

    show_case_detail(st.session_state["detail_id"])

# ════════════════════════════════════════
# 페이지 1: 판례 검색
# ════════════════════════════════════════
elif page == "🔍 판례 검색":
    st.header("판례 검색")

    col1, col2 = st.columns([3, 1])
    with col1:
        search_query = st.text_input(
            "검색어",
            placeholder="사건번호, 사건명, 키워드 (예: 소유권이전등기, 2019다12345, 부당해고)",
        )
    with col2:
        search_mode = st.selectbox("검색 방식", ["전문 검색", "사건번호", "사건명"])

    with st.expander("상세 필터", expanded=False):
        fcol1, fcol2 = st.columns(2)
        with fcol1:
            case_types = query("SELECT DISTINCT case_type FROM cases WHERE case_type != '' ORDER BY case_type")
            type_options = ["전체"] + [r["case_type"] for r in case_types]
            selected_type = st.selectbox("사건유형", type_options)
            result_classes = query("SELECT DISTINCT result_class FROM cases ORDER BY result_class")
            result_options = ["전체"] + [r["result_class"] for r in result_classes]
            selected_result = st.selectbox("판결결과", result_options)
        with fcol2:
            article_filter = st.text_input(
                "조문 단위 필터",
                placeholder="예: 민법 제750조 (법령명만 적어도 됨)",
                help="해당 법령/조문이 적용된 판례만. 공백으로 법령명과 조문 구분.",
            )
            min_citations = st.number_input(
                "최소 인용 횟수",
                min_value=0, max_value=1000, value=0, step=1,
                help="이 판례를 인용한 다른 판례의 수. 0이면 필터 없음.",
            )

        year_preset = st.radio(
            "기간",
            ["전체", "최근 5년", "최근 10년", "2020년대", "2010년대", "2000년대", "직접 입력"],
            horizontal=True, index=0,
        )

        current_year = 2026
        preset_map = {
            "전체": (1940, 2025),
            "최근 5년": (current_year - 5, current_year),
            "최근 10년": (current_year - 10, current_year),
            "2020년대": (2020, 2029),
            "2010년대": (2010, 2019),
            "2000년대": (2000, 2009),
        }
        if year_preset == "직접 입력":
            yc1, yc2 = st.columns(2)
            with yc1:
                year_from = st.number_input("시작 연도", min_value=1940, max_value=2025, value=1940)
            with yc2:
                year_to = st.number_input("종료 연도", min_value=1940, max_value=2025, value=2025)
        else:
            year_from, year_to = preset_map[year_preset]


    def _parse_article_filter(raw: str) -> tuple[str, str] | None:
        """'민법 제750조' → ('민법', '제750조'). 법령명만 주어지면 ('민법', '')."""
        raw = (raw or "").strip()
        if not raw:
            return None
        m = re.search(r"(제?\s*\d+\s*조(?:\s*의\s*\d+)?)", raw)
        if m:
            article = re.sub(r"\s+", "", m.group(1))
            if not article.startswith("제"):
                article = "제" + article
            law_name = raw[: m.start()].strip()
            return (law_name, article) if law_name else ("", article)
        return (raw, "")

    if search_query:
        params: list = []

        if search_mode == "전문 검색":
            fts_query = search_query.replace('"', '""')
            base_sql = f"""
                SELECT c.precedent_id, c.case_number, c.case_name, c.court_name,
                       c.decision_date, c.case_type, c.result_class, c.ruling_for,
                       c.easy_explanation,
                       {SNIPPET_SELECT}
                FROM cases_fts
                JOIN cases c ON c.rowid = cases_fts.rowid
                WHERE cases_fts MATCH ?
            """
            params.append(f'"{fts_query}"')
            tbl = "c"
        elif search_mode == "사건번호":
            base_sql = """
                SELECT precedent_id, case_number, case_name, court_name,
                       decision_date, case_type, result_class, ruling_for,
                       easy_explanation
                FROM cases WHERE case_number LIKE ?
            """
            params.append(f"%{search_query}%")
            tbl = ""
        else:
            base_sql = """
                SELECT precedent_id, case_number, case_name, court_name,
                       decision_date, case_type, result_class, ruling_for,
                       easy_explanation
                FROM cases WHERE case_name LIKE ?
            """
            params.append(f"%{search_query}%")
            tbl = ""

        prefix = f"{tbl}." if tbl else ""
        filters = []
        if selected_type != "전체":
            filters.append(f"{prefix}case_type = ?")
            params.append(selected_type)
        if selected_result != "전체":
            filters.append(f"{prefix}result_class = ?")
            params.append(selected_result)
        filters.append(f"{prefix}decision_date >= ?")
        params.append(f"{year_from}0101")
        filters.append(f"{prefix}decision_date <= ?")
        params.append(f"{year_to}1231")

        parsed_article = _parse_article_filter(article_filter)
        if parsed_article:
            law_name, article = parsed_article
            if law_name and article:
                filters.append(
                    f"EXISTS (SELECT 1 FROM case_laws cl WHERE cl.precedent_id = {prefix}precedent_id "
                    "AND cl.law_name = ? AND cl.article_label = ?)"
                )
                params.extend([law_name, article])
            elif law_name:
                filters.append(
                    f"EXISTS (SELECT 1 FROM case_laws cl WHERE cl.precedent_id = {prefix}precedent_id "
                    "AND cl.law_name = ?)"
                )
                params.append(law_name)
            elif article:
                filters.append(
                    f"EXISTS (SELECT 1 FROM case_laws cl WHERE cl.precedent_id = {prefix}precedent_id "
                    "AND cl.article_label = ?)"
                )
                params.append(article)

        if min_citations and min_citations > 0:
            filters.append(
                f"(SELECT COUNT(*) FROM citations WHERE cited_case_number = {prefix}case_number) >= ?"
            )
            params.append(int(min_citations))

        if filters:
            base_sql += " AND " + " AND ".join(filters)
        base_sql += f" ORDER BY {prefix}decision_date DESC LIMIT 100"

        results = query(base_sql, tuple(params))
        st.subheader(f"검색 결과: {len(results)}건" + (" (최대 100건)" if len(results) == 100 else ""))

        for r in results:
            show_case_card(r, "search", query_str=search_query)


# ════════════════════════════════════════
# 페이지 2: 법령별 조회
# ════════════════════════════════════════
elif page == "📚 법령별 조회":
    st.header("법령별 판례 조회")

    # ── 법령 선택 (복수 선택 가능) ──
    all_laws = query("""
        SELECT law_name, COUNT(DISTINCT precedent_id) as cnt
        FROM case_laws GROUP BY law_name ORDER BY cnt DESC
    """)
    law_options = [f"{l['law_name']} ({l['cnt']:,}건)" for l in all_laws]
    law_name_map = {f"{l['law_name']} ({l['cnt']:,}건)": l["law_name"] for l in all_laws}

    selected_law_labels = st.multiselect(
        "법령 선택 (복수 가능)",
        options=law_options,
        default=[],
        placeholder="법령명을 검색하세요 (예: 민법, 형법)",
    )
    selected_laws = [law_name_map[lbl] for lbl in selected_law_labels]

    # ── 필터 ──
    with st.expander("필터", expanded=True):
        fcol1, fcol2, fcol3, fcol4 = st.columns(4)
        with fcol1:
            result_classes = query("SELECT DISTINCT result_class FROM cases WHERE result_class != '' ORDER BY result_class")
            result_options = ["전체"] + [r["result_class"] for r in result_classes]
            selected_result = st.selectbox("판결결과", result_options, key="law_result")
        with fcol2:
            case_types = query("SELECT DISTINCT case_type FROM cases WHERE case_type != '' ORDER BY case_type")
            type_options = ["전체"] + [r["case_type"] for r in case_types]
            selected_type = st.selectbox("사건유형", type_options, key="law_type")
        with fcol3:
            year_from = st.number_input("시작 연도", min_value=1940, max_value=2025, value=1940, key="law_yf")
        with fcol4:
            year_to = st.number_input("종료 연도", min_value=1940, max_value=2025, value=2025, key="law_yt")

        sort_col1, sort_col2 = st.columns([1, 3])
        with sort_col1:
            sort_by = st.selectbox("정렬", ["최신순", "오래된순"], key="law_sort")

    # ── 검색 실행 ──
    if selected_laws:
        # 법령 조건: 선택한 법령이 모두 매칭된 판례 (AND 조건)
        if len(selected_laws) == 1:
            law_where = "cl.law_name = ?"
            law_params = [selected_laws[0]]
            having_clause = ""
        else:
            placeholders = ",".join(["?"] * len(selected_laws))
            law_where = f"cl.law_name IN ({placeholders})"
            law_params = list(selected_laws)
            # HAVING으로 모든 법령이 매칭된 판례만 필터
            having_clause = f"HAVING COUNT(DISTINCT cl.law_name) = {len(selected_laws)}"

        # 추가 필터
        extra_filters = []
        extra_params: list = []
        if selected_result != "전체":
            extra_filters.append("c.result_class = ?")
            extra_params.append(selected_result)
        if selected_type != "전체":
            extra_filters.append("c.case_type = ?")
            extra_params.append(selected_type)
        extra_filters.append("c.decision_date >= ?")
        extra_params.append(f"{year_from}0101")
        extra_filters.append("c.decision_date <= ?")
        extra_params.append(f"{year_to}1231")

        extra_where = (" AND " + " AND ".join(extra_filters)) if extra_filters else ""
        order = "DESC" if sort_by == "최신순" else "ASC"

        # 전체 건수 조회
        count_sql = f"""
            SELECT COUNT(*) as cnt FROM (
                SELECT c.precedent_id
                FROM case_laws cl
                JOIN cases c ON c.precedent_id = cl.precedent_id
                WHERE {law_where} {extra_where}
                GROUP BY c.precedent_id
                {having_clause}
            )
        """
        total_count = query_one(count_sql, tuple(law_params + extra_params))
        total_cnt = total_count["cnt"] if total_count else 0

        # 선택한 법령 태그 표시
        law_tags = " + ".join([f"`{l}`" for l in selected_laws])
        st.markdown(f"**{law_tags}** — {total_cnt:,}건")

        if total_cnt == 0:
            st.info("조건에 맞는 판례가 없습니다.")
        else:
            # 페이지네이션
            page_size = 20
            total_pages = max(1, (total_cnt + page_size - 1) // page_size)
            current_page = st.number_input(
                f"페이지 (총 {total_pages}페이지)",
                min_value=1, max_value=total_pages, value=1, step=1, key="law_page",
            )
            offset = (current_page - 1) * page_size

            data_sql = f"""
                SELECT c.precedent_id, c.case_number, c.case_name,
                       c.decision_date, c.result_class, c.court_name,
                       c.case_type, c.ruling_for, c.easy_explanation
                FROM case_laws cl
                JOIN cases c ON c.precedent_id = cl.precedent_id
                WHERE {law_where} {extra_where}
                GROUP BY c.precedent_id
                {having_clause}
                ORDER BY c.decision_date {order}
                LIMIT ? OFFSET ?
            """
            cases = query(data_sql, tuple(law_params + extra_params + [page_size, offset]))

            for case in cases:
                show_case_card(case, "law")
    else:
        st.info("왼쪽 법령 선택 창에서 법령을 검색하여 선택하세요.")


# ════════════════════════════════════════
# 페이지 3: 판례 비교
# ════════════════════════════════════════
elif page == "⚖️ 판례 비교":
    st.header("판례 비교")
    st.caption("두 판례를 나란히 놓고 항목별로 비교합니다. 다른 페이지의 '비교 추가' 버튼으로도 담을 수 있습니다.")

    cart = st.session_state.get("compare_cart", [])

    # 입력 영역 — 카트에 담긴 것을 기본값으로, 직접 입력도 허용
    st.markdown("#### 비교할 판례 선택")
    in_col1, in_col2 = st.columns(2)

    def _find_pid_by_cn(cn: str) -> str | None:
        if not cn:
            return None
        row = query_one(
            "SELECT precedent_id FROM cases WHERE case_number LIKE ? LIMIT 1",
            (f"%{cn.strip()}%",),
        )
        return row["precedent_id"] if row else None

    default_a = ""
    default_b = ""
    if len(cart) >= 1:
        r = query_one("SELECT case_number FROM cases WHERE precedent_id = ?", (cart[0],))
        default_a = r["case_number"] if r else ""
    if len(cart) >= 2:
        r = query_one("SELECT case_number FROM cases WHERE precedent_id = ?", (cart[1],))
        default_b = r["case_number"] if r else ""

    with in_col1:
        cn_a = st.text_input("판례 A 사건번호", value=default_a, placeholder="예: 95다28625", key="cmp_cn_a")
    with in_col2:
        cn_b = st.text_input("판례 B 사건번호", value=default_b, placeholder="예: 2019다12345", key="cmp_cn_b")

    pid_a = _find_pid_by_cn(cn_a)
    pid_b = _find_pid_by_cn(cn_b)

    if cn_a and not pid_a:
        st.error(f"판례 A를 찾을 수 없습니다: {cn_a}")
    if cn_b and not pid_b:
        st.error(f"판례 B를 찾을 수 없습니다: {cn_b}")

    if pid_a and pid_b:
        if pid_a == pid_b:
            st.warning("같은 판례입니다. 다른 판례를 선택하세요.")
        else:
            ca = query_one("SELECT * FROM cases WHERE precedent_id = ?", (pid_a,))
            cb = query_one("SELECT * FROM cases WHERE precedent_id = ?", (pid_b,))

            # 양쪽 법령 조회
            laws_a = query(
                "SELECT DISTINCT law_name, article_label FROM case_laws WHERE precedent_id = ?",
                (pid_a,),
            )
            laws_b = query(
                "SELECT DISTINCT law_name, article_label FROM case_laws WHERE precedent_id = ?",
                (pid_b,),
            )
            laws_a_set = {f"{l['law_name']} {l['article_label']}" for l in laws_a}
            laws_b_set = {f"{l['law_name']} {l['article_label']}" for l in laws_b}
            common_laws = laws_a_set & laws_b_set
            only_a_laws = laws_a_set - laws_b_set
            only_b_laws = laws_b_set - laws_a_set

            st.markdown("---")

            # 헤더
            h1, h2 = st.columns(2)
            with h1:
                st.markdown(f"### A. {ca['case_number']}")
                st.markdown(f"_{ca['case_name']}_")
            with h2:
                st.markdown(f"### B. {cb['case_number']}")
                st.markdown(f"_{cb['case_name']}_")

            # 판결결과 차이 하이라이트
            st.markdown("#### 🎯 판결결과")
            r1, r2 = st.columns(2)
            same_result = ca.get("result_class") == cb.get("result_class")
            with r1:
                rc = ca.get("result_class", "")
                rf = ca.get("ruling_for", "")
                txt = f"**{rc}**" + (f" ({rf})" if rf else "")
                if same_result:
                    st.success(txt)
                else:
                    st.warning(txt)
            with r2:
                rc = cb.get("result_class", "")
                rf = cb.get("ruling_for", "")
                txt = f"**{rc}**" + (f" ({rf})" if rf else "")
                if same_result:
                    st.success(txt)
                else:
                    st.warning(txt)
            if not same_result:
                st.caption("⚠️ 두 판례의 판결 결과가 다릅니다.")

            # 기본 메타
            st.markdown("#### 📋 기본 정보")
            meta_fields = [
                ("법원", "court_name"),
                ("선고일", "decision_date"),
                ("사건유형", "case_type"),
                ("결정유형", "decision_type"),
                ("원고", "plaintiff"),
                ("피고", "defendant"),
            ]
            for label, key in meta_fields:
                c1, c2 = st.columns(2)
                va = ca.get(key, "") or "-"
                vb = cb.get(key, "") or "-"
                if key == "decision_date":
                    va = fmt_date(va) if va != "-" else "-"
                    vb = fmt_date(vb) if vb != "-" else "-"
                with c1:
                    st.markdown(f"**{label}**: {va}")
                with c2:
                    st.markdown(f"**{label}**: {vb}")

            # 적용 법령 비교
            st.markdown("#### ⚖️ 적용 법령 비교")
            if common_laws:
                st.info(f"**공통 법령** ({len(common_laws)}개): " +
                        " · ".join(f"`{l}`" for l in sorted(common_laws)))
            l1, l2 = st.columns(2)
            with l1:
                st.markdown(f"**A에만 적용** ({len(only_a_laws)}개)")
                if only_a_laws:
                    for l in sorted(only_a_laws):
                        st.caption(f"· {l}")
                else:
                    st.caption("없음")
            with l2:
                st.markdown(f"**B에만 적용** ({len(only_b_laws)}개)")
                if only_b_laws:
                    for l in sorted(only_b_laws):
                        st.caption(f"· {l}")
                else:
                    st.caption("없음")

            # 긴 텍스트 필드 병렬 비교
            st.markdown("#### 📝 본문 비교")
            text_fields = [
                ("판시사항", "decision_points"),
                ("판결요지", "decision_summary"),
                ("주문", "ruling"),
                ("핵심 판단", "key_reasoning"),
            ]
            for label, key in text_fields:
                va = ca.get(key, "") or ""
                vb = cb.get(key, "") or ""
                if not va and not vb:
                    continue
                with st.expander(label, expanded=(key == "decision_points")):
                    tc1, tc2 = st.columns(2)
                    with tc1:
                        if va:
                            st.write(va)
                        else:
                            st.caption("(없음)")
                    with tc2:
                        if vb:
                            st.write(vb)
                        else:
                            st.caption("(없음)")

            # 상호 인용 여부
            cross_a_to_b = query_one(
                "SELECT 1 as x FROM citations WHERE citing_case_number = ? AND cited_case_number = ?",
                (ca["case_number"], cb["case_number"]),
            )
            cross_b_to_a = query_one(
                "SELECT 1 as x FROM citations WHERE citing_case_number = ? AND cited_case_number = ?",
                (cb["case_number"], ca["case_number"]),
            )
            if cross_a_to_b or cross_b_to_a:
                st.markdown("#### 🔗 인용 관계")
                if cross_a_to_b:
                    st.info(f"A({ca['case_number']})가 B({cb['case_number']})를 인용합니다.")
                if cross_b_to_a:
                    st.info(f"B({cb['case_number']})가 A({ca['case_number']})를 인용합니다.")
    else:
        if not cart:
            st.info("💡 사건번호를 직접 입력하거나, 다른 페이지의 '비교 추가' 버튼으로 판례를 담아보세요.")
        elif len(cart) == 1:
            st.info("한 개만 담겼습니다. 두 번째 판례를 추가하거나 B란에 사건번호를 입력하세요.")


# ════════════════════════════════════════
# 페이지 4: 인용 관계
# ════════════════════════════════════════
elif page == "🔗 인용 관계":
    st.header("판례 인용 관계 탐색")

    tab1, tab2 = st.tabs(["🏆 최다 인용 판례", "🔎 인용 검색"])

    with tab1:
        st.subheader("가장 많이 인용된 판례 TOP 50")
        top_cited = query("""
            SELECT cited_case_number, cited_case_name,
                   COUNT(*) as cite_count
            FROM citations
            WHERE cited_case_number != ''
            GROUP BY cited_case_number
            ORDER BY cite_count DESC
            LIMIT 50
        """)

        for i, r in enumerate(top_cited):
            cols = st.columns([0.5, 2, 4, 1])
            with cols[0]:
                st.write(f"**{i+1}**")
            with cols[1]:
                st.write(r["cited_case_number"])
            with cols[2]:
                st.caption(r.get("cited_case_name", ""))
            with cols[3]:
                st.write(f"**{r['cite_count']}회**")

    with tab2:
        case_input = st.text_input("사건번호 입력", placeholder="예: 95다28625")
        if case_input:
            citing = query("""
                SELECT cited_case_number, cited_case_name
                FROM citations
                WHERE citing_case_number LIKE ?
                ORDER BY cited_case_number
            """, (f"%{case_input}%",))

            cited_by = query("""
                SELECT citing_case_number, citing_case_name
                FROM citations
                WHERE cited_case_number LIKE ?
                ORDER BY citing_case_number
            """, (f"%{case_input}%",))

            c1, c2 = st.columns(2)
            with c1:
                st.subheader(f"인용한 판례 ({len(citing)}건)")
                for c in citing[:50]:
                    st.write(f"→ **{c['cited_case_number']}** {c.get('cited_case_name','')}")
            with c2:
                st.subheader(f"인용된 판례 ({len(cited_by)}건)")
                for c in cited_by[:50]:
                    st.write(f"← **{c['citing_case_number']}** {c.get('citing_case_name','')}")


# ════════════════════════════════════════
# 페이지 4: 통계
# ════════════════════════════════════════
elif page == "📊 통계":
    st.header("판례 데이터 통계")

    total = query_one("SELECT COUNT(*) as cnt FROM cases")
    total_laws = query_one("SELECT COUNT(DISTINCT law_name) as cnt FROM case_laws")
    total_cites = query_one("SELECT COUNT(*) as cnt FROM citations")

    m1, m2, m3 = st.columns(3)
    m1.metric("전체 판례", f"{total['cnt']:,}건")
    m2.metric("연결된 법령", f"{total_laws['cnt']:,}개")
    m3.metric("인용 관계", f"{total_cites['cnt']:,}건")

    st.divider()

    st.subheader("연도별 판례 수")
    yearly = query("""
        SELECT SUBSTR(decision_date, 1, 4) as year, COUNT(*) as cnt
        FROM cases
        WHERE length(decision_date) >= 4
          AND CAST(SUBSTR(decision_date, 1, 4) AS INTEGER) BETWEEN 1950 AND 2025
        GROUP BY year ORDER BY year
    """)
    if yearly:
        df_year = pd.DataFrame(yearly)
        df_year.columns = ["연도", "건수"]
        st.bar_chart(df_year.set_index("연도"))

    col1, col2 = st.columns(2)
    with col1:
        st.subheader("판결결과 분포")
        results = query("""
            SELECT result_class, COUNT(*) as cnt
            FROM cases WHERE result_class != ''
            GROUP BY result_class ORDER BY cnt DESC
        """)
        if results:
            df_result = pd.DataFrame(results)
            df_result.columns = ["판결결과", "건수"]
            st.dataframe(df_result, use_container_width=True, hide_index=True)

    with col2:
        st.subheader("사건유형 분포")
        types = query("""
            SELECT case_type, COUNT(*) as cnt
            FROM cases WHERE case_type != ''
            GROUP BY case_type ORDER BY cnt DESC
        """)
        if types:
            df_type = pd.DataFrame(types)
            df_type.columns = ["사건유형", "건수"]
            st.dataframe(df_type, use_container_width=True, hide_index=True)

    st.subheader("판례가 가장 많은 법령 TOP 30")
    top30 = query("""
        SELECT law_name, COUNT(DISTINCT precedent_id) as cnt
        FROM case_laws GROUP BY law_name
        ORDER BY cnt DESC LIMIT 30
    """)
    if top30:
        df_law = pd.DataFrame(top30)
        df_law.columns = ["법령", "판례 수"]
        st.bar_chart(df_law.set_index("법령"))

    st.subheader("법원별 판례 수 (상위 15)")
    courts = query("""
        SELECT court_name, COUNT(*) as cnt
        FROM cases WHERE court_name != ''
        GROUP BY court_name ORDER BY cnt DESC LIMIT 15
    """)
    if courts:
        df_court = pd.DataFrame(courts)
        df_court.columns = ["법원", "건수"]
        st.dataframe(df_court, use_container_width=True, hide_index=True)


# ── 푸터 ──
st.sidebar.divider()
st.sidebar.caption(
    "데이터 출처: 법제처 국가법령정보센터 (공공저작물)  \n"
    "법령 데이터 파싱 참조: legalize-kr/legalize-kr  \n"
    "판례 원문은 저작권법 제7조에 의해 자유이용 가능"
)
