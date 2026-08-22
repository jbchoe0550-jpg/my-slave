import json
import os
from datetime import datetime
import google.generativeai as genai

# 1. API 키 설정 (GitHub Actions 환경변수에서 로드)
api_key = os.environ.get("GEMINI_API_KEY")
if not api_key:
    raise ValueError("GEMINI_API_KEY가 설정되지 않았습니다.")

genai.configure(api_key=api_key)

# 2. 오늘 날짜 구하기
today_str = datetime.now().strftime("%Y-%m-%d")

# 3. 뉴스 수집 및 Gemini 요약 진행 (기존 app.py의 요약 로직 활용)
def generate_news_summary():
    model = genai.GenerativeModel('gemini-1.5-flash')
    
    # 예시 프롬프트 (기존에 작성하신 프롬프트나 뉴스 수집 로직을 넣으시면 됩니다)
    prompt = "오늘의 주요 IT/기술 뉴스를 3줄로 요약해줘."
    response = model.generate_content(prompt)
    
    return response.text

# 4. 요약 실행
new_summary = generate_news_summary()

# 5. news_history.json 읽고 업데이트하기
file_path = "news_history.json"

# 기존 기록 불러오기 (파일이 없거나 비어있으면 빈 데이터로 시작)
if os.path.exists(file_path):
    try:
        with open(file_path, "r", encoding="utf-8") as f:
            data = json.load(f)
    except Exception:
        data = {}
else:
    data = {}

# 오늘 날짜 키에 요약본 저장
data[today_str] = new_summary

# 파일에 다시 저장
with open(file_path, "w", encoding="utf-8") as f:
    json.dump(data, f, ensure_ascii=False, indent=4)

print(f"[{today_str}] 뉴스 요약이 성공적으로 news_history.json에 기록되었습니다.")
