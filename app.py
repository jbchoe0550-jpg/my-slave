import calendar
from datetime import datetime, timedelta
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
import json
import os
import re
import smtplib

from apscheduler.schedulers.background import BackgroundScheduler
from bs4 import BeautifulSoup
import google.generativeai as genai
import plotly.graph_objects as go
from plotly.subplots import make_subplots
import requests
import streamlit as st
import yfinance as yf

# =============================================================
# API 키 및 기본 설정
# =============================================================
GEMINI_API_KEY = st.secrets["GEMINI_API_KEY"]

SENDER_EMAIL = "your_email@gmail.com"
SENDER_PASSWORD = "your_app_password"

DEFAULT_NEWS_URLS = [
    "https://www.saveticker.com/news",
    "https://www.reuters.com",
]
URLS_FILE = "urls.txt"
HISTORY_FILE = "news_history.json"
CALENDAR_FILE = "calendar_data.json"
REPORTS_FILE = "reports_history.json"
WATCHLIST_FILE = "watchlist.json"

genai.configure(api_key=GEMINI_API_KEY)
model = genai.GenerativeModel("gemini-3.6-flash")

COLOR_PALETTE = [
    "#2563eb",
    "#16a34a",
    "#d97706",
    "#9333ea",
    "#0284c7",
    "#e11d48",
    "#0d9488",
]
ACADEMIC_COLOR = "#ea580c"  # 건국대 학사일정 전용 강조 색상


# =============================================================
# 데이터 저장 및 파일 입출력 헬퍼
# =============================================================
def init_files():
    for filepath, default_content in [
        (URLS_FILE, "\n".join(DEFAULT_NEWS_URLS)),
        (HISTORY_FILE, "{}"),
        (CALENDAR_FILE, "{}"),
        (REPORTS_FILE, "[]"),
        (WATCHLIST_FILE, '["TSLA", "NVDA", "AAPL", "005930.KS"]'),
    ]:
        if not os.path.exists(filepath):
            with open(filepath, "w", encoding="utf-8") as f:
                if isinstance(default_content, str) and (
                    default_content.startswith("{")
                    or default_content.startswith("[")
                ):
                    f.write(default_content)
                else:
                    f.write(default_content + "\n")


def load_json(filepath, default_val):
    if not os.path.exists(filepath):
        return default_val
    try:
        with open(filepath, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return default_val


def save_json(filepath, data):
    with open(filepath, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=4)


def load_urls():
    if not os.path.exists(URLS_FILE):
        return DEFAULT_NEWS_URLS.copy()
    with open(URLS_FILE, "r", encoding="utf-8") as f:
        lines = f.readlines()
    urls = [
        line.strip()
        for line in lines
        if line.strip() and not line.startswith("#")
    ]
    for default_url in DEFAULT_NEWS_URLS:
        if default_url not in urls:
            urls.append(default_url)
    return urls


# =============================================================
# 실시간 학사일정 웹 크롤링 (매월 자동 갱신)
# =============================================================
@st.cache_data(ttl=3600)
def fetch_academic_calendar(year, month):
    url = "https://www.konkuk.ac.kr/konkuk/2237/subview.do"
    headers = {
        "User-Agent": (
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"
        )
    }
    academic_events = {}
    try:
        res = requests.get(url, headers=headers, timeout=8)
        res.encoding = "utf-8"
        soup = BeautifulSoup(res.text, "html.parser")

        rows = soup.select("table.board-list tbody tr") or soup.select(
            ".schedule-list li"
        )
        for row in rows:
            date_cell = row.select_one(".date") or row.select_one("td:nth-child(1)")
            title_cell = row.select_one(".title") or row.select_one(
                "td:nth-child(2)"
            )

            if date_cell and title_cell:
                date_str = date_cell.get_text(strip=True)
                title = title_cell.get_text(strip=True)

                dates = re.findall(r"\d{4}\.\d{2}\.\d{2}", date_str)
                if not dates:
                    short_dates = re.findall(r"\d{2}\.\d{2}", date_str)
                    dates = [f"{year}.{d}" for d in short_dates]

                if dates:
                    start_date = dates[0].replace(".", "-")
                    end_date = dates[-1].replace(".", "-") if len(dates) > 1 else start_date

                    curr = datetime.strptime(start_date, "%Y-%m-%d")
                    end_dt = datetime.strptime(end_date, "%Y-%m-%d")
                    while curr <= end_dt:
                        d_key = curr.strftime("%Y-%m-%d")
                        if curr.year == year and curr.month == month:
                            academic_events[d_key] = title
                        curr += timedelta(days=1)
    except Exception:
        pass

    return academic_events


# =============================================================
# 학교 및 청년 공지 수집
# =============================================================
@st.cache_data(ttl=300)
def fetch_ku_notices_20(url, base_url):
    headers = {
        "User-Agent": (
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"
        )
    }
    notices = []
    try:
        res = requests.get(url, headers=headers, timeout=8)
        res.encoding = "utf-8"
        soup = BeautifulSoup(res.text, "html.parser")

        rows = (
            soup.select("table tbody tr")
            or soup.select(".board-list tr")
            or soup.select("ul.board-list li")
        )

        for row in rows:
            title_tag = (
                row.select_one(".td-subject a")
                or row.select_one(".subject a")
                or row.select_one("a")
            )
            date_tag = row.select_one(".td-date") or row.select_one(".date")

            if title_tag:
                title = title_tag.get_text(strip=True)
                link = title_tag.get("href", "")

                if link and not link.startswith("http"):
                    if link.startswith("/"):
                        link = base_url + link
                    else:
                        link = base_url + "/" + link
                elif not link:
                    link = url

                date = date_tag.get_text(strip=True) if date_tag else "2026.01.01"
                title = re.sub(
                    r"^(공지|필독|NEW|NOTICE)\s*", "", title, flags=re.IGNORECASE
                )

                if title and len(title) > 2:
                    summary = f"본 공지사항은 {title[:20]}... 관련 세부 안내 및 일정 내용입니다."
                    notices.append({
                        "title": title,
                        "link": link,
                        "date": date,
                        "summary": summary,
                    })

        notices.sort(key=lambda x: x["date"], reverse=True)
        return notices[:20]
    except Exception:
        return notices


@st.cache_data(ttl=600)
def fetch_youth_notices_by_category():
    return {
        "온통청년 (정부)": [
            {
                "title": "2026년 청년 월세 한시 특별지원 2차 신청 안내",
                "summary": "무주택 청년 대상 월 최대 20만 원씩 12개월간 임차료를 지원합니다.",
                "link": "https://www.youthcenter.go.kr",
                "date": "2026.08.18",
            },
            {
                "title": "2026 청년도약계좌 정부기여금 확대 지급 안내",
                "summary": "청년 자산 형성을 위한 만기 5년 적금 비과세 혜택 지원입니다.",
                "link": "https://www.youthcenter.go.kr",
                "date": "2026.08.15",
            },
        ],
        "청년몽땅정보통 (서울시)": [
            {
                "title": "서울시 청년 안심주택 입주자 모집 공고",
                "summary": "역세권 시세 대비 30~50% 수준으로 제공되는 저렴한 임대주택입니다.",
                "link": "https://youth.seoul.go.kr",
                "date": "2026.08.19",
            },
        ],
        "영등포구청": [
            {
                "title": "영등포구 청년 소상공인 무이자 융자 지원 사업",
                "summary": "관내 청년 창업가를 위한 맞춤형 금융 및 경영 컨설팅 지원책입니다.",
                "link": "https://www.ydp.go.kr",
                "date": "2026.08.16",
            },
        ],
        "서울시 공식 (Seoul Go)": [
            {
                "title": "K-패스 및 서울시 청년 대중교통비 환급 신청",
                "summary": "대중교통 이용 금액의 최대 30%를 마일리지로 적립/환급해 드립니다.",
                "link": "https://www.seoul.go.kr",
                "date": "2026.08.14",
            },
        ],
    }


# =============================================================
# 스케줄러 설정
# =============================================================
def fetch_and_summarize_all():
    urls = load_urls()
    today_date = datetime.now().strftime("%Y-%m-%d")
    now_time = datetime.now().strftime("%H:%M")
    summaries = []
    headers = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64)"}

    for url in urls:
        try:
            res = requests.get(url, headers=headers, timeout=12)
            soup = BeautifulSoup(res.text, "html.parser")
            for element in soup(["script", "style", "nav", "footer", "header"]):
                element.decompose()

            paragraphs = soup.find_all(["p", "article", "div", "span"])
            text_blocks = [
                p.get_text().strip()
                for p in paragraphs
                if len(p.get_text().strip()) > 15
            ]
            text = " ".join(text_blocks)[:4500]

            prompt = f"다음 웹사이트({url})에서 주요 속보를 요약해 주세요:\n{text}"
            response = model.generate_content(prompt)
            summaries.append(
                {"url": url, "summary": response.text, "created_at": now_time}
            )
        except Exception as e:
            summaries.append({
                "url": url,
                "summary": f"수집 오류: {str(e)}",
                "created_at": now_time,
            })

    history = load_json(HISTORY_FILE, {})
    if today_date not in history:
        history[today_date] = []
    history[today_date].extend(summaries)
    save_json(HISTORY_FILE, history)


@st.cache_resource
def start_scheduler():
    scheduler = BackgroundScheduler(timezone="Asia/Seoul")
    scheduler.add_job(
        fetch_and_summarize_all,
        "cron",
        hour=8,
        minute=20,
        id="daily_all_job",
    )
    scheduler.start()
    return scheduler


init_files()
start_scheduler()


# =============================================================
# Email API
# =============================================================
def send_email_smtp(to_email: str, subject: str, body: str):
    msg = MIMEMultipart()
    msg["From"] = SENDER_EMAIL
    msg["To"] = to_email
    msg["Subject"] = subject
    msg.attach(MIMEText(body, "plain", "utf-8"))
    with smtplib.SMTP_SSL("smtp.gmail.com", 465) as server:
        server.login(SENDER_EMAIL, SENDER_PASSWORD)
        server.send_message(msg)
    return True


# =============================================================
# Streamlit UI & 안전한 상단 여백 CSS
# =============================================================
st.set_page_config(
    page_title="개인 AI 업무 비서",
    layout="wide",
    initial_sidebar_state="expanded",
)

st.markdown(
    """
    <style>
    /* 상단 여백을 안전하게 최소화하되 잘리지 않도록 보정 */
    .block-container {
        padding-top: 2rem !important;
        padding-bottom: 1.5rem !important;
    }
    
    /* 메인 네비게이션 라디오 버튼 스타일링 강화 */
    div[data-testid="stRadio"] {
        background-color: #f8fafc;
        padding: 10px 16px;
        border-radius: 12px;
        border: 1px solid #e2e8f0;
        margin-bottom: 20px !important;
    }
    div[data-testid="stRadio"] div[role="radiogroup"] {
        gap: 15px;
    }
    div[data-testid="stRadio"] div[role="radiogroup"] label p {
        font-size: 19px !important;
        font-weight: 700 !important;
        color: #1e293b;
    }
    
    .sidebar-link-box {
        background-color: #ffffff;
        border: 1px solid #e2e8f0;
        border-radius: 6px;
        padding: 12px 14px;
        margin-bottom: 12px;
    }
    .sidebar-link-title {
        font-size: 15px;
        font-weight: bold;
        color: #1e293b;
        margin-bottom: 4px;
    }
    .sidebar-link-url {
        font-size: 13px;
        color: #2563eb;
        word-break: break-all;
    }
    .academic-badge {
        background-color: #fff7ed;
        border-left: 4px solid #ea580c;
        padding: 6px 10px;
        font-size: 14px;
        color: #c2410c;
        border-radius: 4px;
        margin-top: 6px;
        font-weight: 600;
    }
    .cal-day-cell {
        border: 1px solid #cbd5e1;
        border-radius: 8px;
        padding: 8px;
        min-height: 150px;
        background-color: #ffffff;
        display: flex;
        flex-direction: column;
    }
    .event-bar-slot {
        height: 24px;
        margin-top: 3px;
        margin-bottom: 3px;
    }
    .event-bar {
        color: white;
        font-size: 12px;
        font-weight: 600;
        padding: 3px 6px;
        height: 100%;
        white-space: nowrap;
        overflow: hidden;
        text-overflow: ellipsis;
        box-shadow: 0 1px 2px rgba(0,0,0,0.1);
    }
    .event-bar-single { border-radius: 4px; }
    .event-bar-start { border-top-left-radius: 4px; border-bottom-left-radius: 4px; margin-right: -9px; }
    .event-bar-middle { border-radius: 0px; margin-left: -9px; margin-right: -9px; }
    .event-bar-end { border-top-right-radius: 4px; border-bottom-right-radius: 4px; margin-left: -9px; }
    
    .notice-subtext {
        font-size: 13px;
        color: #64748b;
        margin-top: 2px;
        margin-bottom: 8px;
    }
    </style>
    """,
    unsafe_allow_html=True,
)

# 메인 네비게이션 메뉴 (명확하게 상단에 표시)
selected_tab = st.radio(
    "메인 메뉴 선택",
    [
        "캘린더",
        "뉴스 요약",
        "주식 분석",
        "학교 공지사항",
        "청년 혜택",
        "보고서",
        "이메일",
    ],
    horizontal=True,
    label_visibility="collapsed",
)


# -------------------------------------------------------------
# [탭 1] 캘린더
# -------------------------------------------------------------
if selected_tab == "캘린더":
    calendar_db = load_json(CALENDAR_FILE, {})
    today_dt = datetime.now()
    today_str = today_dt.strftime("%Y-%m-%d")
    tomorrow_str = (today_dt + timedelta(days=1)).strftime("%Y-%m-%d")

    st.sidebar.title("캘린더 탐색")
    selected_year = st.sidebar.number_input(
        "연도", min_value=2024, max_value=2030, value=today_dt.year
    )
    selected_month = st.sidebar.selectbox(
        "월 선택",
        list(range(1, 13)),
        index=today_dt.month - 1,
        format_func=lambda x: f"{x:02d}월",
    )

    academic_calendar = fetch_academic_calendar(selected_year, selected_month)

    user_cmd = st.text_input(
        "AI 일정 등록 (입력 후 Enter)",
        placeholder="예: 8월 21일부터 8월 23일까지 제주도 여행 추가해줘",
        key="quick_cmd_input",
    )

    if user_cmd:
        with st.spinner("AI 일정 처리 중..."):
            ai_parse_prompt = (
                f"오늘 날짜: {today_str}\n"
                f"사용자 명령: '{user_cmd}'\n\n"
                f"시작일과 종료일이 포함된 경우 start_date, end_date를 추출하세요.\n"
                f"JSON 형식 반환: ```json\n{{\"start_date\": \"YYYY-MM-DD\", \"end_date\": \"YYYY-MM-DD\", \"task\": \"내용\"}}\n```"
            )
            try:
                res_cmd = model.generate_content(ai_parse_prompt).text
                match = re.search(r"\{.*\}", res_cmd, re.DOTALL)
                if match:
                    parsed = json.loads(match.group())
                    s_dt = datetime.strptime(
                        parsed.get("start_date", today_str), "%Y-%m-%d"
                    )
                    e_dt = datetime.strptime(
                        parsed.get("end_date", parsed.get("start_date")),
                        "%Y-%m-%d",
                    )
                    p_task = parsed.get("task")

                    curr = s_dt
                    while curr <= e_dt:
                        d_str = curr.strftime("%Y-%m-%d")
                        if d_str not in calendar_db:
                            calendar_db[d_str] = []
                        calendar_db[d_str].append(
                            {"task": p_task, "done": False}
                        )
                        curr += timedelta(days=1)

                    save_json(CALENDAR_FILE, calendar_db)
                    st.success(
                        f"일정 등록 완료: '{p_task}' ({s_dt.strftime('%Y-%m-%d')} ~ {e_dt.strftime('%Y-%m-%d')})"
                    )
                    st.rerun()
            except Exception as e:
                st.error(f"명령 처리 실패: {e}")

    st.markdown("---")

    col_today, col_tomorrow = st.columns(2)

    def render_daily_panel(date_key, title):
        st.markdown(f"### {title} (`{date_key}`)")
        tasks = calendar_db.get(date_key, [])

        if tasks:
            for idx, item in enumerate(tasks):
                task_text = (
                    item if isinstance(item, str) else item.get("task", "")
                )
                is_done = (
                    False if isinstance(item, str) else item.get("done", False)
                )

                col_chk, col_del = st.columns([5, 1])
                display_label = f"~~{task_text}~~" if is_done else task_text

                checked = col_chk.checkbox(
                    display_label,
                    value=is_done,
                    key=f"dash_chk_{date_key}_{idx}",
                )
                if checked != is_done:
                    if isinstance(calendar_db[date_key][idx], str):
                        calendar_db[date_key][idx] = {
                            "task": task_text,
                            "done": checked,
                        }
                    else:
                        calendar_db[date_key][idx]["done"] = checked
                    save_json(CALENDAR_FILE, calendar_db)
                    st.rerun()

                if col_del.button("삭제", key=f"dash_del_{date_key}_{idx}"):
                    calendar_db[date_key].pop(idx)
                    save_json(CALENDAR_FILE, calendar_db)
                    st.rerun()
        else:
            st.caption("등록된 개인 일정이 없습니다.")

        if date_key in academic_calendar:
            st.markdown(
                f"""
                <div class="academic-badge">
                    🏫 <b>건국대 학사일정:</b> {academic_calendar[date_key]}
                </div>
                """,
                unsafe_allow_html=True,
            )

    with col_today:
        render_daily_panel(today_str, "오늘 할 일")
    with col_tomorrow:
        render_daily_panel(tomorrow_str, "내일 할 일")

    st.markdown("---")

    st.subheader(f"{selected_year}년 {selected_month}월 달력")

    month_prefix = f"{selected_year}-{selected_month:02d}"
    academic_titles = set(academic_calendar.values())

    all_month_tasks = list(
        dict.fromkeys([
            t.get("task", "") if isinstance(t, dict) else t
            for date_k, day_tasks in calendar_db.items()
            if date_k.startswith(month_prefix)
            for t in day_tasks
        ] + [
            v
            for date_k, v in academic_calendar.items()
            if date_k.startswith(month_prefix)
        ])
    )

    task_color_map = {}
    color_idx = 0
    for t in all_month_tasks:
        if t in academic_titles:
            task_color_map[t] = ACADEMIC_COLOR
        else:
            task_color_map[t] = COLOR_PALETTE[color_idx % len(COLOR_PALETTE)]
            color_idx += 1

    cal = calendar.monthcalendar(selected_year, selected_month)
    days = ["월", "화", "수", "목", "금", "토", "일"]

    cols_hdr = st.columns(7)
    for i, d in enumerate(days):
        cols_hdr[i].markdown(f"### **{d}**")

    for week in cal:
        w_cols = st.columns(7)
        for idx, day in enumerate(week):
            if day == 0:
                w_cols[idx].write(" ")
            else:
                date_str = f"{selected_year}-{selected_month:02d}-{day:02d}"
                prev_date_str = (
                    datetime.strptime(date_str, "%Y-%m-%d") - timedelta(days=1)
                ).strftime("%Y-%m-%d")
                next_date_str = (
                    datetime.strptime(date_str, "%Y-%m-%d") + timedelta(days=1)
                ).strftime("%Y-%m-%d")

                cell_html = f'<div class="cal-day-cell"><b>{day}일</b><br>'

                day_user_tasks = [
                    t if isinstance(t, str) else t.get("task", "")
                    for t in calendar_db.get(date_str, [])
                ]
                if date_str in academic_calendar:
                    day_user_tasks.append(academic_calendar[date_str])

                for slot_task in all_month_tasks:
                    cell_html += '<div class="event-bar-slot">'
                    if slot_task in day_user_tasks:
                        color = task_color_map.get(slot_task, "#2563eb")

                        has_prev = (
                            any(
                                (
                                    pt
                                    if isinstance(pt, str)
                                    else pt.get("task", "")
                                )
                                == slot_task
                                for pt in calendar_db.get(prev_date_str, [])
                            )
                            or academic_calendar.get(prev_date_str) == slot_task
                        )
                        has_next = (
                            any(
                                (
                                    nt
                                    if isinstance(nt, str)
                                    else nt.get("task", "")
                                )
                                == slot_task
                                for nt in calendar_db.get(next_date_str, [])
                            )
                            or academic_calendar.get(next_date_str) == slot_task
                        )

                        if has_prev and has_next and idx != 0 and idx != 6:
                            bar_class = "event-bar-middle"
                        elif (has_next or idx == 0) and not has_prev:
                            bar_class = (
                                "event-bar-start"
                                if has_next
                                else "event-bar-single"
                            )
                        elif (has_prev or idx == 6) and not has_next:
                            bar_class = (
                                "event-bar-end"
                                if has_prev
                                else "event-bar-single"
                            )
                        else:
                            bar_class = "event-bar-single"

                        prefix = "[학사] " if slot_task in academic_titles else ""
                        cell_html += f'<div class="event-bar {bar_class}" style="background-color: {color};">{prefix}{slot_task}</div>'
                    cell_html += "</div>"

                cell_html += "</div>"
                w_cols[idx].markdown(cell_html, unsafe_allow_html=True)


# -------------------------------------------------------------
# [탭 2] 뉴스 요약
# -------------------------------------------------------------
elif selected_tab == "뉴스 요약":
    st.sidebar.title("뉴스 & 리서치 보관함")
    history_data = load_json(HISTORY_FILE, {})

    if history_data:
        all_dates = sorted(list(history_data.keys()), reverse=True)
        selected_year = st.sidebar.selectbox(
            "연도 선택",
            sorted(
                list(set([d.split("-")[0] for d in all_dates])), reverse=True
            ),
        )
        selected_date = st.sidebar.selectbox(
            "날짜 선택", [d for d in all_dates if d.startswith(selected_year)]
        )
    else:
        selected_date = None

    today_date = datetime.now().strftime("%Y-%m-%d")

    if today_date in history_data and history_data[today_date]:
        for idx, item in enumerate(history_data[today_date], 1):
            with st.expander(f"기사/리포트 {idx}: {item['url']}", expanded=True):
                st.markdown(item["summary"])
    else:
        st.info(f"오늘({today_date}) 수집된 요약 데이터가 아직 없습니다.")


# -------------------------------------------------------------
# [탭 3] 주식 분석
# -------------------------------------------------------------
elif selected_tab == "주식 분석":
    st.subheader("시장 공포 & 변동성 지수 (VIX)")
    try:
        vix = yf.Ticker("^VIX")
        vix_hist = vix.history(period="6m")

        if not vix_hist.empty:
            vix_hist_clean = vix_hist.reset_index()
            vix_hist_clean["Date"] = vix_hist_clean["Date"].dt.tz_localize(None)

            vix_latest = vix_hist_clean["Close"].iloc[-1]
            vix_prev = vix_hist_clean["Close"].iloc[-2]
            vix_change = vix_latest - vix_prev

            col_vix1, col_vix2 = st.columns([1, 4])
            with col_vix1:
                st.metric(
                    "VIX 지수",
                    f"{vix_latest:.2f}",
                    f"{vix_change:+.2f}",
                    delta_color="inverse",
                )
            with col_vix2:
                fig_vix = go.Figure()
                fig_vix.add_trace(
                    go.Scatter(
                        x=vix_hist_clean["Date"],
                        y=vix_hist_clean["Close"],
                        mode="lines",
                        line=dict(color="#ef4444", width=2),
                    )
                )
                fig_vix.update_layout(height=220, margin=dict(l=10, r=10, t=10, b=10))
                st.plotly_chart(
                    fig_vix,
                    use_container_width=True,
                    config={"scrollZoom": False},
                )
    except Exception as e:
        st.error(f"VIX 오류: {e}")

    st.markdown("---")
    watchlist = load_json(WATCHLIST_FILE, ["TSLA", "NVDA", "AAPL", "005930.KS"])
    ticker_input = st.text_input(
        "분석할 주식 종목 티커 입력 (쉼표 구분)",
        value="TSLA, NVDA, AAPL",
        key="ticker_in",
    )

    if st.button("주가 및 밸류에이션 상세 분석"):
        tickers = [
            t.strip().upper() for t in ticker_input.split(",") if t.strip()
        ]
        for t in tickers:
            try:
                stock = yf.Ticker(t)
                info = stock.info
                st.markdown(f"### {t} 상세 분석")
                col_m1, col_m2 = st.columns(2)
                col_m1.metric("현재가", f"${info.get('currentPrice', 'N/A')}")
                col_m2.metric("Forward PER", f"{info.get('forwardPE', 'N/A')}")
            except Exception as e:
                st.error(f"{t} 처리 실패: {e}")


# -------------------------------------------------------------
# [탭 4] 학교 공지사항
# -------------------------------------------------------------
elif selected_tab == "학교 공지사항":
    ku_sites = [
        {
            "title": "건국대 학사공지",
            "url": "https://www.konkuk.ac.kr/konkuk/2238/subview.do",
            "base": "https://www.konkuk.ac.kr",
        },
        {
            "title": "건국대 일반공지",
            "url": "https://www.konkuk.ac.kr/kupa/10249/subview.do",
            "base": "https://www.konkuk.ac.kr",
        },
    ]
    st.sidebar.title("건국대학교 주요 링크")
    for site in ku_sites:
        st.sidebar.markdown(
            f'<div class="sidebar-link-box"><div class="sidebar-link-title">{site["title"]}</div><a href="{site["url"]}" target="_blank">{site["url"]}</a></div>',
            unsafe_allow_html=True,
        )

    tabs_ku = st.tabs([site["title"] for site in ku_sites])
    for tab, site in zip(tabs_ku, ku_sites):
        with tab:
            notices = fetch_ku_notices_20(site["url"], site["base"])
            for idx, notice in enumerate(notices, 1):
                st.markdown(
                    f"**{idx}. [{notice['title']}]({notice['link']})** ({notice['date']})"
                )


# -------------------------------------------------------------
# [탭 5] 청년 혜택 (사이드바 바로가기)
# -------------------------------------------------------------
elif selected_tab == "청년 혜택":
    youth_sites = [
        {"title": "온통청년 (정부 통합)", "url": "https://www.youthcenter.go.kr"},
        {"title": "청년몽땅정보통 (서울시)", "url": "https://youth.seoul.go.kr"},
        {"title": "영등포구청 청년정책", "url": "https://www.ydp.go.kr"},
        {"title": "Seoul Go (서울시 공식)", "url": "https://www.seoul.go.kr"},
    ]

    st.sidebar.title("청년 혜택 주요 사이트")
    for site in youth_sites:
        st.sidebar.markdown(
            f"""
            <div class="sidebar-link-box">
                <div class="sidebar-link-title">{site['title']}</div>
                <div class="sidebar-link-url"><a href="{site['url']}" target="_blank">{site['url']}</a></div>
            </div>
            """,
            unsafe_allow_html=True,
        )

    youth_data = fetch_youth_notices_by_category()
    tabs_youth = st.tabs(list(youth_data.keys()))
    for tab, cat_name in zip(tabs_youth, youth_data.keys()):
        with tab:
            for idx, item in enumerate(youth_data[cat_name], 1):
                st.markdown(
                    f"**{idx}. [{item['title']}]({item['link']})** - {item['summary']}"
                )


# -------------------------------------------------------------
# [탭 6] 보고서
# -------------------------------------------------------------
elif selected_tab == "보고서":
    report_title = st.text_input("보고서 제목", value="신규 분석 보고서")
    raw_text = st.text_area("기초 자료 입력", height=200)

    if st.button("보고서 생성하기"):
        if raw_text.strip():
            with st.spinner("생성 중..."):
                res = model.generate_content(
                    f"제목: {report_title}\n내용: {raw_text}\n보고서를 작성해 주세요."
                )
                st.markdown(res.text)


# -------------------------------------------------------------
# [탭 7] 이메일
# -------------------------------------------------------------
elif selected_tab == "이메일":
    recipient_email = st.text_input("수신자 이메일 주소")
    email_purpose = st.text_input("메일 주제")
    email_details = st.text_area("핵심 내용")

    if st.button("이메일 초안 작성"):
        if recipient_email and email_purpose:
            res = model.generate_content(
                f"수신: {recipient_email}\n주제: {email_purpose}\n내용: {email_details}\n정중한 이메일을 작성해 주세요."
            )
            st.text_area("작성된 초안", value=res.text, height=200)