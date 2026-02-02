import streamlit as st
import requests

st.set_page_config(page_title="나와 어울리는 영화는?", page_icon="🎬", layout="centered")

# -----------------------------
# TMDB 설정
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


@st.cache_data(show_spinner=False, ttl=60 * 30)
def fetch_movies(api_key: str, genre_id: int, n: int = 5):
    """TMDB discover로 장르별 인기 영화 가져오기"""
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
    results = data.get("results", [])
    return results[:n]


# -----------------------------
# 장르 점수 규칙(간단 분석)
# -----------------------------
# 각 선택지가 특정 장르 선호를 얼마나 반영하는지 점수화
# + 추천 이유 문구도 함께 저장
OPTION_RULES = {
    "q1": {  # 주말
        "집에서 휴식": [("드라마", 2, "집에서 쉬며 감정선이 깊은 이야기에 몰입하는 편이에요."),
                     ("로맨스", 1, "편안한 분위기의 설레는 이야기도 잘 맞아요.")],
        "친구와 놀기": [("코미디", 2, "사람들과 웃고 떠드는 에너지가 강해요.")],
        "새로운 곳 탐험": [("액션", 2, "새로운 경험/도전을 즐기는 편이에요."),
                        ("판타지", 1, "낯선 세계를 탐험하는 이야기에도 끌릴 수 있어요.")],
        "혼자 취미생활": [("SF", 2, "혼자만의 몰입을 즐기고 설정/아이디어에 끌리는 편이에요."),
                       ("판타지", 1, "상상력 자극하는 세계관도 잘 맞아요.")],
    },
    "q2": {  # 스트레스 해소
        "혼자 있기": [("드라마", 2, "조용히 감정을 정리하는 타입이에요."),
                    ("SF", 1, "혼자 빠져드는 몰입형 장르가 잘 맞아요.")],
        "수다 떨기": [("코미디", 2, "가벼운 분위기에서 스트레스를 날리는 편이에요."),
                   ("로맨스", 1, "사람 이야기 중심의 장르도 잘 맞아요.")],
        "운동하기": [("액션", 2, "에너지와 속도감 있는 전개를 선호할 가능성이 커요.")],
        "맛있는 거 먹기": [("코미디", 2, "기분 전환은 결국 ‘즐거움’이죠!"),
                        ("로맨스", 1, "소소한 행복을 담은 이야기에도 잘 끌려요.")],
    },
    "q3": {  # 영화에서 중요한 것
        "감동 스토리": [("드라마", 2, "여운이 남는 스토리에 끌리는 편이에요."),
                     ("로맨스", 1, "감정선이 중요한 영화가 잘 맞아요.")],
        "시각적 영상미": [("SF", 2, "비주얼·스케일이 큰 작품을 좋아할 확률이 높아요."),
                      ("판타지", 1, "환상적인 장면/세계관에 매력을 느끼는 편이에요.")],
        "깊은 메시지": [("SF", 2, "‘만약에?’를 던지는 작품을 좋아할 가능성이 커요."),
                     ("드라마", 1, "현실을 비추는 묵직한 이야기에도 끌려요.")],
        "웃는 재미": [("코미디", 2, "무조건 웃기고 재밌는 게 최고예요!")],
    },
    "q4": {  # 여행 스타일
        "계획적": [("드라마", 2, "차분하게 흐름을 따라가는 이야기와 잘 맞아요.")],
        "즉흥적": [("로맨스", 2, "우연과 설렘이 있는 전개에 끌릴 가능성이 커요."),
                ("코미디", 1, "즉흥에서 나오는 웃긴 상황도 좋아할 수 있어요.")],
        "액티비티": [("액션", 2, "박진감 넘치는 전개를 선호할 가능성이 커요.")],
        "힐링": [("로맨스", 2, "따뜻하고 편안한 분위기의 영화가 잘 맞아요."),
               ("드라마", 1, "잔잔한 여운도 좋아할 수 있어요.")],
    },
    "q5": {  # 친구 사이 역할
        "듣는 역할": [("드라마", 2, "인물의 감정과 관계를 세심하게 보는 편이에요."),
                   ("로맨스", 1, "관계 중심 이야기와도 잘 맞아요.")],
        "주도하기": [("액션", 2, "주도적으로 상황을 돌파하는 주인공 서사에 끌릴 수 있어요.")],
        "분위기 메이커": [("코미디", 2, "웃음 포인트를 잘 살리는 장르가 찰떡이에요.")],
        "필요할 때 나타남": [("SF", 2, "미스터리/설정형 캐릭터나 반전 요소를 좋아할 수 있어요."),
                         ("판타지", 1, "숨겨진 능력/운명 같은 설정에도 끌릴 수 있어요.")],
    },
}

# 동점일 때 선호 우선순위(원하면 바꿔도 됨)
TIE_BREAK = ["드라마", "로맨스", "액션", "SF", "판타지", "코미디"]


def decide_genre(answers: dict):
    scores = {g: 0 for g in GENRES.keys()}
    reasons_pool = {g: [] for g in GENRES.keys()}

    for q_key, choice in answers.items():
        rules = OPTION_RULES.get(q_key, {})
        for genre, pts, reason in rules.get(choice, []):
            scores[genre] += pts
            reasons_pool[genre].append(reason)

    max_score = max(scores.values())
    candidates = [g for g, s in scores.items() if s == max_score]

    # tie-break
    for g in TIE_BREAK:
        if g in candidates:
            selected = g
            break
    else:
        selected = candidates[0]

    # 추천 이유: 해당 장르에 쌓인 이유 중 상위 2~3개
    picked = []
    for r in reasons_pool[selected]:
        if r not in picked:
            picked.append(r)
    picked = picked[:3] if picked else ["당신의 답변 패턴이 이 장르의 분위기와 잘 맞아요."]

    return selected, scores, picked


# -----------------------------
# UI
# -----------------------------
st.title("🎬 나와 어울리는 영화는?")
st.write("간단한 질문 5개로 지금의 당신에게 딱 맞는 영화 장르를 찾고, TMDB에서 인기 영화 5편을 추천해요! 🎥✨")

with st.sidebar:
    st.header("TMDB API 설정")
    api_key = st.text_input("API Key", type="password", placeholder="여기에 TMDB API Key를 입력하세요")
    st.caption("키는 로컬에서만 사용되며, 서버 배포 시에는 secrets 사용을 권장해요.")

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

    # 2) 사용자 답변 분석해서 장르 결정
    genre_name, scores, picked_reasons = decide_genre(answers)
    genre_id = GENRES[genre_name]

    # 1) 버튼 누르면 분석 중... (짧게라도 표시)
    with st.spinner("분석 중..."):
        try:
            # 3) TMDB API로 해당 장르 인기 영화 5개
            movies = fetch_movies(api_key=api_key, genre_id=genre_id, n=5)
        except requests.HTTPError as e:
            st.error("TMDB 요청에 실패했어요. API Key가 올바른지 확인해 주세요.")
            st.stop()
        except Exception:
            st.error("요청 처리 중 오류가 발생했어요. 잠시 후 다시 시도해 주세요.")
            st.stop()

    st.subheader(f"당신과 어울리는 장르: **{genre_name}**")
    st.caption("장르 점수(참고): " + ", ".join([f"{g} {s}" for g, s in sorted(scores.items(), key=lambda x: -x[1])]))

    st.markdown("**이 장르를 추천하는 이유**")
    for r in picked_reasons:
        st.write(f"- {r}")

    st.divider()
    st.subheader("추천 영화 TOP 5")

    if not movies:
        st.warning("추천할 영화가 아직 없어요. 다른 장르로 다시 시도해 볼까요?")
        st.stop()

    for m in movies:
        title = m.get("title") or m.get("name") or "제목 정보 없음"
        overview = m.get("overview") or "줄거리 정보가 없어요."
        vote = m.get("vote_average", 0)
        poster_path = m.get("poster_path")
        poster_url = f"{POSTER_BASE}{poster_path}" if poster_path else None

        # 4) 포스터, 제목, 평점, 줄거리 표시
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

            # 5) 이 영화를 추천하는 이유 (간단)
            st.markdown("**이 영화를 추천하는 이유**")
            st.write(f"- 당신의 취향이 **{genre_name}** 쪽에 가까워서, 이 장르에서 반응이 좋은 인기 작품을 골랐어요.")
            st.write("- 부담 없이 시작하기 좋은 ‘요즘 인기작’ 중심으로 가져왔어요.")

        st.divider()

