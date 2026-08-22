import json
import os
from datetime import datetime
import google.generativeai as genai

# GitHub Secrets에서 API 키 로드
api_key = os.environ.get("GEMINI_API_KEY")
if not api_key:
    raise ValueError("GEMINI_API_KEY가 설정되지 않았습니다.")

genai.configure(api_key=api_key)

# 오늘 날짜 구하기
today_str = datetime.now().strftime("%Y-%m-%d")

# 안내된 최신 모델(gemini-3.6-flash)로 변경
model = genai.GenerativeModel('gemini-3.6-flash')
prompt = "오늘의 주요 트렌드 및 IT 뉴스를 알기 쉽게 핵심만 요약해줘."
response = model.generate_content(prompt)

# news_history.json 파일 업데이트
file_path = "news_history.json"
if os.path.exists(file_path):
    try:
        with open(file_path, "r", encoding="utf-8") as f:
            data = json.load(f)
    except Exception:
        data = {}
else:
    data = {}

data[today_str] = response.text

with open(file_path, "w", encoding="utf-8") as f:
    json.dump(data, f, ensure_ascii=False, indent=4)

print(f"[{today_str}] 뉴스 요약이 성공적으로 완료되었습니다.")
