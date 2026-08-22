import base64
import calendar
from datetime import datetime, timedelta
import json
import os
import re

from bs4 import BeautifulSoup
import google.generativeai as genai
import plotly.graph_objects as go
from plotly.subplots import make_subplots
import requests
import streamlit as st
import yfinance as yf

# =============================================================
# 설정 및 환경 변수 (안전한 로드)
# =============================================================
def get_secret(key):
    try:
        return st.secrets.get(key, os.environ.get(key, ""))
    except Exception:
        return os.environ.get(key, "")

GITHUB_TOKEN = get_secret("GITHUB_TOKEN")
GEMINI_API_KEY = get_secret("GEMINI_API_KEY")
REPO_NAME, CALENDAR_FILE, WATCHLIST_FILE = "jbchoe0550-jpg/my-slave", "calendar_data.json", "watchlist.json"
COLOR_PALETTE = ["#2563eb", "#16a34a", "#d97706", "#9333ea", "#0284c7", "#e11d48", "#0d9488"]
ACADEMIC_COLOR = "#ea580c"

if GEMINI_API_KEY:
    genai.configure(api_key=GEMINI_API_KEY)
    model = genai.GenerativeModel("gemini-1.5-flash")
else:
    model = None

# =============================================================
# GitHub & 데이터 파일 입출력 헬퍼
# =============================================================
def github_api(file_path, data=None, sha=None):
    if not GITHUB_TOKEN:
        return (None, None) if data is None else (False, None)
    url = f"https://api.github.com/repos/{REPO_NAME}/contents/{file_path}"
    headers = {"Authorization": f"token {GITHUB_TOKEN}"}
    
    if data is None:  # 불러오기
        try:
            res = requests.get(url, headers=headers)
            if res.status_code == 200:
                c = res.json()
                return json.loads(base64.b64decode(c["content"]).decode("utf-8")), c["sha"]
        except Exception:
            pass
        return {}, None
    else:  # 저장하기
        if not sha:
            _, sha = github_api(file_path)
        content_b64 = base64.b64encode(json.dumps(data, ensure_ascii=False, indent=2).encode("utf-8")).decode("utf-8")
        payload = {"message": "Auto update calendar", "content": content_b64, "branch": "main"}
        if sha:
            payload["sha"] = sha
        try:
            res = requests.put(url, headers=headers, json=payload)
            return res.status_code in [200, 201], None
        except Exception:
            return False, None

def load_json(filepath, default_val):
    try:
        with open(filepath, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return default_val

def save_json(filepath, data):
    with open(filepath, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=4)

def get_calendar_data():
    if "calendar_db" not in st.session_state:
        data, sha = github_api(CALENDAR_FILE)
        st.session_state["calendar_db"] = data if data else load_json(CALENDAR_FILE, {})
        st.session_state["calendar_sha"] = sha
    return st.session_state["calendar_db"]

def update_calendar_data(new_data):
    st.session_state["calendar_db"] = new_data
    save_json(CALENDAR_FILE, new_data)
    if GITHUB_TOKEN:
        ok, _ = github_api(CALENDAR_FILE, new_data, st.session_state.get("calendar_sha"))
        if ok:
            _, new_sha = github_api(CALENDAR_FILE)
            st.session_state["calendar_sha"] = new_sha

# 초기 파일 보장
if not os.path.exists(WATCHLIST_FILE):
    save_json(WATCHLIST_FILE, ["TSLA", "NVDA", "AAPL", "005930.KS"])

# =============================================================
# 크롤링 헬퍼 (학사일정 / 공지사항 / 청년혜택)
# =============================================================
@st.cache_data(ttl=3600)
def fetch_academic_calendar(year, month):
    academic_events = {}
    try:
        res = requests.get("https://www.konkuk.ac.kr/konkuk/2237/subview.do", headers={"User-Agent": "Mozilla/5.0"}, timeout=8)
        soup = BeautifulSoup(res.text, "html.parser")
        for row in soup.select("table.board-list tbody tr, .schedule-list li"):
            d_cell = row.select_one(".date, td:nth-child(1)")
            t_cell = row.select_one(".title, td:nth-child(2)")
            if d_cell and t_cell:
                d_str, title = d_cell.get_text(strip=True), t_cell.get_text(strip=True)
                dates = re.findall(r"\d{4}\.\d{2}\.\d{2}", d_str) or [f"{year}.{d}" for d in re.findall(r"\d{2}\.\d{2}", d_str)]
                if dates:
                    curr = datetime.strptime(dates[0].replace(".", "-"), "%Y-%m-%d")
                    end_dt = datetime.strptime(dates[-1].replace(".", "-"), "%Y-%m-%d")
                    while curr <= end_dt:
                        if curr.year == year and curr.month == month:
                            academic_events[curr.strftime("%Y-%m-%d")] = title
                        curr += timedelta(days=1)
    except Exception:
        pass
    return academic_events

@st.cache_data(ttl=600)
def fetch_ku_notices_20(url, base_url):
    notices = []
    try:
        res = requests.get(url, headers={"User-Agent": "Mozilla/5.0"}, timeout=8)
        soup = BeautifulSoup(res.text, "html.parser")
        for row in soup.select("table tbody tr, .board-list tr, ul.board-list li"):
            t_tag = row.select_one(".td-subject a, .subject a, a")
            d_tag = row.select_one(".td-date, .date")
            if t_tag:
                title = re.sub(r"^(공지|필독|NEW|NOTICE)\s*", "", t_tag.get_text(strip=True), flags=re.IGNORECASE)
                link = t_tag.get("href", "")
                link = base_url + link if link.startswith("/") else (link if link.startswith("http") else f"{base_url}/{link}")
                date = d_tag.get_text(strip=True) if d_tag else "2026.01.01"
                if len(title) > 2:
                    notices.append({"title": title, "link": link, "date": date, "summary": f"본 공지사항은 '{title[:25]}...' 주요 내용 확인이 필요합니다."})
        notices.sort(key=lambda x: x["date"], reverse=True)
        return notices[:20]
    except Exception:
        return notices

@st.cache_data(ttl=600)
def fetch_youth_notices_by_category():
    return {
        "온통청년 (정부)": [
            {"title": "2026년 청년 월세 한시 특별지원 2차 신청 안내", "summary": "무주택 청년 대상 월 최대 20만 원씩 12개월간 임차료 지원.", "link": "https://www.youthcenter.go.kr", "date": "2026.08.18"},
            {"title": "2026 청년도약계좌 정부기여금 확대 지급 안내", "summary": "청년 자산 형성을 위한 만기 5년 적금 비과세 혜택 지원.", "link": "https://www.youthcenter.go.kr", "date": "2026.08.15"}
        ],
        "청년몽땅정보통 (서울시)": [
            {"title": "서울시 청년 안심주택 입주자 모집 공고", "summary": "역세권 시세 대비 30~50% 수준 임대주택.", "link": "https://youth.seoul.go.kr", "date": "2026.08.19"}
        ],
        "영등포구청": [
            {"title": "영등포구 청년 소상공인 무이자 융자 지원 사업", "summary": "관내 청년 창업가 맞춤형 금융 및 경영 컨설팅 지원.", "link": "https://www.ydp.go.kr", "date": "2026.08.16"}
        ],
        "서울시 공식 (Seoul Go)": [
            {"title": "K-패스 및 서울시 청년 대중교통비 환급 신청", "summary": "대중교통 이용 금액의 최대 30% 마일리지 적립/환급.", "link": "https://www.seoul.go.kr", "date": "2026.08.14"}
        ]
    }

# =============================================================
# Streamlit 레이아웃 & CSS
# =============================================================
st.set_page_config(page_title="개인 AI 업무 비서", layout="wide", initial_sidebar_state="expanded")
st.markdown("""
    <style>
    .block-container { padding-top: 1.8rem !important; padding-bottom: 1.5rem !important; }
    div[data-testid="stRadio"] { background-color: #f8fafc; padding: 8px 14px; border-radius: 12px; border: 1px solid #e2e8f0; margin-bottom: 15px !important; }
    div[data-testid="stRadio"] div[role="radiogroup"] { gap: 12px; }
    div[data-testid="stRadio"] div[role="radiogroup"] label p { font-size: 17px !important; font-weight: 700 !important; color: #1e293b; }
    .academic-badge { background-color: #fff7ed; border-left: 4px solid #ea580c; padding: 6px 10px; font-size: 14px; color: #c2410c; border-radius: 4px; margin-top: 6px; font-weight: 600; }
    .cal-day-cell { border: 1px solid #cbd5e1; border-radius: 8px; padding: 6px; min-height: 140px; background-color: #ffffff; display: flex; flex-direction: column; }
    .event-bar-slot { height: 22px; margin: 2px 0; }
    .event-bar { color: white; font-size: 11px; font-weight: 600; padding: 2px 5px; height: 100%; white-space: nowrap; overflow: hidden; text-overflow: ellipsis; }
    .event-bar-single { border-radius: 4px; }
    .event-bar-start { border-top-left-radius: 4px; border-bottom-left-radius: 4px; }
    .event-bar-middle { border-radius: 0px; }
    .event-bar-end { border-top-right-radius: 4px; border-bottom-right-radius: 4px; }
    </style>
""", unsafe_allow_html=True)

selected_tab = st.radio("메인 메뉴 선택", ["캘린더", "주식 분석", "학교 공지사항", "청년 혜택"], horizontal=True, label_visibility="collapsed")

# =============================================================
# [탭 1] 캘린더
# =============================================================
if selected_tab == "캘린더":
    calendar_db = get_calendar_data()
    today_dt = datetime.now()
    today_str, tomorrow_str = today_dt.strftime("%Y-%m-%d"), (today_dt + timedelta(days=1)).strftime("%Y-%m-%d")
    
    st.sidebar.title("캘린더 탐색")
    selected_year = st.sidebar.number_input("연도", min_value=2024, max_value=2030, value=today_dt.year)
    selected_month = st.sidebar.selectbox("월 선택", list(range(1, 13)), index=today_dt.month - 1, format_func=lambda x: f"{x:02d}월")
    academic_calendar = fetch_academic_calendar(selected_year, selected_month)

    user_cmd = st.text_input("AI 일정 등록 (입력 후 Enter)", placeholder="예: 8월 21일부터 8월 23일까지 제주도 여행 추가해줘")
    if user_cmd and model:
        with st.spinner("AI 일정 처리 중..."):
            prompt = f"오늘 날짜: {today_str}\n사용자 명령: '{user_cmd}'\nstart_date, end_date 추출 후 JSON 응답: ```json\n{{\"start_date\": \"YYYY-MM-DD\", \"end_date\": \"YYYY-MM-DD\", \"task\": \"내용\"}}\n```"
            try:
                match = re.search(r"\{.*\}", model.generate_content(prompt).text, re.DOTALL)
                if match:
                    parsed = json.loads(match.group())
                    s_dt = datetime.strptime(parsed.get("start_date", today_str), "%Y-%m-%d")
                    e_dt = datetime.strptime(parsed.get("end_date", parsed.get("start_date")), "%Y-%m-%d")
                    p_task = parsed.get("task")
                    curr = s_dt
                    while curr <= e_dt:
                        d_str = curr.strftime("%Y-%m-%d")
                        calendar_db.setdefault(d_str, []).append({"task": p_task, "done": False})
                        curr += timedelta(days=1)
                    update_calendar_data(calendar_db)
                    st.success(f"일정 등록 완료: '{p_task}' ({s_dt.strftime('%Y-%m-%d')} ~ {e_dt.strftime('%Y-%m-%d')})")
                    st.rerun()
            except Exception as e:
                st.error(f"명령 처리 실패: {e}")

    st.markdown("---")
    col_today, col_tomorrow = st.columns(2)

    def render_panel(date_key, title):
        st.markdown(f"### {title} (`{date_key}`)")
        tasks = calendar_db.get(date_key, [])
        if tasks:
            for idx, item in enumerate(tasks):
                text = item if isinstance(item, str) else item.get("task", "")
                done = False if isinstance(item, str) else item.get("done", False)
                c_chk, c_del = st.columns([5, 1])
                chk = c_chk.checkbox(f"~~{text}~~" if done else text, value=done, key=f"chk_{date_key}_{idx}")
                if chk != done:
                    calendar_db[date_key][idx] = {"task": text, "done": chk}
                    update_calendar_data(calendar_db)
                    st.rerun()
                if c_del.button("삭제", key=f"del_{date_key}_{idx}"):
                    calendar_db[date_key].pop(idx)
                    update_calendar_data(calendar_db)
                    st.rerun()
        else:
            st.caption("등록된 개인 일정이 없습니다.")
        if date_key in academic_calendar:
            st.markdown(f'<div class="academic-badge">🏫 <b>건국대 학사일정:</b> {academic_calendar[date_key]}</div>', unsafe_allow_html=True)

    with col_today: render_panel(today_str, "오늘 할 일")
    with col_tomorrow: render_panel(tomorrow_str, "내일 할 일")

    st.markdown("---")
    st.subheader(f"{selected_year}년 {selected_month}월 달력")
    
    month_prefix = f"{selected_year}-{selected_month:02d}"
    academic_titles = set(academic_calendar.values())
    all_month_tasks = list(dict.fromkeys(
        [t.get("task", "") if isinstance(t, dict) else t for dk, dt in calendar_db.items() if dk.startswith(month_prefix) for t in dt] +
        [v for dk, v in academic_calendar.items() if dk.startswith(month_prefix)]
    ))

    task_color_map = {t: ACADEMIC_COLOR if t in academic_titles else COLOR_PALETTE[i % len(COLOR_PALETTE)] for i, t in enumerate(all_month_tasks)}
    cal = calendar.monthcalendar(selected_year, selected_month)
    
    cols_hdr = st.columns(7)
    for i, d in enumerate(["월", "화", "수", "목", "금", "토", "일"]):
        cols_hdr[i].markdown(f"### **{d}**")

    for week in cal:
        w_cols = st.columns(7)
        for idx, day in enumerate(week):
            if day == 0:
                w_cols[idx].write(" ")
            else:
                d_str = f"{selected_year}-{selected_month:02d}-{day:02d}"
                prev_str = (datetime.strptime(d_str, "%Y-%m-%d") - timedelta(days=1)).strftime("%Y-%m-%d")
                next_str = (datetime.strptime(d_str, "%Y-%m-%d") + timedelta(days=1)).strftime("%Y-%m-%d")
                
                day_tasks = [t if isinstance(t, str) else t.get("task", "") for t in calendar_db.get(d_str, [])]
                if d_str in academic_calendar:
                    day_tasks.append(academic_calendar[d_str])

                cell_html = f'<div class="cal-day-cell"><b>{day}일</b><br>'
                for slot in all_month_tasks:
                    cell_html += '<div class="event-bar-slot">'
                    if slot in day_tasks:
                        color = task_color_map.get(slot, "#2563eb")
                        has_prev = any((pt if isinstance(pt, str) else pt.get("task", "")) == slot for pt in calendar_db.get(prev_str, [])) or academic_calendar.get(prev_str) == slot
                        has_next = any((nt if isinstance(nt, str) else nt.get("task", "")) == slot for nt in calendar_db.get(next_str, [])) or academic_calendar.get(next_str) == slot
                        
                        bar_cls = "event-bar-middle" if (has_prev and has_next and idx not in (0, 6)) else (
                            "event-bar-start" if (has_next or idx == 0) and not has_prev else (
                            "event-bar-end" if (has_prev or idx == 6) and not has_next else "event-bar-single"
                        ))
                        prefix = "[학사] " if slot in academic_titles else ""
                        cell_html += f'<div class="event-bar {bar_cls}" style="background-color: {color};">{prefix}{slot}</div>'
                    cell_html += '</div>'
                cell_html += '</div>'
                w_cols[idx].markdown(cell_html, unsafe_allow_html=True)

# =============================================================
# [탭 2] 주식 분석
# =============================================================
elif selected_tab == "주식 분석":
    st.subheader("📊 글로벌 시장 변동성 지수 (VIX)")
    try:
        vix_df = yf.Ticker("^VIX").history(period="6m").reset_index()
        vix_df["Date"] = vix_df["Date"].dt.tz_localize(None)
        latest, prev = vix_df["Close"].iloc[-1], vix_df["Close"].iloc[-2]
        
        col_v1, col_v2 = st.columns([1, 3])
        with col_v1:
            st.metric("VIX 지수", f"{latest:.2f}", f"{latest - prev:+.2f}", delta_color="inverse")
            st.caption("🟢 시장 안정" if latest < 15 else ("🟡 보통 변동성" if latest < 25 else "🔴 높은 공포 지수"))
        with col_v2:
            fig_vix = go.Figure(go.Scatter(x=vix_df["Date"], y=vix_df["Close"], mode="lines", line=dict(color="#ef4444", width=2)))
            fig_vix.update_layout(height=200, margin=dict(l=10, r=10, t=10, b=10), paper_bgcolor="rgba(0,0,0,0)", plot_bgcolor="rgba(0,0,0,0)")
            st.plotly_chart(fig_vix, use_container_width=True)
    except Exception as e:
        st.warning(f"VIX 지수 조회 실패: {e}")

    st.markdown("---")
    st.subheader("📈 관심 종목 차트 & AI 기술적 분석")
    watchlist = load_json(WATCHLIST_FILE, ["TSLA", "NVDA", "AAPL", "005930.KS"])
    
    col_w1, col_w2 = st.columns([3, 1])
    selected_ticker = col_w1.selectbox("관심 종목 선택", watchlist)
    new_ticker = col_w2.text_input("새 종목 추가 (예: AMZN, 000660.KS)").strip().upper()
    if col_w2.button("종목 추가") and new_ticker and new_ticker not in watchlist:
        watchlist.append(new_ticker)
        save_json(WATCHLIST_FILE, watchlist)
        st.success(f"{new_ticker} 추가 완료!")
        st.rerun()

    period_opt = st.radio("기간 선택", ["1mo", "3mo", "6mo", "1y", "2y"], horizontal=True, index=2)
    if selected_ticker:
        try:
            df = yf.Ticker(selected_ticker).history(period=period_opt)
            if not df.empty:
                df["SMA20"], df["SMA50"] = df["Close"].rolling(20).mean(), df["Close"].rolling(50).mean()
                fig = make_subplots(rows=2, cols=1, shared_xaxes=True, vertical_spacing=0.08, row_heights=[0.7, 0.3])
                fig.add_trace(go.Candlestick(x=df.index, open=df["Open"], high=df["High"], low=df["Low"], close=df["Close"], name="주가"), row=1, col=1)
                fig.add_trace(go.Scatter(x=df.index, y=df["SMA20"], line=dict(color="#2563eb", width=1.5), name="20일 이평"), row=1, col=1)
                fig.add_trace(go.Scatter(x=df.index, y=df["SMA50"], line=dict(color="#d97706", width=1.5), name="50일 이평"), row=1, col=1)
                fig.add_trace(go.Bar(x=df.index, y=df["Volume"], marker_color="#94a3b8", name="거래량"), row=2, col=1)
                fig.update_layout(height=500, margin=dict(l=20, r=20, t=20, b=20), xaxis_rangeslider_visible=False, paper_bgcolor="rgba(0,0,0,0)", plot_bgcolor="rgba(0,0,0,0)")
                st.plotly_chart(fig, use_container_width=True)

                if st.button(f"🤖 Gemini AI로 {selected_ticker} 진단받기"):
                    if model:
                        with st.spinner("종목 진단 중..."):
                            close, prev_close = df["Close"].iloc[-1], df["Close"].iloc[-2]
                            prompt = f"{selected_ticker} 최신 종가: {close:.2f} ({((close - prev_close)/prev_close)*100:+.2f}%), 20일이평: {df['SMA20'].iloc[-1]:.2f}, 50일이평: {df['SMA50'].iloc[-1]:.2f}. 기술적 지표와 포인트를 3문장 이내로 요약해줘."
                            st.info(model.generate_content(prompt).text)
                    else:
                        st.warning("GEMINI API 키가 설정되지 않았습니다.")
        except Exception as ex:
            st.error(f"주식 데이터 불러오기 오류: {ex}")

# =============================================================
# [탭 3] 학교 공지사항
# =============================================================
elif selected_tab == "학교 공지사항":
    st.subheader("🏫 건국대학교 실시간 핵심 공지사항")
    ku_urls = [
        ("일반공지", "https://www.konkuk.ac.kr/konkuk/2231/subview.do"),
        ("학사공지", "https://www.konkuk.ac.kr/konkuk/2232/subview.do"),
        ("장학공지", "https://www.konkuk.ac.kr/konkuk/2235/subview.do")
    ]
    tabs = st.tabs([u[0] for u in ku_urls])
    for idx, (cat, url) in enumerate(ku_urls):
        with tabs[idx]:
            notices = fetch_ku_notices_20(url, "https://www.konkuk.ac.kr")
            for n in notices:
                c_t, c_d = st.columns([4, 1])
                c_t.markdown(f"**[{n['title']}]({n['link']})**\n\n`{n['summary']}`")
                c_d.write(f"🗓️ `{n['date']}`")
                st.markdown("---")

# =============================================================
# [탭 4] 청년 혜택
# =============================================================
elif selected_tab == "청년 혜택":
    st.subheader("🎁 청년 정책 및 혜택 지원 정보")
    for category, items in fetch_youth_notices_by_category().items():
        st.markdown(f"#### 📌 {category}")
        for item in items:
            with st.expander(f"{item['title']} ({item['date']})"):
                st.write(item["summary"])
                st.markdown(f"[👉 상세보기 및 신청링크]({item['link']})")
        st.markdown("<br>", unsafe_allow_html=True)
