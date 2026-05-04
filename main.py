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


def fmt_change(close, prev, currency="$"):
    """가격 + 등락률 포맷팅"""
    change_pct = (close - prev) / prev * 100
    sign = "+" if change_pct >= 0 else ""
    if currency == "₩":
        return f"₩{close:,.0f} ({sign}{change_pct:.2f}%)"
    return f"{currency}{close:,.2f} ({sign}{change_pct:.2f}%)"


def fetch_market_data():
    """yfinance로 미국/한국 시장 데이터 수집"""
    # (ticker, 표시이름, 통화)
    tickers = [
        # 미국 ETF
        ("SPY", "SPY", "$"),
        ("QQQ", "QQQ", "$"),
        ("QLD", "QLD", "$"),
        ("TQQQ", "TQQQ", "$"),
        # 미국 지수
        ("^GSPC", "S&P500", ""),
        ("^IXIC", "Nasdaq", ""),
        ("^DJI", "Dow", ""),
        ("^RUT", "Russell2000", ""),
        ("^VIX", "VIX", ""),
        # 채권/환율/원자재
        ("^TNX", "美10년물", ""),
        ("DX-Y.NYB", "DXY", ""),
        ("KRW=X", "USD/KRW", "₩"),
        ("CL=F", "WTI", "$"),
        ("GC=F", "금", "$"),
        ("BTC-USD", "BTC", "$"),
        # 한국 지수 (전일 종가)
        ("^KS11", "코스피", ""),
        ("^KQ11", "코스닥", ""),
        # 한국 종목 (전일 종가)
        ("005930.KS", "삼성전자", "₩"),
        ("000660.KS", "SK하이닉스", "₩"),
    ]

    results = {}
    for symbol, name, currency in tickers:
        try:
            t = yf.Ticker(symbol)
            hist = t.history(period="3d")
            if len(hist) < 2:
                results[name] = "데이터 없음"
                continue
            close = hist["Close"].iloc[-1]
            prev = hist["Close"].iloc[-2]

            if currency == "":
                # 지수/금리는 단순 숫자
                change_pct = (close - prev) / prev * 100
                sign = "+" if change_pct >= 0 else ""
                results[name] = f"{close:,.2f} ({sign}{change_pct:.2f}%)"
            else:
                results[name] = fmt_change(close, prev, currency)
        except Exception as e:
            results[name] = "조회 실패"
            print(f"[{symbol}] error: {e}")

    return results


def get_news_analysis(market_data):
    """Gemini로 뉴스/이슈 분석"""
    now = datetime.now(ZoneInfo("Asia/Seoul"))
    date_str = now.strftime('%Y-%m-%d')

    market_str = "\n".join([f"- {k}: {v}" for k, v in market_data.items()])

    prompt = f"""한국시간 {date_str} 오전 7시 기준 시장 데이터:

{market_str}

위 데이터 + Google 검색을 바탕으로 아래 형식 작성해줘.

[美 핵심 이슈]
1. 어제 미국 증시 최대 동인 (3~4문장)
2. 두 번째 이슈 (2~3문장)

[美 섹터/종목]
- 강세 섹터 + 이유
- 약세 섹터 + 이유
- 빅테크 큰 움직임 (NVDA/TSLA/AAPL 등 2~3개)

[韓 시장 전망]
- 어제 코스피/코스닥 마감 흐름 + 이유
- 삼성전자/SK하이닉스 동향 (반도체 업황 포함)
- 美 증시 영향 받아 오늘(개장일) 한국 시장 예상 흐름

[경제 지표 / 일정]
- 발표된 지표 + 시장 반응
- 다음 거래일 예정 이벤트 (실적/지표)

[레버리지 ETF 코멘트]
- TQQQ/QLD 보유자 관점 (2문장)
- MDD 관점 주의점 1문장

지침:
- 문체: "~함", "~음" 개조식. "~습니다" 절대 금지
- 추측 금지, 검색 결과 기반
- 데이터 없으면 "확인 불가"
- 전체 1000~1400자
- 이모지 최소화"""

    url = f"https://generativelanguage.googleapis.com/v1beta/models/gemini-2.5-flash:generateContent?key={GEMINI_API_KEY}"
    headers = {"Content-Type": "application/json"}
    data = {
        "contents": [{"parts": [{"text": prompt}]}],
        "tools": [{"google_search": {}}],
        "generationConfig": {"temperature": 0.3, "maxOutputTokens": 3500},
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


def build_full_report(md, analysis):
    """최종 리포트 조립"""
    now = datetime.now(ZoneInfo("Asia/Seoul"))
    date_str = now.strftime('%Y-%m-%d')

    g = lambda k: md.get(k, 'N/A')

    report = f"""📊 [{date_str}] 美/韓 증시 데일리 리포트

[美 ETF / 전일대비]
• SPY: {g('SPY')}
• QQQ: {g('QQQ')}
• QLD: {g('QLD')}
• TQQQ: {g('TQQQ')}

[美 지수]
• S&P500: {g('S&P500')}
• Nasdaq: {g('Nasdaq')}
• Dow: {g('Dow')}
• Russell2000: {g('Russell2000')}
• VIX: {g('VIX')}

[韓 시장 / 전일종가]
• 코스피: {g('코스피')}
• 코스닥: {g('코스닥')}
• 삼성전자: {g('삼성전자')}
• SK하이닉스: {g('SK하이닉스')}

[채권 / 환율 / 원자재]
• 美10년물: {g('美10년물')}
• DXY: {g('DXY')}
• USD/KRW: {g('USD/KRW')}
• WTI: {g('WTI')}
• 금: {g('금')}
• BTC: {g('BTC')}

{analysis}"""
    return report


def send_kakao_message(access_token, text):
    """카카오톡 분할 발송 (175자 안전선)"""
    url = "https://kapi.kakao.com/v2/api/talk/memo/default/send"
    headers = {"Authorization": f"Bearer {access_token}"}

    lines = text.split('\n')
    chunks = []
    current = ""
    for line in lines:
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

    print("2. yfinance로 가격 수집 (美 + 韓)")
    market_data = fetch_market_data()
    for k, v in market_data.items():
        print(f"  {k}: {v}")

    print("3. Gemini로 뉴스/전망 분석")
    analysis = get_news_analysis(market_data)

    print("4. 리포트 조립")
    full_report = build_full_report(market_data, analysis)
    print(f"--- 리포트 ({len(full_report)}자) ---\n{full_report}\n--------------------")

    print("5. 카톡 발송")
    send_kakao_message(access_token, full_report)
    print("완료")


if __name__ == "__main__":
    main()
