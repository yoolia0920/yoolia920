import streamlit as st
import requests

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
POSTER_BASE = "https://image.tmdb.org/t/p/w500"


# -----------------------------
# TMDB
# -----------------------------
@st.cache_data(show_spinner=False, ttl=60 * 30)
def fetch_movies_by_genre(api_key: str, genre_id: int, n: int = 5):
    """
    TMDB discover/movie로 특정 장르 인기 영화 n개 가져오기
    """
    url = "https://api.themoviedb.org/3/discover/movie"
    params = {
        "api_key": api_key,
        "with_genres": genre_id,
        "language": "ko-KR",
        "sort_by": "popularity.desc",
        "page": 1,
        "include_adult": False,
    }
    r = requests.get(url, params=params, timeout=15)
    r.raise_for_status()
    data = r.json()
    return (data.get("results") or [])[:n]


# -----------------------------
# Analyze answers -> genre
# (간단 점수 기반. 필요하면 규칙/가중치만 바꾸면 됨)
# -----------------------------
def decide_genre(answers: dict):
    # 점수 초기화
    scores = {g: 0 for g in GENRES.keys()}
    reasons = {g: [] for g in GENRES.keys()}

    # Q1 주말
    if answers["q1"] == "집에서 휴식":
        scores["드라마"] += 2
        scores["로맨스"] += 1
        reasons["드라마"].append("주말엔 조용히 쉬며 감정선 있는 이야기에 몰입하는 편이에요.")
        reasons["로맨스"].append("편안한 분위기의 관계 중심 이야기도 잘 맞아요.")
    elif answers["q1"] == "친구와 놀기":
        scores["코미디"] += 2
        reasons["코미디"].append("사람들과 웃고 떠드는 에너지가 강해요.")
    elif answers["q1"] == "새로운 곳 탐험":
        scores["액션"] += 2
        scores["판타지"] += 1
        reasons["액션"].append("새로운 경험과 도전을 좋아하는 편이에요.")
        reasons["판타지"].append("낯선 세계를 탐험하는 설정에도 끌릴 수 있어요.")
    elif answers["q1"] == "혼자 취미생활":
        scores["SF"] += 2
        scores["판타지"] += 1
        reasons["SF"].append("혼자 깊게 몰입하는 설정/아이디어형 이야기를 좋아할 가능성이 커요.")
        reasons["판타지"].append("상상력 자극하는 세계관도 잘 맞아요.")

    # Q2 스트레스
    if answers["q2"] == "혼자 있기":
        scores["드라마"] += 2
        scores["SF"] += 1
        reasons["드라마"].append("혼자만의 시간으로 감정을 정리하는 타입이에요.")
        reasons["SF"].append("몰입감 있는 세계로 잠시 도피하는 것도 잘 맞아요.")
    elif answers["q2"] == "수다 떨기":
        scores["코미디"] += 2
        scores["로맨스"] += 1
        reasons["코미디"].append("대화와 웃음으로 스트레스를 푸는 편이에요.")
        reasons["로맨스"].append("사람 이야기 중심 장르에도 공감이 잘 가요.")
    elif answers["q2"] == "운동하기":
        scores["액션"] += 2
        reasons["액션"].append("에너지와 속도감이 있는 전개를 선호할 가능성이 커요.")
    elif answers["q2"] == "맛있는 거 먹기":
        scores["코미디"] += 2
        scores["로맨스"] += 1
        reasons["코미디"].append("기분 전환은 ‘즐거움’이 중요한 편이에요.")
        reasons["로맨스"].append("소소한 행복을 담은 이야기에도 잘 끌려요.")

    # Q3 영화에서 중요한 것
    if answers["q3"] == "감동 스토리":
        scores["드라마"] += 2
        scores["로맨스"] += 1
        reasons["드라마"].append("여운이 남는 스토리를 중요하게 여겨요.")
        reasons["로맨스"].append("감정선이 탄탄한 영화가 잘 맞아요.")
    elif answers["q3"] == "시각적 영상미":
        scores["SF"] += 2
        scores["판타지"] += 1
        reasons["SF"].append("스케일 큰 비주얼과 설정을 좋아할 확률이 높아요.")
        reasons["판타지"].append("환상적인 장면/세계관에 매력을 느껴요.")
    elif answers["q3"] == "깊은 메시지":
        scores["SF"] += 2
        scores["드라마"] += 1
        reasons["SF"].append("‘만약에?’ 같은 질문을 던지는 작품을 좋아할 가능성이 커요.")
        reasons["드라마"].append("현실을 비추는 묵직한 이야기에도 끌려요.")
    elif answers["q3"] == "웃는 재미":
        scores["코미디"] += 2
        reasons["코미디"].append("재미와 웃음 포인트를 가장 중요하게 봐요.")

    # Q4 여행 스타일
    if answers["q4"] == "계획적":
        scores["드라마"] += 2
        reasons["드라마"].append("차분하게 흐름을 따라가는 서사와 잘 맞아요.")
    elif answers["q4"] == "즉흥적":
        scores["로맨스"] += 2
        scores["코미디"] += 1
        reasons["로맨스"].append("우연과 설렘이 있는 전개에 끌릴 가능성이 커요.")
        reasons["코미디"].append("즉흥에서 나오는 웃긴 상황도 좋아할 수 있어요.")
    elif answers["q4"] == "액티비티":
        scores["액션"] += 2
        reasons["액션"].append("박진감 넘치는 전개가 찰떡이에요.")
    elif answers["q4"] == "힐링":
        scores["로맨스"] += 2
        scores["드라마"] += 1
        reasons["로맨스"].append("따뜻하고 편안한 분위기의 영화가 잘 맞아요.")
        reasons["드라마"].append("잔잔한 여운도 좋아할 수 있어요.")

    # Q5 친구 사이에서 나는
    if answers["q5"] == "듣는 역할":
        scores["드라마"] += 2
        scores["로맨스"] += 1
        reasons["드라마"].append("인물의 감정과 관계를 세심하게 보는 편이에요.")
        reasons["로맨스"].append("관계 중심 이야기와도 잘 맞아요.")
    elif answers["q5"] == "주도하기":
        scores["액션"] += 2
        reasons["액션"].append("주인공이 돌파하는 서사에 끌릴 가능성이 커요.")
    elif answers["q5"] == "분위기 메이커":
        scores["코미디"] += 2
        reasons["코미디"].append("분위기를 띄우는 유쾌한 에너지가 강해요.")
    elif answers["q5"] == "필요할 때 나타남":
        scores["SF"] += 2
        scores["판타지"] += 1
        reasons["SF"].append("반전/설정형 이야기, 미스터리한 전개를 좋아할 수 있어요.")
        reasons["판타지"].append("숨겨진 능력/운명 같은 설정에도 끌릴 수 있어요.")

    # 최고 점수 장르 선택 (동점이면 우선순위로 결정)
    max_score = max(scores.values())
    candidates = [g for g, s in scores.items() if s == max_score]
    tie_break = ["드라마", "로맨스", "액션", "SF", "판타지", "코미디"]
    selected = next((g for g in tie_break if g in candidates), candidates[0])

    # 추천 이유는 해당 장르 reasons에서 중복 제거 후 2~3개
    uniq = []
    for r in reasons[selected]:
        if r not in uniq:
            uniq.append(r)
    if not uniq:
        uniq = ["당신의 답변 패턴이 이 장르의 분위기와 잘 맞아요."]
    picked_reasons = uniq[:3]

    return selected, scores, picked_reasons


def safe_text(s: str) -> str:
    return s if s else ""


# -----------------------------
# UI
# -----------------------------
st.title("🎬 나와 어울리는 영화는?")
st.write("간단한 질문 5개로 당신에게 어울리는 영화 장르를 찾고, TMDB에서 인기 영화 5편을 추천해요! 🍿")

with st.sidebar:
    st.header("TMDB API")
    api_key = st.text_input("API Key", type="password", placeholder="TMDB API Key 입력")
    st.caption("배포할 땐 st.secrets 사용을 권장해요.")

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

    # 2) 분석해서 장르 결정
    genre_name, scores, genre_reasons = decide_genre(answers)
    genre_id = GENRES[genre_name]

    # 1) 버튼 누르면 분석 중...
    with st.spinner("분석 중..."):
        try:
            # 3) TMDB에서 해당 장르 인기 영화 5개
            movies = fetch_movies_by_genre(api_key=api_key, genre_id=genre_id, n=5)
        except requests.HTTPError as e:
            st.error("TMDB 요청에 실패했어요. API Key가 올바른지, 네트워크가 정상인지 확인해 주세요.")
            st.stop()
        except Exception:
            st.error("요청 처리 중 오류가 발생했어요. 잠시 후 다시 시도해 주세요.")
            st.stop()

    st.subheader(f"당신과 어울리는 장르: **{genre_name}**")
    st.caption(
        "장르 점수(참고): "
        + ", ".join([f"{g} {s}" for g, s in sorted(scores.items(), key=lambda x: -x[1])])
    )

    st.markdown("### 이 장르를 추천하는 이유")
    for r in genre_reasons:
        st.write(f"- {r}")

    st.divider()
    st.subheader("추천 영화 TOP 5")

    if not movies:
        st.warning("영화를 가져오지 못했어요. 다른 장르로 다시 시도해 볼까요?")
        st.stop()

    for m in movies:
        title = safe_text(m.get("title") or m.get("name") or "제목 정보 없음")
        overview = safe_text(m.get("overview") or "줄거리 정보가 없어요.")
        vote = float(m.get("vote_average") or 0.0)
        poster_path = m.get("poster_path")
        poster_url = f"{POSTER_BASE}{poster_path}" if poster_path else None

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

            # 5) 추천 이유 (간단)
            st.markdown("**이 영화를 추천하는 이유**")
            st.write(f"- 당신의 답변에서 **{genre_name}** 취향이 가장 강하게 나타났어요.")
            st.write("- 해당 장르에서 지금 인기(인기도 기준) 있는 작품을 골랐어요.")

        st.divider()


