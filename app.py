import re
import requests
import streamlit as st
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry

# =========================================================
# Page setup
# =========================================================
st.set_page_config(page_title="🎬 나와 어울리는 영화는?", page_icon="🎬", layout="wide")

# =========================================================
# Lightweight UI theme (CSS)
# =========================================================
st.markdown(
    """
    <style>
      /* 전체 배경/폰트 느낌 */
      .block-container {padding-top: 1.2rem; padding-bottom: 2rem;}
      /* 카드 느낌 */
      .movie-card {
        background: rgba(255,255,255,0.06);
        border: 1px solid rgba(255,255,255,0.10);
        padding: 0.9rem;
        border-radius: 16px;
      }
      .badge {
        display:inline-block;
        padding: 0.2rem 0.55rem;
        border-radius: 999px;
        border: 1px solid rgba(255,255,255,0.15);
        font-size: 0.85rem;
        margin-right: 0.35rem;
      }
      .subtle {opacity: 0.85;}
      /* 사이드바 꾸미기 */
      section[data-testid="stSidebar"] > div {
        padding-top: 1rem;
      }
      .sidebar-box {
        background: rgba(255,255,255,0.06);
        border: 1px solid rgba(255,255,255,0.10);
        padding: 0.85rem;
        border-radius: 16px;
        margin-bottom: 0.8rem;
      }
      /* TOP3 시상대 */
      .podium {
        background: rgba(255,255,255,0.06);
        border: 1px solid rgba(255,255,255,0.10);
        padding: 0.85rem;
        border-radius: 16px;
      }
    </style>
    """,
    unsafe_allow_html=True,
)

# =========================================================
# Constants
# =========================================================
GENRES = {
    "액션": 28,
    "코미디": 35,
    "드라마": 18,
    "SF": 878,
    "로맨스": 10749,
    "판타지": 14,
}
TIE_BREAK = ["드라마", "로맨스", "액션", "SF", "판타지", "코미디"]

# 관람자 기분 상태(추가) → 장르 가중치에 반영
VIEWER_MOOD = {
    "힐링되는 영화가 보고 싶어": ["드라마", "로맨스"],
    "빵빵 웃고 싶어": ["코미디"],
    "손에 땀 쥐는 긴장감!": ["액션", "SF"],
    "상상력/세계관에 빠지고 싶어": ["SF", "판타지"],
    "설레고 감정선 진한 영화": ["로맨스", "드라마"],
}

# 연령대(추가) → 최소 평가 수/정렬에 아주 약하게 반영(추천 안정화)
AGE_PRESET = {
    "10대": {"min_vote_count": 50},
    "20대": {"min_vote_count": 120},
    "30대": {"min_vote_count": 150},
    "40대+": {"min_vote_count": 180},
}

# =========================================================
# HTTP Session with Retry
# =========================================================
@st.cache_resource
def get_session() -> requests.Session:
    s = requests.Session()
    retry = Retry(
        total=3,
        backoff_factor=0.6,
        status_forcelist=[429, 500, 502, 503, 504],
        allowed_methods=["GET"],
        raise_on_status=False,
    )
    adapter = HTTPAdapter(max_retries=retry)
    s.mount("https://", adapter)
    s.mount("http://", adapter)
    return s


def tmdb_get(url: str, api_key: str | None, v4_token: str | None, params: dict | None = None) -> dict:
    session = get_session()
    params = params or {}

    headers = {"Accept": "application/json"}
    if v4_token and v4_token.strip():
        headers["Authorization"] = f"Bearer {v4_token.strip()}"
    elif api_key and api_key.strip():
        params["api_key"] = api_key.strip()

    r = session.get(url, params=params, headers=headers, timeout=15)

    try:
        data = r.json()
    except Exception:
        data = {}

    if r.status_code >= 400:
        if r.status_code == 401:
            raise RuntimeError("인증 실패(401). API Key 또는 Read Token이 올바른지 확인해 주세요.")
        if r.status_code == 429:
            raise RuntimeError("요청이 너무 많아요(429). 잠시 후 다시 시도해 주세요.")
        msg = data.get("status_message") or f"TMDB 요청 실패 (HTTP {r.status_code})"
        raise RuntimeError(msg)

    return data


# =========================================================
# TMDB APIs
# =========================================================
@st.cache_data(show_spinner=False, ttl=60 * 60)
def fetch_configuration(api_key: str | None, v4_token: str | None) -> dict:
    return tmdb_get("https://api.themoviedb.org/3/configuration", api_key, v4_token, params={})


def build_image_url(cfg: dict, file_path: str | None, size_preference: str = "w500") -> str | None:
    if not file_path:
        return None
    images = (cfg or {}).get("images") or {}
    base_url = images.get("secure_base_url") or images.get("base_url")
    if not base_url:
        return f"https://image.tmdb.org/t/p/{size_preference}{file_path}"
    sizes = images.get("poster_sizes") or []
    size = size_preference if size_preference in sizes else (sizes[-1] if sizes else size_preference)
    return f"{base_url}{size}{file_path}"


@st.cache_data(show_spinner=False, ttl=60 * 10)
def discover_movies(
    api_key: str | None,
    v4_token: str | None,
    with_genres: str,
    language: str,
    sort_by: str,
    page: int,
    min_vote_count: int,
    vote_avg_min: float,
    vote_avg_max: float,
    country_mode: str,
):
    url = "https://api.themoviedb.org/3/discover/movie"
    params = {
        "with_genres": with_genres,
        "language": language,
        "sort_by": sort_by,
        "page": page,
        "include_adult": False,
        "vote_count.gte": int(min_vote_count),
        "vote_average.gte": float(vote_avg_min),
        "vote_average.lte": float(vote_avg_max),
    }

    # 국가 필터(근사)
    if country_mode == "한국영화":
        params["with_original_language"] = "ko"
        params["region"] = "KR"
        params["primary_release_country"] = "KR"
    elif country_mode == "외국영화":
        params["without_original_language"] = "ko"

    data = tmdb_get(url, api_key, v4_token, params=params)
    return data.get("results") or []


@st.cache_data(show_spinner=False, ttl=60 * 30)
def movie_details(api_key: str | None, v4_token: str | None, movie_id: int, language: str) -> dict:
    url = f"https://api.themoviedb.org/3/movie/{movie_id}"
    params = {
        "language": language,
        "append_to_response": "videos,images,credits",
        "include_image_language": "en,null,ko",
    }
    return tmdb_get(url, api_key, v4_token, params=params)


def pick_trailer_url(details: dict) -> str | None:
    videos = (details.get("videos") or {}).get("results") or []
    for v in videos:
        if (v.get("site") == "YouTube") and (v.get("type") == "Trailer") and v.get("key"):
            return f"https://www.youtube.com/watch?v={v['key']}"
    for v in videos:
        if (v.get("site") == "YouTube") and v.get("key"):
            return f"https://www.youtube.com/watch?v={v['key']}"
    return None


# =========================================================
# Scoring
# - 모든 질문을 "영화 속 주인공 상황 가정형"으로 변경
# - 3번 질문은 사용자가 지정한 여행 역할 질문으로 교체
# =========================================================
def decide_genres_and_reasons(answers: dict, viewer_mood: str, age_band: str):
    scores = {g: 0 for g in GENRES.keys()}
    reasons_pool = {g: [] for g in GENRES.keys()}

    def add(g, pts, reason):
        scores[g] += pts
        reasons_pool[g].append(reason)

    # Q1: 실제 영화 상황 가정
    # "정체불명의 초대장을 받았다! 당신의 첫 행동은?"
    if answers["q1"] == "수상하지만 일단 따라가 본다":
        add("액션", 2, "사건의 중심으로 직접 뛰어드는 전개를 선택했어요.")
        add("어드벤처", 0, "")  # placeholder (미사용)
    elif answers["q1"] == "단서를 모으며 조심히 접근한다":
        add("SF", 2, "설정과 단서를 따라가는 몰입형 전개가 잘 맞아요.")
        add("드라마", 1, "인물의 내적 판단/긴장도 함께 즐길 수 있어요.")
    elif answers["q1"] == "누군가와 함께 움직이며 관계를 확인한다":
        add("로맨스", 2, "관계 중심의 설렘/감정선이 중요한 편이에요.")
        add("드라마", 1, "인물 간 감정 변화에 몰입하는 타입이에요.")
    elif answers["q1"] == "농담 한마디로 분위기부터 푼다":
        add("코미디", 2, "웃음과 텐션이 있는 장면을 좋아해요.")

    # Q2: 실제 영화 상황 가정
    # "친구가 갑자기 이별을 당했다. 당신의 행동은?"
    if answers["q2"] == "조용히 옆에 있어준다":
        add("드라마", 2, "잔잔하지만 깊은 감정선을 선호해요.")
        add("로맨스", 1, "관계의 온도/서사를 중요하게 여겨요.")
    elif answers["q2"] == "맛있는 걸 사주며 웃기려 한다":
        add("코미디", 2, "기분 전환 포인트가 중요한 편이에요.")
        add("로맨스", 1, "따뜻한 관계 중심 이야기에도 끌려요.")
    elif answers["q2"] == "바로 밖으로 끌고 나가 땀 빼게 한다":
        add("액션", 2, "에너지 넘치는 전개를 선호할 가능성이 커요.")
    elif answers["q2"] == "현실적인 조언 + 해결책을 같이 찾는다":
        add("SF", 1, "문제 해결/전개 구조가 명확한 이야기를 좋아할 수 있어요.")
        add("드라마", 2, "현실 공감/해결 서사에 끌려요.")

    # Q3: 사용자 요구대로 교체
    # 종강 후 여행! 친구와 떠날 때 내 역할?
    if answers["q3"] == "계획형":
        add("드라마", 2, "흐름이 탄탄한 서사에 안정감을 느껴요.")
        add("SF", 1, "논리적 전개/설정도 즐길 수 있어요.")
    elif answers["q3"] == "즉흥적이지만 계획에 수긍":
        add("로맨스", 2, "우연/설렘/케미가 있는 전개에 강해요.")
        add("코미디", 1, "즉흥에서 생기는 웃긴 상황도 좋아해요.")
    elif answers["q3"] == "액티비티는 무조건!":
        add("액션", 2, "박진감 넘치는 액티비티/사건 전개가 찰떡이에요.")
        add("판타지", 1, "스케일 큰 모험도 좋아할 수 있어요.")
    elif answers["q3"] == "여행은 힐링이지":
        add("로맨스", 2, "따뜻하고 편안한 분위기의 영화가 잘 맞아요.")
        add("드라마", 1, "잔잔한 여운도 좋아할 수 있어요.")

    # Q4: 실제 영화 상황 가정
    # "새로운 세계로 포탈이 열렸다. 당신의 선택은?"
    if answers["q4"] == "망설임 없이 들어간다":
        add("액션", 2, "모험/돌파형 전개에 끌려요.")
        add("판타지", 1, "이세계/마법 같은 설정에 매력을 느껴요.")
    elif answers["q4"] == "규칙을 파악하고 안전장치부터":
        add("SF", 2, "규칙/설정 기반 세계관에 몰입하는 편이에요.")
        add("드라마", 1, "신중한 캐릭터 중심 서사도 좋아할 수 있어요.")
    elif answers["q4"] == "같이 들어갈 동료부터 찾는다":
        add("로맨스", 2, "관계 중심의 케미와 팀워크를 좋아해요.")
        add("드라마", 1, "감정선이 있는 전개와도 잘 맞아요.")
    elif answers["q4"] == "일단 상황을 웃기게 정리한다":
        add("코미디", 2, "유머로 풀어가는 전개가 취향이에요.")

    # Q5: 실제 영화 상황 가정
    # "마지막 결말을 바꿀 수 있다면?"
    if answers["q5"] == "모두가 행복한 결말":
        add("로맨스", 2, "따뜻한 감정의 완결감을 좋아해요.")
        add("드라마", 1, "여운 있는 해피엔딩에 끌려요.")
    elif answers["q5"] == "짜릿한 반전 결말":
        add("SF", 2, "설정/반전/아이디어의 쾌감을 좋아해요.")
        add("판타지", 1, "예상 밖의 전개도 즐길 수 있어요.")
    elif answers["q5"] == "악당을 통쾌하게 제압":
        add("액션", 2, "카타르시스 있는 결말이 찰떡이에요.")
    elif answers["q5"] == "웃기게 마무리(쿠키영상까지!)":
        add("코미디", 2, "끝까지 즐겁게 웃는 영화가 좋아요.")

    # 관람자 기분 상태 가중치(요구사항)
    for g in VIEWER_MOOD.get(viewer_mood, []):
        if g in scores:
            scores[g] += 1
            reasons_pool[g].append(f"지금 기분(“{viewer_mood}”)에 {g} 장르가 잘 어울려요.")

    # 연령대는 추천 안정화를 위해 아주 약하게만 반영(점수에는 영향 X)
    # (min_vote_count 등 필터에서 반영)

    # top1/top2
    sorted_scores = sorted(scores.items(), key=lambda x: x[1], reverse=True)
    top_score = sorted_scores[0][1]
    top_candidates = [g for g, s in sorted_scores if s == top_score]
    top1 = next((g for g in TIE_BREAK if g in top_candidates), sorted_scores[0][0])

    top2 = None
    if len(sorted_scores) > 1:
        second_score = sorted_scores[1][1]
        if (top_score - second_score) <= 1 and second_score > 0:
            second_candidates = [g for g, s in sorted_scores if s == second_score and g != top1]
            if second_candidates:
                top2 = next((g for g in TIE_BREAK if g in second_candidates), second_candidates[0])

    def uniq_take(lst, k=3):
        out = []
        for x in lst:
            if x and x not in out:
                out.append(x)
        return out[:k] if out else ["당신의 선택이 이 장르 분위기와 잘 맞아요."]

    return scores, top1, top2, uniq_take(reasons_pool[top1], 3), (uniq_take(reasons_pool[top2], 2) if top2 else [])


# =========================================================
# Utilities
# =========================================================
def normalize_title(t: str) -> str:
    t = (t or "").strip().lower()
    t = re.sub(r"\s+", " ", t)
    t = re.sub(r"[^\w\s가-힣]", "", t)
    return t


def movie_reason(genre_names: list[str], vote_avg: float, has_trailer: bool, viewer_mood: str) -> str:
    bits = [
        f"당신의 취향 장르(**{', '.join(genre_names)}**) 기반으로 골랐어요.",
        f"지금 기분(“{viewer_mood}”)에 맞는 분위기의 인기작이에요.",
    ]
    if vote_avg >= 7.5:
        bits.append("평점이 높아서 만족도가 좋은 편이에요.")
    if has_trailer:
        bits.append("트레일러로 분위기를 먼저 확인할 수 있어요.")
    return " ".join(bits)


# =========================================================
# Header (대표 캐릭터)
# =========================================================
left_h, right_h = st.columns([2.2, 1.0], vertical_alignment="center")
with left_h:
    st.markdown("## 🎬 나와 어울리는 영화는?")
    st.markdown('<span class="subtle">영화 속 주인공이 된 것처럼 선택하면, 지금의 취향에 딱 맞는 영화를 추천해줄게요 🍿</span>', unsafe_allow_html=True)
with right_h:
    # 대표 캐릭터(이모지 기반) - 외부 이미지 없이도 예쁘게
    st.markdown(
        """
        <div class="movie-card" style="text-align:center;">
          <div style="font-size:52px;">🧑‍🎤🎥</div>
          <div style="font-weight:700;">무비 가이드, ‘무비냥’</div>
          <div class="subtle" style="font-size:0.9rem;">당신 취향만 콕 집어 추천!</div>
        </div>
        """,
        unsafe_allow_html=True,
    )

st.divider()

# =========================================================
# Sidebar (꾸미기 + 옵션 추가)
# =========================================================
with st.sidebar:
    st.markdown(
        """
        <div class="sidebar-box">
          <div style="font-size:1.05rem; font-weight:800;">🎟️ 관람자 설정</div>
          <div class="subtle" style="font-size:0.9rem;">지금 상태에 맞춰 추천을 더 정확히!</div>
        </div>
        """,
        unsafe_allow_html=True,
    )

    age_band = st.selectbox("현재 관람자 연령대", list(AGE_PRESET.keys()), index=1)
    viewer_mood = st.selectbox("지금 어떤 영화를 보고 싶어?", list(VIEWER_MOOD.keys()), index=0)

    st.markdown(
        """
        <div class="sidebar-box">
          <div style="font-size:1.05rem; font-weight:800;">🔑 TMDB 인증</div>
          <div class="subtle" style="font-size:0.9rem;">API Key(v3) 또는 Read Token(v4)</div>
        </div>
        """,
        unsafe_allow_html=True,
    )
    api_key = st.text_input("API Key (v3)", type="password", placeholder="선택")
    v4_token = st.text_input("Read Access Token (v4)", type="password", placeholder="선택")

    st.markdown(
        """
        <div class="sidebar-box">
          <div style="font-size:1.05rem; font-weight:800;">🎛️ 추천 필터</div>
          <div class="subtle" style="font-size:0.9rem;">원하는 조건으로 결과를 조정해보세요</div>
        </div>
        """,
        unsafe_allow_html=True,
    )

    language = st.selectbox("언어(language)", ["ko-KR", "en-US"], index=0)
    sort_by = st.selectbox("정렬 기준", ["popularity.desc", "vote_average.desc"], index=0)

    vote_min, vote_max = st.slider("최저/최고 평점", 0.0, 10.0, (6.0, 9.5), step=0.1)
    country_mode = st.radio("[한국영화/외국영화/모두]", ["모두", "한국영화", "외국영화"], index=0)

    # 연령대에 따라 기본 최소 평가수 프리셋 적용
    base_min_votes = AGE_PRESET[age_band]["min_vote_count"]
    min_vote_count = st.slider("최소 평가 수(신뢰도)", 0, 3000, base_min_votes, step=50)

# =========================================================
# Questions (모두 상황 가정형 / Q3 교체 완료)
# =========================================================
st.markdown("### 🎭 심리테스트: 내가 영화 속 주인공이라면?")
st.caption("아래 상황은 ‘실제 영화 속 한 장면’처럼 상상하고 골라주세요.")

q1 = st.radio(
    "1) 어느 날, 정체불명의 초대장이 도착했다. 당신의 첫 행동은?",
    ["수상하지만 일단 따라가 본다", "단서를 모으며 조심히 접근한다", "누군가와 함께 움직이며 관계를 확인한다", "농담 한마디로 분위기부터 푼다"],
    key="q1",
)

q2 = st.radio(
    "2) 친구가 갑자기 이별을 당했다. 당신은 어떻게 할까?",
    ["조용히 옆에 있어준다", "맛있는 걸 사주며 웃기려 한다", "바로 밖으로 끌고 나가 땀 빼게 한다", "현실적인 조언 + 해결책을 같이 찾는다"],
    key="q2",
)

q3 = st.radio(
    "3) 종강 후 떠나는 여행! 친구와 여행을 떠날 때 당신의 역할은?",
    ["계획형", "즉흥적이지만 계획에 수긍", "액티비티는 무조건!", "여행은 힐링이지"],
    key="q3",
)

q4 = st.radio(
    "4) 눈앞에 새로운 세계로 향하는 포탈이 열렸다. 당신의 선택은?",
    ["망설임 없이 들어간다", "규칙을 파악하고 안전장치부터", "같이 들어갈 동료부터 찾는다", "일단 상황을 웃기게 정리한다"],
    key="q4",
)

q5 = st.radio(
    "5) 결말을 바꿀 수 있다면 어떤 결말을 선택할까?",
    ["모두가 행복한 결말", "짜릿한 반전 결말", "악당을 통쾌하게 제압", "웃기게 마무리(쿠키영상까지!)"],
    key="q5",
)

st.divider()

# =========================================================
# Result button
# =========================================================
if st.button("결과 보기", type="primary"):
    if not (v4_token.strip() if v4_token else "") and not (api_key.strip() if api_key else ""):
        st.error("사이드바에 API Key(v3) 또는 Read Access Token(v4) 중 하나를 입력해 주세요.")
        st.stop()

    answers = {"q1": q1, "q2": q2, "q3": q3, "q4": q4, "q5": q5}

    with st.spinner("분석 중..."):
        try:
            cfg = fetch_configuration(api_key, v4_token)

            scores, top1, top2, reasons1, reasons2 = decide_genres_and_reasons(
                answers=answers,
                viewer_mood=viewer_mood,
                age_band=age_band,
            )
            chosen = [top1] + ([top2] if top2 else [])
            with_genres = ",".join(str(GENRES[g]) for g in chosen)

            # 후보를 넉넉히 받아서 중복 제거 후 9개(3열) 구성
            candidates = discover_movies(
                api_key=api_key,
                v4_token=v4_token,
                with_genres=with_genres,
                language=language,
                sort_by=sort_by,
                page=1,
                min_vote_count=min_vote_count,
                vote_avg_min=vote_min,
                vote_avg_max=vote_max,
                country_mode=country_mode,
            )

            # 부족하면 top1 단독 fallback
            if len(candidates) < 10 and top2:
                more = discover_movies(
                    api_key=api_key,
                    v4_token=v4_token,
                    with_genres=str(GENRES[top1]),
                    language=language,
                    sort_by=sort_by,
                    page=1,
                    min_vote_count=max(0, min_vote_count // 2),
                    vote_avg_min=vote_min,
                    vote_avg_max=vote_max,
                    country_mode=country_mode,
                )
                candidates += more

            # 제목 기준 dedup
            deduped = []
            seen = set()
            for m in candidates:
                t = normalize_title(m.get("title") or "")
                if not t or t in seen:
                    continue
                seen.add(t)
                deduped.append(m)
                if len(deduped) >= 12:
                    break

            top_list = deduped[:9]

            enriched = []
            for m in top_list:
                mid = m.get("id")
                if not mid:
                    continue
                d = movie_details(api_key, v4_token, int(mid), language)
                enriched.append((m, d))

        except Exception as e:
            st.error(str(e))
            st.stop()

    # -----------------------------
    # Result header
    # -----------------------------
    st.markdown(f"# 당신에게 딱인 장르는: **{top1}**!")
    badges = "".join([f'<span class="badge">#{b}</span>' for b in chosen])
    st.markdown(f"<div>{badges}</div>", unsafe_allow_html=True)

    if top2:
        st.caption(f"보조 취향 장르: {top2}")

    # -----------------------------
    # Podium TOP 3
    # -----------------------------
    st.subheader("🏆 TOP 3 시상대")
    podium = enriched[:3]
    pcols = st.columns(3)
    medals = ["🥇 1위", "🥈 2위", "🥉 3위"]
    for i in range(3):
        with pcols[i]:
            st.markdown('<div class="podium">', unsafe_allow_html=True)
            if i < len(podium):
                m, d = podium[i]
                title = d.get("title") or m.get("title") or "제목 정보 없음"
                vote_avg = float(d.get("vote_average") or m.get("vote_average") or 0.0)
                poster_url = build_image_url(cfg, (d.get("poster_path") or m.get("poster_path")), "w500")
                st.markdown(f"### {medals[i]}")
                if poster_url:
                    st.image(poster_url, use_container_width=True)
                st.write(f"**{title}**")
                st.write(f"⭐ {vote_avg:.1f}/10")
            else:
                st.write("결과가 부족해요.")
            st.markdown("</div>", unsafe_allow_html=True)

    st.divider()

    # -----------------------------
    # Recommendations in 3 columns
    # -----------------------------
    st.subheader("🎬 추천 영화 (3열 카드)")
    cols = st.columns(3)

    for idx, (m, d) in enumerate(enriched):
        col = cols[idx % 3]
        with col:
            title = d.get("title") or m.get("title") or "제목 정보 없음"
            overview = d.get("overview") or m.get("overview") or "줄거리 정보가 없어요."
            vote_avg = float(d.get("vote_average") or m.get("vote_average") or 0.0)
            poster_url = build_image_url(cfg, (d.get("poster_path") or m.get("poster_path")), "w500")
            trailer = pick_trailer_url(d)

            # 카드 UI
            st.markdown('<div class="movie-card">', unsafe_allow_html=True)
            if poster_url:
                st.image(poster_url, use_container_width=True)
            else:
                st.info("포스터 없음")

            st.markdown(f"**{title}**")
            st.markdown(f"⭐ **{vote_avg:.1f}** / 10")

            # "카드 클릭" 요구사항은 Streamlit에서 카드 자체 클릭 이벤트가 제한적이라
            # expander를 카드 내부에 배치해 UX를 만족시키는 방식으로 구현
            with st.expander("상세 정보 보기"):
                st.write(overview)

                # 추가 정보(옵션)
                genres_badge = [g for g in chosen]
                st.markdown("**이 영화를 추천하는 이유**")
                st.write(f"- {movie_reason(genres_badge, vote_avg, bool(trailer), viewer_mood)}")

                if trailer:
                    st.link_button("🎞️ 트레일러 보기", trailer)

                # 크레딧 일부
                credits = d.get("credits") or {}
                cast = credits.get("cast") or []
                if cast:
                    top_cast = [c.get("name") for c in cast[:5] if c.get("name")]
                    if top_cast:
                        st.caption("출연: " + ", ".join(top_cast))

            st.markdown("</div>", unsafe_allow_html=True)

    st.divider()
    st.caption("필터(평점/국가/연령대/기분)를 바꿔서 다시 결과를 눌러보면 추천이 달라져요!")
