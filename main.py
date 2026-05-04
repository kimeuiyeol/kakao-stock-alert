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
    """Claude API로 미국 증시 상세 요약 생성 (웹 검색 포함)"""
    now = datetime.now(ZoneInfo("Asia/Seoul"))
    date_str = now.strftime('%Y-%m-%d')

    prompt = f"""지금은 한국시간 {date_str} 오전 7시야. 미국 증시는 한국시간 새벽 5시(서머타임 4시)에 마감했어.
가장 최근 거래일 기준 미국 증시 현황을 웹에서 검색해서 아래 형식으로 자세하게 정리해줘.

📊 [{date_str}] 미국 증시 데일리 리포트
━━━━━━━━━━━━━━━━━━━━

[ETF 종가 / 전일 대비]
• SPY (S&P500): $종가 (±X.XX%)
• QQQ (나스닥100): $종가 (±X.XX%)
• QLD (나스닥100 2배): $종가 (±X.XX%)
• TQQQ (나스닥100 3배): $종가 (±X.XX%)

[주요 지수]
• S&P 500: 종가 / 등락률
• Nasdaq Composite: 종가 / 등락률
• Dow Jones: 종가 / 등락률
• Russell 2000: 종가 / 등락률
• VIX (변동성지수): 종가 / 등락률

[오늘의 핵심 이슈]
1. 가장 큰 시장 동인을 자세히 (3~5문장)
2. 두 번째 이슈 (2~3문장)
3. 세 번째 이슈 (2~3문장)

[섹터별 동향]
• 강세 섹터: 어떤 섹터가 왜 올랐는지
• 약세 섹터: 어떤 섹터가 왜 빠졌는지
• 주목할 개별 종목: 큰 움직임 보인 빅테크/주요 종목 2~3개

[주요 경제 지표 / 일정]
• 발표된 지표가 있으면 결과 + 시장 반응
• 다음 거래일 예정 지표/이벤트 (실적발표 포함)

[채권 / 환율 / 원자재]
• 미국 10년물 국채 금리
• 달러인덱스 (DXY)
• 원유 (WTI)
• 금
• 비트코인 (참고용)

[레버리지 ETF 투자자 코멘트]
- TQQQ/QLD 보유 관점에서 오늘 흐름 해석 (2~3문장)
- MDD 관점에서 주의할 점이 있다면 언급

━━━━━━━━━━━━━━━━━━━━

지침:
- 모든 수치는 구체적으로 (예: +1.23%, $543.21)
- 추측 금지, 검색 결과 기반으로만
- 검색이 안 되거나 데이터 없으면 "데이터 없음"이라고 표시
- 전체 분량 1500~2000자
- 이모지는 섹션 구분용으로만 사용"""

    url = "https://api.anthropic.com/v1/messages"
    headers = {
        "x-api-key": ANTHROPIC_API_KEY,
        "anthropic-version": "2023-06-01",
        "content-type": "application/json",
    }
    data = {
        "model": "claude-sonnet-4-5",
        "max_tokens": 4000,
        "tools": [{"type": "web_search_20250305", "name": "web_search", "max_uses": 8}],
        "messages": [{"role": "user", "content": prompt}],
    }
    res = requests.post(url, headers=headers, json=data, timeout=180)
    res.raise_for_status()
    result = res.json()

    parts = [b['text'] for b in result['content'] if b.get('type') == 'text']
    return '\n'.join(parts).strip()


def send_kakao_message(access_token, text):
    """카카오톡 나에게 메시지 보내기 (긴 메시지는 분할)"""
    url = "https://kapi.kakao.com/v2/api/talk/memo/default/send"
    headers = {"Authorization": f"Bearer {access_token}"}

    # 카카오 텍스트 메시지는 최대 200자 제한 → 분할
    # 자연스러운 분할을 위해 줄바꿈 단위로 자르기
    lines = text.split('\n')
    chunks = []
    current = ""
    for line in lines:
        if len(current) + len(line) + 1 > 190:
            if current:
                chunks.append(current)
            current = line
        else:
            current = current + '\n' + line if current else line
    if current:
        chunks.append(current)

    total = len(chunks)
    for i, chunk in enumerate(chunks, 1):
        # 분할 표시 추가
        if total > 1:
            chunk_with_idx = f"[{i}/{total}]\n{chunk}"
        else:
            chunk_with_idx = chunk

        template = {
            "object_type": "text",
            "text": chunk_with_idx[:200],
            "link": {"web_url": "https://finance.yahoo.com",
                     "mobile_web_url": "https://finance.yahoo.com"},
        }
        data = {"template_object": json.dumps(template)}
        res = requests.post(url, headers=headers, data=data, timeout=15)
        res.raise_for_status()
        print(f"[{i}/{total}] 전송 완료")


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

    print("2️⃣ Claude로 증시 상세 리포트 생성 중...")
    summary = get_market_summary()
    print(f"--- 생성된 리포트 ({len(summary)}자) ---\n{summary}\n--------------------")

    print("3️⃣ 카카오톡 발송 중...")
    send_kakao_message(access_token, summary)
    print("✅ 완료")


if __name__ == "__main__":
    main()
