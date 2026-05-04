import os
import json
import requests
from datetime import datetime
from zoneinfo import ZoneInfo

ANTHROPIC_API_KEY = os.environ['ANTHROPIC_API_KEY']
KAKAO_REST_API_KEY = os.environ['KAKAO_REST_API_KEY']
KAKAO_REFRESH_TOKEN = os.environ['KAKAO_REFRESH_TOKEN']


def refresh_kakao_token():
    """Refresh Token으로 새 Access Token 발급"""
    url = "https://kauth.kakao.com/oauth/token"
    data = {
        "grant_type": "refresh_token",
        "client_id": KAKAO_REST_API_KEY,
        "refresh_token": KAKAO_REFRESH_TOKEN,
    }
    res = requests.post(url, data=data, timeout=15)
    res.raise_for_status()
    return res.json()


def get_market_summary():
    """Claude API로 미국 증시 요약 생성 (웹 검색 포함)"""
    now = datetime.now(ZoneInfo("Asia/Seoul"))
    date_str = now.strftime('%Y-%m-%d %H:%M')

    prompt = f"""지금은 한국시간 {date_str}이야.
가장 최근 거래일 기준 미국 증시 현황을 웹에서 검색해서 아래 형식으로 요약해줘.

📊 [날짜] 미국 증시 요약

[지수 등락]
- S&P 500: 등락률
- Nasdaq: 등락률
- Dow: 등락률

[주요 원인]
- 핵심 이유 2~3개

[경제 뉴스]
- 주요 이슈 2~3개

전체 분량 700자 이내. 이모지 최소화. 구체적 수치 포함."""

    url = "https://api.anthropic.com/v1/messages"
    headers = {
        "x-api-key": ANTHROPIC_API_KEY,
        "anthropic-version": "2023-06-01",
        "content-type": "application/json",
    }
    data = {
        "model": "claude-sonnet-4-5",
        "max_tokens": 2000,
        "tools": [{"type": "web_search_20250305", "name": "web_search", "max_uses": 5}],
        "messages": [{"role": "user", "content": prompt}],
    }
    res = requests.post(url, headers=headers, json=data, timeout=120)
    res.raise_for_status()
    result = res.json()

    parts = [b['text'] for b in result['content'] if b.get('type') == 'text']
    return '\n'.join(parts).strip()


def send_kakao_message(access_token, text):
    """카카오톡 나에게 메시지 보내기"""
    url = "https://kapi.kakao.com/v2/api/talk/memo/default/send"
    headers = {"Authorization": f"Bearer {access_token}"}

    # 카카오 텍스트 메시지는 최대 200자 제한 → 길면 분할
    chunks = [text[i:i+190] for i in range(0, len(text), 190)]

    for i, chunk in enumerate(chunks):
        template = {
            "object_type": "text",
            "text": chunk,
            "link": {"web_url": "https://finance.yahoo.com",
                     "mobile_web_url": "https://finance.yahoo.com"},
        }
        data = {"template_object": json.dumps(template)}
        res = requests.post(url, headers=headers, data=data, timeout=15)
        res.raise_for_status()
        print(f"[{i+1}/{len(chunks)}] 전송 완료")


def main():
    print("1️⃣ 카카오 토큰 갱신 중...")
    token_data = refresh_kakao_token()
    access_token = token_data['access_token']

    if 'refresh_token' in token_data:
        print("=" * 50)
        print("⚠️ NEW REFRESH TOKEN ISSUED")
        print(f"새 refresh_token: {token_data['refresh_token']}")
        print("→ GitHub Secrets의 KAKAO_REFRESH_TOKEN 값을 위 토큰으로 교체하세요")
        print("=" * 50)

    print("2️⃣ Claude로 증시 요약 생성 중...")
    summary = get_market_summary()
    print(f"--- 생성된 요약 ---\n{summary}\n--------------------")

    print("3️⃣ 카카오톡 발송 중...")
    send_kakao_message(access_token, summary)
    print("✅ 완료")


if __name__ == "__main__":
    main()
