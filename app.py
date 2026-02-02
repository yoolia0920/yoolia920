import re
import requests
import streamlit as st
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry

st.set_page_config(page_title="🎬 나와 어울리는 영화는?", page_icon="🎬", layout="wide")

# -----------------------------
# Constants
# -----------------------------
GENRES = {
    "액션": 28,
    "코미디": 35,
    "드라마": 18,
    "SF": 878,
    "로맨스": 10749,
    "판타지": 14,
}
TIE_BREAK = ["드라마", "로맨스", "액션", "SF", "판타지", "코미디"]

MOOD_PRESET = {
    "힐링": {"sort_by": "popularity.desc", "min_vote_count": 50, "prefer_genres": ["드라마", "로맨스"]},
    "긴장": {"sort_by": "popularity.desc", "min_vote_count": 200, "prefer_genres": ["액션", "SF"]},
    "설렘": {"sort_by": "popularity.desc", "min_vote_count": 80, "prefer_genres": ["로맨스", "드라마"]},
    "웃김": {"sort_by": "popularity.desc", "min_vote_count": 80, "prefer_genres": ["코미디"]},
    "상상력": {"sort_by": "popularity.desc", "min_vote_count": 100, "prefer_genres": ["SF", "판타지"]},
}

# [한국영화/외국영화/모두] 필터용 (TMDB origin_country는 movie에는 직접 필터가 제한적이라
# primary_release_country=KR + with_original_language=ko 조합을 사용)
REGION_MODE = {
    "모두": None,
    "한국영화": "KR",
    "외국영화": "FOREIGN",
}


# -----------------------------
# HTTP Session with Retry
# -----------------------------
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


# -----------------------------
# TMDB APIs
# -----------------------------
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

    # 국가 필터 (근사치)
    if country_mode == "한국영화":
        params["with_original_language"] = "ko"
        params["region"] = "KR"
        params["primary_release_country"] = "KR"
    elif country_mode == "외국영화":
        # 한국어/한국개봉 우선 조건을 피하려고 region 미사용,
        # ko 원어 제외로 필터링
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


# -----------------------------
# Quiz -> Genre scoring
# -----------------------------
def decide_genres_and_reasons(answers: dict):
    scores = {g: 0 for g in GENRES.keys()}
    reasons_pool = {g: [] for g in GENRES.keys()}

    def add(g, pts, reason):
        scores[g] += pts
        reasons_pool[g].append(reason)

    # Q1 (상황형으로 변경)
    # 원래: 주말에 가장 하고 싶은 것은?
    # 변경: 영화 속 주인공이 되어 주말 장면을 선택
    if answers["q1"] == "집에서 휴식":
        add("드라마", 2, "영화 속에서도 조용히 쉬며 감정선을 따라가는 장면을 선택했어요.")
        add("로맨스", 1, "따뜻한 관계 중심 장면에도 끌리는 편이에요.")
    elif answers["q1"] == "친구와 놀기":
        add("코미디", 2, "왁자지껄한 케미가 터지는 장면을 고르는 편이에요.")
    elif answers["q1"] == "새로운 곳 탐험":
        add("액션", 2, "새로운 장소에서 사건이 벌어지는 전개를 좋아해요.")
        add("판타지", 1, "낯선 세계를 탐험하는 설정에도 잘 끌려요.")
    elif answers["q1"] == "혼자 취미생활":
        add("SF", 2, "혼자 몰입하는 ‘설정/아이디어’ 중심 장면과 잘 맞아요.")
        add("판타지", 1, "상상력 자극하는 요소에도 관심이 있어요.")

    # Q2 스트레스
    if answers["q2"] == "혼자 있기":
        add("드라마", 2, "감정을 정리하는 조용한 장면이 어울려요.")
        add("SF", 1, "몰입감 있는 세계관으로 빠져들기 좋아요.")
    elif answers["q2"] == "수다 떨기":
        add("코미디", 2, "대화 템포가 빠르고 웃긴 장면이 취향이에요.")
        add("로맨스", 1, "사람 이야기 중심 전개도 공감이 잘 가요.")
    elif answers["q2"] == "운동하기":
        add("액션", 2, "몸으로 풀어내는 에너지 넘치는 전개가 찰떡이에요.")
    elif answers["q2"] == "맛있는 거 먹기":
        add("코미디", 2, "기분 전환은 결국 ‘즐거움’이 중요해요.")
        add("로맨스", 1, "소소한 행복을 담은 이야기에도 끌려요.")

    # Q3 영화에서 중요한 것은? (상황형으로 변경)
    # 원래: 영화에서 중요한 것은?
    # 변경: 네가 주인공이라면 어떤 ‘한 방’ 장면이 중요?
    if answers["q3"] == "감동 스토리":
        add("드라마", 2, "주인공의 성장/치유 같은 감정선이 가장 중요해요.")
        add("로맨스", 1, "관계의 변화가 설레거나 찡하게 다가와요.")
    elif answers["q3"] == "시각적 영상미":
        add("SF", 2, "비주얼과 스케일이 큰 장면에서 전율을 느껴요.")
        add("판타지", 1, "환상적인 세계관 연출을 좋아해요.")
    elif answers["q3"] == "깊은 메시지":
        add("SF", 2, "‘만약에?’를 던지는 설정과 메시지를 좋아해요.")
        add("드라마", 1, "현실을 비추는 묵직한 이야기에도 끌려요.")
    elif answers["q3"] == "웃는 재미":
        add("코미디", 2, "재치 있는 대사와 상황 코미디가 최고예요.")

    # Q4 여행 스타일?
    if answers["q4"] == "계획적":
        add("드라마", 2, "차분하게 흐름을 따라가는 서사와 잘 맞아요.")
    elif answers["q4"] == "즉흥적":
        add("로맨스", 2, "우연과 설렘이 있는 전개에 끌릴 가능성이 커요.")
        add("코미디", 1, "즉흥에서 나오는 웃긴 상황도 좋아할 수 있어요.")
    elif answers["q4"] == "액티비티":
        add("액션", 2, "박진감 넘치는 전개를 선호할 가능성이 커요.")
    elif answers["q4"] == "힐링":
        add("로맨스", 2, "따뜻하고 편안한 분위기의 영화가 잘 맞아요.")
        add("드라마", 1, "잔잔한 여운도 좋아할 수 있어요.")

    # Q5 친구 사이에서 나는?
    if answers["q5"] == "듣는 역할":
        add("드라마", 2, "인물의 감정과 관계를 세심하게 보는 편이에요.")
        add("로맨스", 1, "관계 중심 이야기와도 잘 맞아요.")
    elif answers["q5"] == "주도하기":
        add("액션", 2, "주인공이 돌파하는 서사에 끌릴 가능성이 커요.")
    elif answers["q5"] == "분위기 메이커":
        add("코미디", 2, "유쾌한 에너지가 강해서 웃긴 영화가 찰떡이에요.")
    elif answers["q5"] == "필요할 때 나타남":
        add("SF", 2, "설정/반전/미스터리 요소에 끌릴 수 있어요.")
        add("판타지", 1, "숨겨진 능력/운명 같은 설정도 좋아할 수 있어요.")

    # top1 / top2
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
            if x not in out:
                out.append(x)
        return out[:k] if out else ["당신의 답변 패턴이 이 장르 분위기와 잘 맞아요."]

    return scores, top1, top2, uniq_take(reasons_pool[top1], 3), (uniq_take(reasons_pool[top2], 2) if top2 else [])


def normalize_title(t: str) -> str:
    t = (t or "").strip().lower()
    t = re.sub(r"\s+", " ", t)
    t = re.sub(r"[^\w\s가-힣]", "", t)
    return t


def movie_reason(genre_names: list[str], vote_avg: float, has_trailer: bool) -> str:
    bits = [f"취향 장르(**{', '.join(genre_names)}**) 기반으로 지금 인기 있는 작품을 골랐어요."]
    if vote_avg >= 7.5:
        bits.append("평점이 높은 편이라 만족도가 좋아요.")
    if has_trailer:
        bits.append("트레일러로 분위기를 먼저 확인할 수 있어요.")
    return " ".join(bits)


# -----------------------------
# UI
# -----------------------------
st.title("🎬 나와 어울리는 영화는?")
st.write("질문 5개로 취향 장르를 분석하고, TMDB에서 인기 영화 5편을 추천해요! 🍿")

with st.sidebar:
    st.header("TMDB 인증")
    api_key = st.text_input("API Key (v3)", type="password", placeholder="선택")
    v4_token = st.text_input("Read Access Token (v4)", type="password", placeholder="선택")
    st.caption("둘 중 하나만 입력해도 돼요. (둘 다 있으면 v4 토큰을 우선 사용)")

    st.divider()
    st.header("추천 옵션")
    language = st.selectbox("언어(language)", ["ko-KR", "en-US"], index=0)
    sort_by = st.selectbox("정렬 기준", ["popularity.desc", "vote_average.desc"], index=0)

    st.subheader("평점 범위")
    vote_min, vote_max = st.slider("최저/최고 평점", 0.0, 10.0, (6.0, 9.5), step=0.1)

    st.subheader("국가 필터")
    country_mode = st.radio("[한국영화/외국영화/모두]", ["모두", "한국영화", "외국영화"], index=0)

    min_vote_count = st.slider("최소 평가 수(신뢰도)", 0, 2000, 200, step=50)

st.divider()

# ✅ 질문 2개를 '주인공 상황 가정형'으로 수정 (q1, q3)
q1 = st.radio(
    "1. (영화 주인공) 오늘은 주말! 당신이 주인공이라면 첫 장면에서 뭘 할까?",
    ["집에서 휴식", "친구와 놀기", "새로운 곳 탐험", "혼자 취미생활"],
    key="q1",
)
q2 = st.radio(
    "2. 스트레스 받으면?",
    ["혼자 있기", "수다 떨기", "운동하기", "맛있는 거 먹기"],
    key="q2",
)
q3 = st.radio(
    "3. (영화 주인공) 클라이맥스에서 당신이 제일 보고 싶은 ‘한 방’ 장면은?",
    ["감동 스토리", "시각적 영상미", "깊은 메시지", "웃는 재미"],
    key="q3",
)
q4 = st.radio(
    "4. 여행 스타일?",
    ["계획적", "즉흥적", "액티비티", "힐링"],
    key="q4",
)
q5 = st.radio(
    "5. 친구 사이에서 나는?",
    ["듣는 역할", "주도하기", "분위기 메이커", "필요할 때 나타남"],
    key="q5",
)

st.divider()

if st.button("결과 보기", type="primary"):
    if not (v4_token.strip() if v4_token else "") and not (api_key.strip() if api_key else ""):
        st.error("사이드바에 API Key(v3) 또는 Read Access Token(v4) 중 하나를 입력해 주세요.")
        st.stop()

    answers = {"q1": q1, "q2": q2, "q3": q3, "q4": q4, "q5": q5}

    with st.spinner("분석 중..."):
        try:
            cfg = fetch_configuration(api_key, v4_token)

            scores, top1, top2, reasons1, reasons2 = decide_genres_and_reasons(answers)
            chosen = [top1] + ([top2] if top2 else [])
            with_genres = ",".join(str(GENRES[g]) for g in chosen)

            # 후보 많이 가져와서 dedup 후 5개 선정
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

            top_list = deduped[:9]  # 3열로 보여주려면 9개가 보기 좋아서
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

    # ✅ 요구사항 1) 결과 제목
    st.markdown(f"# 당신에게 딱인 장르는: **{top1}**!")
    if top2:
        st.caption(f"보조 취향 장르: {top2}")

    # ✅ 요구사항 8) 1-3위 시상대(상단)
    st.subheader("🏆 TOP 3 시상대")
    podium = enriched[:3]
    pcols = st.columns(3)
    medals = ["🥇 1위", "🥈 2위", "🥉 3위"]
    for i in range(3):
        with pcols[i]:
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

    st.divider()

    # ✅ 3열 카드 (요구사항 2~5)
    st.subheader("🎬 추천 영화")
    cols = st.columns(3)
    for idx, (m, d) in enumerate(enriched):
        col = cols[idx % 3]
        with col:
            title = d.get("title") or m.get("title") or "제목 정보 없음"
            vote_avg = float(d.get("vote_average") or m.get("vote_average") or 0.0)
            overview = d.get("overview") or m.get("overview") or "줄거리 정보가 없어요."
            poster_url = build_image_url(cfg, (d.get("poster_path") or m.get("poster_path")), "w500")
            trailer = pick_trailer_url(d)

            # 카드 내용 (포스터/제목/평점)
            if poster_url:
                st.image(poster_url, use_container_width=True)
            else:
                st.info("포스터 없음")
            st.write(f"**{title}**")
            st.write(f"⭐ {vote_avg:.1f}/10")

            # ✅ 카드 클릭(대신 expander로 상세 제공)
            with st.expander("상세 보기"):
                st.write(overview)
                st.markdown("**이 영화를 추천하는 이유**")
                st.write(f"- {movie_reason(chosen, vote_avg, bool(trailer))}")
                if trailer:
                    st.link_button("🎞️ 트레일러 보기", trailer)

    st.divider()
    st.caption("필터를 바꾸고 다시 결과를 눌러보면 추천이 달라져요.")



