import os
import requests
import streamlit as st
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry

st.set_page_config(page_title="🎬 나와 어울리는 영화는?", page_icon="🎬", layout="centered")

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

# 동점일 때 선호 우선순위
TIE_BREAK = ["드라마", "로맨스", "액션", "SF", "판타지", "코미디"]


# -----------------------------
# HTTP session with retry
# -----------------------------
@st.cache_resource
def get_session() -> requests.Session:
    s = requests.Session()
    retry = Retry(
        total=3,
        backoff_factor=0.5,
        status_forcelist=[429, 500, 502, 503, 504],
        allowed_methods=["GET"],
        raise_on_status=False,
    )
    adapter = HTTPAdapter(max_retries=retry)
    s.mount("https://", adapter)
    s.mount("http://", adapter)
    return s


def tmdb_get(session: requests.Session, url: str, params: dict, timeout: int = 15) -> dict:
    r = session.get(url, params=params, timeout=timeout)
    # 여기서 raise_for_status를 쓰면 TMDB가 내려주는 JSON 에러 메시지를 못 보게 되는 경우가 있어,
    # 아래에서 status code 기반으로 메시지를 친절하게 처리합니다.
    try:
        data = r.json()
    except Exception:
        data = {}

    if r.status_code >= 400:
        # TMDB Errors 가이드 기반으로 대표 케이스 핸들링 :contentReference[oaicite:4]{index=4}
        if r.status_code == 401:
            raise RuntimeError("인증 실패(401). API Key가 올바른지 확인해 주세요.")
        if r.status_code == 404:
            raise RuntimeError("리소스를 찾을 수 없어요(404).")
        if r.status_code == 422:
            raise RuntimeError("요청 파라미터가 올바르지 않아요(422).")
        if r.status_code == 429:
            raise RuntimeError("요청이 너무 많아요(429). 잠시 후 다시 시도해 주세요.")
        if r.status_code >= 500:
            raise RuntimeError("TMDB 서버 오류(5xx). 잠시 후 다시 시도해 주세요.")

        msg = data.get("status_message") or f"TMDB 요청 실패 (HTTP {r.status_code})"
        raise RuntimeError(msg)

    return data


# -----------------------------
# TMDB API helpers
# -----------------------------
@st.cache_data(show_spinner=False, ttl=60 * 60)  # 1시간 캐시
def fetch_configuration(api_key: str) -> dict:
    session = get_session()
    url = "https://api.themoviedb.org/3/configuration"
    params = {"api_key": api_key}
    return tmdb_get(session, url, params)


def build_image_url(cfg: dict, file_path: str | None, size_preference: str = "w500") -> str | None:
    """
    Image Basics 문서의 방식대로: base_url + size + file_path :contentReference[oaicite:5]{index=5}
    """
    if not file_path:
        return None
    images = (cfg or {}).get("images") or {}
    base_url = images.get("secure_base_url") or images.get("base_url")
    if not base_url:
        # fallback(드물지만)
        return f"https://image.tmdb.org/t/p/{size_preference}{file_path}"

    sizes = images.get("poster_sizes") or []
    size = size_preference if size_preference in sizes else (sizes[-1] if sizes else size_preference)
    return f"{base_url}{size}{file_path}"


@st.cache_data(show_spinner=False, ttl=60 * 10)
def discover_movies(api_key: str, with_genres: str, language: str, region: str | None, sort_by: str, page: int = 1) -> list[dict]:
    session = get_session()
    url = "https://api.themoviedb.org/3/discover/movie"
    params = {
        "api_key": api_key,
        "with_genres": with_genres,  # 예: "18" 또는 "18,10749"
        "language": language,
        "region": region or None,
        "sort_by": sort_by,          # popularity.desc / vote_average.desc 등
        "page": page,
        "include_adult": False,
        "include_video": False,
    }
    data = tmdb_get(session, url, params)
    return data.get("results") or []


@st.cache_data(show_spinner=False, ttl=60 * 30)
def movie_details(api_key: str, movie_id: int, language: str) -> dict:
    """
    Append To Response 문서 기반: videos, images 등을 한 번에 :contentReference[oaicite:6]{index=6}
    """
    session = get_session()
    url = f"https://api.themoviedb.org/3/movie/{movie_id}"
    params = {
        "api_key": api_key,
        "language": language,
        "append_to_response": "videos,images",
        # images는 language에 영향 받을 수 있어 include_image_language를 같이 쓰면 유리
        # (이미지 언어 관련은 별도 문서에 더 자세히 있음)
        "include_image_language": "en,null,ko",
    }
    return tmdb_get(session, url, params)


def pick_trailer_url(details: dict) -> str | None:
    videos = (details.get("videos") or {}).get("results") or []
    # 유튜브 트레일러 우선
    for v in videos:
        if (v.get("site") == "YouTube") and ("Trailer" in (v.get("type") or "")) and v.get("key"):
            return f"https://www.youtube.com/watch?v={v['key']}"
    # 없으면 아무 유튜브 영상이라도
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

    # 1) 주말
    if answers["q1"] == "집에서 휴식":
        add("드라마", 2, "주말엔 차분하게 쉬며 감정선 있는 이야기에 몰입하는 편이에요.")
        add("로맨스", 1, "편안한 분위기의 관계 중심 스토리도 잘 맞아요.")
    elif answers["q1"] == "친구와 놀기":
        add("코미디", 2, "사람들과 웃고 떠드는 에너지가 강해요.")
    elif answers["q1"] == "새로운 곳 탐험":
        add("액션", 2, "새로운 경험과 도전을 즐기는 편이에요.")
        add("판타지", 1, "낯선 세계를 탐험하는 설정에도 끌릴 수 있어요.")
    elif answers["q1"] == "혼자 취미생활":
        add("SF", 2, "혼자 깊게 몰입할 수 있는 설정형 이야기가 잘 맞아요.")
        add("판타지", 1, "상상력 자극하는 세계관도 좋아할 가능성이 있어요.")

    # 2) 스트레스
    if answers["q2"] == "혼자 있기":
        add("드라마", 2, "혼자만의 시간으로 감정을 정리하는 타입이에요.")
        add("SF", 1, "몰입감 있는 세계로 잠시 도피하는 것도 잘 맞아요.")
    elif answers["q2"] == "수다 떨기":
        add("코미디", 2, "대화와 웃음으로 스트레스를 푸는 편이에요.")
        add("로맨스", 1, "사람 이야기 중심 장르에도 공감이 잘 가요.")
    elif answers["q2"] == "운동하기":
        add("액션", 2, "에너지와 속도감 있는 전개가 찰떡이에요.")
    elif answers["q2"] == "맛있는 거 먹기":
        add("코미디", 2, "기분 전환은 ‘즐거움’이 중요한 편이에요.")
        add("로맨스", 1, "소소한 행복을 담은 이야기에도 잘 끌려요.")

    # 3) 영화에서 중요한 것
    if answers["q3"] == "감동 스토리":
        add("드라마", 2, "여운이 남는 스토리를 중요하게 여겨요.")
        add("로맨스", 1, "감정선이 탄탄한 영화가 잘 맞아요.")
    elif answers["q3"] == "시각적 영상미":
        add("SF", 2, "스케일 큰 비주얼과 설정을 선호할 확률이 높아요.")
        add("판타지", 1, "환상적인 장면/세계관에 매력을 느껴요.")
    elif answers["q3"] == "깊은 메시지":
        add("SF", 2, "‘만약에?’ 같은 질문을 던지는 작품을 좋아할 가능성이 커요.")
        add("드라마", 1, "현실을 비추는 묵직한 이야기에도 끌려요.")
    elif answers["q3"] == "웃는 재미":
        add("코미디", 2, "재미와 웃음 포인트를 가장 중요하게 봐요.")

    # 4) 여행 스타일
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

    # 5) 친구 사이에서 나는?
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

    # 상위 1~2개 장르 선택(동점 처리 포함)
    sorted_scores = sorted(scores.items(), key=lambda x: x[1], reverse=True)
    top_score = sorted_scores[0][1]
    top_candidates = [g for g, s in sorted_scores if s == top_score]
    top1 = next((g for g in TIE_BREAK if g in top_candidates), sorted_scores[0][0])

    # 2등도 비슷하면 섞어서 추천(점수 차가 1 이하일 때만)
    top2 = None
    if len(sorted_scores) > 1:
        second_score = sorted_scores[1][1]
        if (top_score - second_score) <= 1 and second_score > 0:
            second_candidates = [g for g, s in sorted_scores if s == second_score and g != top1]
            if second_candidates:
                top2 = next((g for g in TIE_BREAK if g in second_candidates), second_candidates[0])

    # 이유(중복 제거, 최대 3개)
    def uniq_take(lst, k=3):
        out = []
        for x in lst:
            if x not in out:
                out.append(x)
        return out[:k] if out else ["당신의 답변 패턴이 이 장르 분위기와 잘 맞아요."]

    reasons_top1 = uniq_take(reasons_pool[top1], 3)
    reasons_top2 = uniq_take(reasons_pool[top2], 2) if top2 else []

    return scores, top1, top2, reasons_top1, reasons_top2


def movie_reason(genre_names: list[str], vote_avg: float, popularity: float, has_trailer: bool) -> str:
    bits = []
    if genre_names:
        bits.append(f"당신의 취향 장르(**{', '.join(genre_names)}**)와 잘 맞아요.")
    if vote_avg >= 7.5:
        bits.append("평점이 높은 편이라 만족도가 좋아요.")
    if popularity >= 80:
        bits.append("최근 인기도가 높아서 ‘입문용’으로 보기 좋아요.")
    if has_trailer:
        bits.append("트레일러로 분위기를 바로 확인할 수 있어요.")
    if not bits:
        bits.append("지금 인기 있는 작품 중에서 취향에 맞는 후보로 골랐어요.")
    return " ".join(bits)


# -----------------------------
# UI
# -----------------------------
st.title("🎬 나와 어울리는 영화는?")
st.write("5개의 질문으로 취향 장르를 분석하고, TMDB에서 인기 영화 5편을 추천해요! 🍿")

with st.sidebar:
    st.header("TMDB 설정")
    api_key = st.text_input("API Key", type="password", placeholder="TMDB v3 API Key")
    st.caption("팁: 배포 환경에서는 st.secrets 사용을 추천해요.")

    language = st.selectbox("언어(language)", ["ko-KR", "en-US"], index=0)
    region = st.text_input("지역(region, 선택)", value="KR", help="예: KR, US. 빈칸이면 미사용.")
    sort_by = st.selectbox("정렬 기준", ["popularity.desc", "vote_average.desc"], index=0)

st.divider()

q1 = st.radio(
    "1. 주말에 가장 하고 싶은 것은?",
    ["집에서 휴식", "친구와 놀기", "새로운 곳 탐험", "혼자 취미생활"],
    key="q1",
)
q2 = st.radio(
    "2. 스트레스 받으면?",
    ["혼자 있기", "수다 떨기", "운동하기", "맛있는 거 먹기"],
    key="q2",
)
q3 = st.radio(
    "3. 영화에서 중요한 것은?",
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
    if not api_key:
        st.error("사이드바에 TMDB API Key를 입력해 주세요.")
        st.stop()

    answers = {"q1": q1, "q2": q2, "q3": q3, "q4": q4, "q5": q5}

    with st.spinner("분석 중..."):
        try:
            # 1) configuration (이미지 URL 정석 구성에 필요) :contentReference[oaicite:7]{index=7}
            cfg = fetch_configuration(api_key)

            # 2) 장르 결정(상위 1~2개 섞기)
            scores, top1, top2, reasons1, reasons2 = decide_genres_and_reasons(answers)
            chosen_genres = [top1] + ([top2] if top2 else [])
            with_genres = ",".join(str(GENRES[g]) for g in chosen_genres)

            # 3) discover로 후보 가져오기
            candidates = discover_movies(
                api_key=api_key,
                with_genres=with_genres,
                language=language,
                region=(region.strip() or None),
                sort_by=sort_by,
                page=1,
            )

            # 후보가 너무 적으면 top1 단독으로 fallback
            if len(candidates) < 5 and top2 is not None:
                candidates = discover_movies(
                    api_key=api_key,
                    with_genres=str(GENRES[top1]),
                    language=language,
                    region=(region.strip() or None),
                    sort_by=sort_by,
                    page=1,
                )

            top5 = candidates[:5]

            # 4) 상세(append_to_response=videos,images)로 enrich :contentReference[oaicite:8]{index=8}
            enriched = []
            for m in top5:
                mid = m.get("id")
                if not mid:
                    continue
                d = movie_details(api_key, int(mid), language)
                enriched.append((m, d))

        except Exception as e:
            st.error(str(e))
            st.stop()

    # 결과 요약
    st.subheader(f"당신과 어울리는 장르: **{top1}**" + (f" + **{top2}**" if top2 else ""))
    st.caption(
        "장르 점수(참고): "
        + ", ".join([f"{g} {s}" for g, s in sorted(scores.items(), key=lambda x: -x[1])])
    )

    st.markdown("### 이 장르를 추천하는 이유")
    for r in reasons1:
        st.write(f"- {r}")
    if top2:
        for r in reasons2:
            st.write(f"- (보조 취향) {r}")

    st.divider()
    st.subheader("추천 영화 TOP 5")

    if not enriched:
        st.warning("추천 영화를 가져오지 못했어요. 정렬/지역을 바꾸거나 잠시 후 다시 시도해 주세요.")
        st.stop()

    for m, d in enriched:
        title = d.get("title") or m.get("title") or "제목 정보 없음"
        overview = d.get("overview") or m.get("overview") or "줄거리 정보가 없어요."
        vote = float(d.get("vote_average") or m.get("vote_average") or 0.0)
        popularity = float(d.get("popularity") or m.get("popularity") or 0.0)

        poster_path = d.get("poster_path") or m.get("poster_path")
        poster_url = build_image_url(cfg, poster_path, size_preference="w500")

        trailer_url = pick_trailer_url(d)
        reason_text = movie_reason(
            genre_names=chosen_genres,
            vote_avg=vote,
            popularity=popularity,
            has_trailer=bool(trailer_url),
        )

        left, right = st.columns([1, 2], vertical_alignment="top")

        with left:
            if poster_url:
                st.image(poster_url, use_container_width=True)
            else:
                st.info("포스터 없음")

        with right:
            st.markdown(f"### {title}")
            st.write(f"⭐ 평점: **{vote:.1f}** / 10")
            st.write(overview)

            st.markdown("**이 영화를 추천하는 이유**")
            st.write(f"- {reason_text}")

            if trailer_url:
                st.link_button("🎞️ 트레일러 보기", trailer_url)

        st.divider()



