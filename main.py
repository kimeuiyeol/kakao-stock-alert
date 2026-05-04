import os
import json
import time
import requests
import yfinance as yf
from datetime import datetime
from zoneinfo import ZoneInfo

GEMINI_API_KEY = os.environ['GEMINI_API_KEY']
KAKAO_REST_API_KEY = os.environ['KAKAO_REST_API_KEY']
KAKAO_REFRESH_TOKEN = os.environ['KAKAO_REFRESH_TOKEN']


def refresh_kakao_token():
    url = "https://kauth.kakao.com/oauth/token"
    data = {
        "grant_type": "refresh_token",
        "client_id": KAKAO_REST_API_KEY,
        "refresh_token": KAKAO_REFRESH_TOKEN,
    }
    res = requests.post(url, data=data, timeout=15)
    res.raise_for_status()
    return res.json()


def fetch_market_data():
    """yfinance로 ETF/지수/원자재 가격 정확히 가져오기"""
    tickers = {
        # ETF
        "SPY": "SPY (S&P500)",
        "QQQ": "QQQ (나스닥100)",
        "QLD": "QLD (2배)",
        "TQQQ": "TQQQ (3배)",
        # 지수
        "^GSPC": "S&P 500",
        "^IXIC": "Nasdaq",
        "^DJI": "Dow Jones",
        "^RUT": "Russell 2000",
        "^VIX": "VIX",
        # 채권/환율/원자재
        "^TNX": "美10년물",
        "DX-Y.NYB": "DXY",
        "CL=F": "WTI",
        "GC=F": "금",
        "BTC-USD": "비트코인",
    }

    results = {}
    for symbol, name in tickers.items():
        try:
            t = yf.Ticker(symbol)
            hist = t.history(period="2d")
            if len(hist) < 2:
                results[name] = "데이터 없음"
                continue
            close = hist["Close"].iloc[-1]
            prev = hist["Close"].iloc[-2]
            change_pct = (close - prev) / prev * 100
            sign = "+" if change_pct >= 0 else ""
            results[name] = f"${close:,.2f} ({sign}{change_pct:.2f}%)"
        except Exception as e:
            results[name] = f"조회 실패"
            print(f"[{symbol}] error: {e}")

    return results


def get_news_analysis(market_data):
    """Gemini로 뉴스/이슈 분석 (가격 데이터는 미리 주입)"""
    now = datetime.now(ZoneInfo("Asia/Seoul"))
    date_str = now.strftime('%Y-%m-%d')

    market_str = "\n".join([f"- {k}: {v}" for k, v in market_data.items()])

    prompt = f"""한국시간 {date_str} 오전 7시 기준, 가장 최근 거래일 미국 증시 데이터:

{market_str}

위 데이터를 바탕으로 어제 미국 증시 마감 관련 뉴스를 Google에서 검색해서 아래 항목만 채워줘.

[오늘의 핵심 이슈]
1. 시장 최대 동인 (3~4문장)
2. 두 번째 이슈 (2~3문장)
3. 세 번째 이슈 (2~3문장)

[섹터별 동향]
- 강세 섹터 + 이유
- 약세 섹터 + 이유
- 주목 종목 2~3개 (NVDA/TSLA/AAPL 등 빅테크 큰 움직임)

[경제 지표 / 일정]
- 발표된 지표 + 시장 반응
- 다음 거래일 예정 지표/실적발표

[레버리지 ETF 코멘트]
- TQQQ/QLD 보유자 관점 해석 (2~3문장)
- MDD 관점 주의점 1문장

지침:
- 문체: "~함", "~음" 같은 개조식. "~습니다" 절대 금지
- 추측 금지, 검색 결과 기반
- 데이터 없으면 "확인 불가"
- 전체 800~1200자
- 이모지 최소화"""

    url = f"https://generativelanguage.googleapis.com/v1beta/models/gemini-2.5-flash:generateContent?key={GEMINI_API_KEY}"
    headers = {"Content-Type": "application/json"}
    data = {
        "contents": [{"parts": [{"text": prompt}]}],
        "tools": [{"google_search": {}}],
        "generationConfig": {"temperature": 0.3, "maxOutputTokens": 3000},
    }
    res = requests.post(url, headers=headers, json=data, timeout=180)
    res.raise_for_status()
    result = res.json()

    candidates = result.get('candidates', [])
    if not candidates:
        raise RuntimeError(f"Gemini 응답 없음: {result}")

    parts = candidates[0]['content']['parts']
    text_parts = [p['text'] for p in parts if 'text' in p]
    return '\n'.join(text_parts).strip()


def build_full_report(market_data, analysis):
    """최종 리포트 조립"""
    now = datetime.now(ZoneInfo("Asia/Seoul"))
    date_str = now.strftime('%Y-%m-%d')

    report = f"""📊 [{date_str}] 미국 증시 데일리 리포트

[ETF 종가 / 전일 대비]
• SPY: {market_data.get('SPY (S&P500)', 'N/A')}
• QQQ: {market_data.get('QQQ (나스닥100)', 'N/A')}
• QLD: {market_data.get('QLD (2배)', 'N/A')}
• TQQQ: {market_data.get('TQQQ (3배)', 'N/A')}

[주요 지수]
• S&P 500: {market_data.get('S&P 500', 'N/A')}
• Nasdaq: {market_data.get('Nasdaq', 'N/A')}
• Dow: {market_data.get('Dow Jones', 'N/A')}
• Russell 2000: {market_data.get('Russell 2000', 'N/A')}
• VIX: {market_data.get('VIX', 'N/A')}

[채권 / 환율 / 원자재]
• 美10년물: {market_data.get('美10년물', 'N/A')}
• DXY: {market_data.get('DXY', 'N/A')}
• WTI: {market_data.get('WTI', 'N/A')}
• 금: {market_data.get('금', 'N/A')}
• BTC: {market_data.get('비트코인', 'N/A')}

{analysis}"""
    return report


def send_kakao_message(access_token, text):
    """카카오톡 나에게 분할 발송 (180자 안전선)"""
    url = "https://kapi.kakao.com/v2/api/talk/memo/default/send"
    headers = {"Authorization": f"Bearer {access_token}"}

    lines = text.split('\n')
    chunks = []
    current = ""
    for line in lines:
        # [i/n] 라벨 + 줄바꿈 8자 정도 여유
        if len(current) + len(line) + 1 > 175:
            if current:
                chunks.append(current)
            current = line
        else:
            current = current + '\n' + line if current else line
    if current:
        chunks.append(current)

    total = len(chunks)
    for i, chunk in enumerate(chunks, 1):
        chunk_with_idx = f"[{i}/{total}]\n{chunk}" if total > 1 else chunk
        # 안전 자르기
        if len(chunk_with_idx) > 200:
            chunk_with_idx = chunk_with_idx[:200]

        template = {
            "object_type": "text",
            "text": chunk_with_idx,
            "link": {"web_url": "https://finance.yahoo.com",
                     "mobile_web_url": "https://finance.yahoo.com"},
        }
        data = {"template_object": json.dumps(template)}
        res = requests.post(url, headers=headers, data=data, timeout=15)
        res.raise_for_status()
        print(f"[{i}/{total}] 전송 완료")
        if i < total:
            time.sleep(1.5)


def main():
    print("1. 카카오 토큰 갱신")
    token_data = refresh_kakao_token()
    access_token = token_data['access_token']

    if 'refresh_token' in token_data:
        print("=" * 50)
        print("NEW REFRESH TOKEN ISSUED")
        print(f"새 refresh_token: {token_data['refresh_token']}")
        print("→ GitHub Secrets의 KAKAO_REFRESH_TOKEN 교체 필요")
        print("=" * 50)

    print("2. yfinance로 가격 데이터 수집")
    market_data = fetch_market_data()
    for k, v in market_data.items():
        print(f"  {k}: {v}")

    print("3. Gemini로 뉴스 분석 생성")
    analysis = get_news_analysis(market_data)

    print("4. 최종 리포트 조립")
    full_report = build_full_report(market_data, analysis)
    print(f"--- 리포트 ({len(full_report)}자) ---\n{full_report}\n--------------------")

    print("5. 카톡 발송")
    send_kakao_message(access_token, full_report)
    print("완료")


if __name__ == "__main__":
    main()
