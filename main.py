import os
import json
import time
import base64
import requests
import yfinance as yf
from datetime import datetime
from zoneinfo import ZoneInfo

GEMINI_API_KEY = os.environ['GEMINI_API_KEY']
KAKAO_REST_API_KEY = os.environ['KAKAO_REST_API_KEY']
KAKAO_REFRESH_TOKEN = os.environ['KAKAO_REFRESH_TOKEN']

# 토큰 자동 회전용 (없으면 비활성 → 기존처럼 새 토큰만 출력)
GH_PAT = os.environ.get('GH_PAT')
GH_REPO = os.environ.get('GITHUB_REPOSITORY')  # "owner/repo", Actions가 자동 주입


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


def update_github_secret(name, value):
    """새 refresh_token을 GitHub Secret에 다시 저장 (영구 회전).

    PAT(GH_PAT)와 GITHUB_REPOSITORY가 있을 때만 동작. libsodium sealed box로
    암호화 후 GitHub API로 PUT. 실패해도 발송은 계속되도록 예외를 삼킴.
    """
    if not (GH_PAT and GH_REPO):
        print("⚠️ GH_PAT/GITHUB_REPOSITORY 없음 → Secret 자동 회전 생략 (수동 교체 필요)")
        return False
    try:
        from nacl import encoding, public  # pynacl
        api = f"https://api.github.com/repos/{GH_REPO}/actions/secrets"
        headers = {
            "Authorization": f"Bearer {GH_PAT}",
            "Accept": "application/vnd.github+json",
        }
        # 1) 레포 공개키 조회
        pk = requests.get(f"{api}/public-key", headers=headers, timeout=15)
        pk.raise_for_status()
        pk = pk.json()
        # 2) sealed box 암호화
        sealed = public.SealedBox(
            public.PublicKey(pk["key"].encode(), encoding.Base64Encoder())
        )
        enc = base64.b64encode(sealed.encrypt(value.encode())).decode()
        # 3) Secret 업데이트
        put = requests.put(
            f"{api}/{name}",
            headers=headers,
            json={"encrypted_value": enc, "key_id": pk["key_id"]},
            timeout=15,
        )
        put.raise_for_status()
        print(f"✅ GitHub Secret '{name}' 자동 회전 완료 (HTTP {put.status_code})")
        return True
    except Exception as e:
        print(f"⚠️ Secret 자동 회전 실패: {e} → 수동 교체 필요")
        return False


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
        ("SPY", "SPY", "$"),
        ("QQQ", "QQQ", "$"),
        ("^IXIC", "Nasdaq", ""),
        ("^KS11", "코스피", ""),
        ("005930.KS", "삼성전자", "₩"),
        ("000660.KS", "SK하이닉스", "₩"),
        ("KRW=X", "USD/KRW", "₩"),
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

위 데이터 + Google 검색을 바탕으로 "왜 이렇게 움직였는지" 원인 중심으로 아래 형식 작성해줘.

[美 시장 원인]
- 어제 SPY/QQQ/Nasdaq 움직임의 핵심 원인 (지표/연준/실적/이슈 중 무엇이 결정적이었는지 2~3문장)
- 영향력 큰 빅테크 1~2개 동향 + 이유 (NVDA/AAPL/TSLA/META/MSFT 등)

[韓 시장 원인 + 오늘 전망]
- 어제 코스피 마감 흐름 원인 (외인/기관 수급, 환율, 美 영향)
- 삼성전자/SK하이닉스 어제 움직임 원인 (반도체 업황/HBM/AI 수요 등)
- 美 영향 받아 오늘 한국 시장 예상 흐름 1~2문장

[오늘 주의점]
- 오늘~내일 주요 일정 (실적/지표/연준 이벤트) 1~2개
- 환율(USD/KRW) 흐름이 주는 시사점 1문장

지침:
- 문체: "~함", "~음" 개조식. "~습니다" 절대 금지
- 마크다운 굵게 (**, __) 사용 금지. 일반 텍스트만
- 추측 금지, 검색 결과 기반
- 데이터 없으면 "확인 불가"
- 전체 500~700자
- 이모지 최소화"""

    url = f"https://generativelanguage.googleapis.com/v1beta/models/gemini-2.5-flash:generateContent?key={GEMINI_API_KEY}"
    headers = {"Content-Type": "application/json"}
    data = {
        "contents": [{"parts": [{"text": prompt}]}],
        "tools": [{"google_search": {}}],
        "generationConfig": {
            "temperature": 0.3,
            "maxOutputTokens": 8000,
            "thinkingConfig": {"thinkingBudget": 0},
        },
    }

    # Gemini 5xx/타임아웃 대비 재시도
    last_err = None
    for attempt in range(1, 4):
        try:
            res = requests.post(url, headers=headers, json=data, timeout=180)
            if res.status_code >= 500:
                raise requests.HTTPError(f"{res.status_code} from Gemini", response=res)
            res.raise_for_status()
            break
        except (requests.HTTPError, requests.ConnectionError, requests.Timeout) as e:
            last_err = e
            wait = 10 * attempt
            print(f"[Gemini] {attempt}/3 실패: {e} → {wait}s 후 재시도")
            time.sleep(wait)
    else:
        raise RuntimeError(f"Gemini 3회 재시도 실패: {last_err}")

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

    report = f"""📊 [{date_str}] 美/韓 마켓

[美]
• SPY: {g('SPY')}
• QQQ: {g('QQQ')}
• Nasdaq: {g('Nasdaq')}

[韓]
• 코스피: {g('코스피')}
• 삼성전자: {g('삼성전자')}
• SK하이닉스: {g('SK하이닉스')}

[환율]
• USD/KRW: {g('USD/KRW')}

{analysis}"""
    return report


def send_kakao_message(access_token, text):
    """카카오톡 분할 발송 (한 줄 길어도 안전)"""
    url = "https://kapi.kakao.com/v2/api/talk/memo/default/send"
    headers = {"Authorization": f"Bearer {access_token}"}

    # 잔여 마크다운 강제 제거
    text = text.replace('**', '').replace('__', '')

    MAX = 165  # 라벨 [i/n]\n 공간 35자 여유
    chunks = []
    current = ""
    for line in text.split('\n'):
        # 한 줄이 MAX 넘으면 강제 분할
        while len(line) > MAX:
            if current:
                chunks.append(current)
                current = ""
            chunks.append(line[:MAX])
            line = line[MAX:]
        # 누적
        if len(current) + len(line) + 1 > MAX:
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
        # 안전 장치
        if len(chunk_with_idx) > 200:
            chunk_with_idx = chunk_with_idx[:200]
            print(f"⚠️ [{i}/{total}] 200자 초과 잘림")

        template = {
            "object_type": "text",
            "text": chunk_with_idx,
            "link": {"web_url": "https://finance.yahoo.com",
                     "mobile_web_url": "https://finance.yahoo.com"},
        }
        data = {"template_object": json.dumps(template)}

        # 일시적 5xx/타임아웃 대비 chunk 단위 재시도
        last_err = None
        for attempt in range(1, 4):
            try:
                res = requests.post(url, headers=headers, data=data, timeout=15)
                res.raise_for_status()
                break
            except (requests.HTTPError, requests.ConnectionError, requests.Timeout) as e:
                last_err = e
                wait = 3 * attempt
                print(f"[{i}/{total}] {attempt}/3 발송 실패: {e} → {wait}s 후 재시도")
                time.sleep(wait)
        else:
            raise RuntimeError(f"[{i}/{total}] 카카오 발송 3회 실패: {last_err}")

        print(f"[{i}/{total}] 전송 완료 ({len(chunk_with_idx)}자)")
        if i < total:
            time.sleep(1.5)


def main():
    print("1. 카카오 토큰 갱신")
    token_data = refresh_kakao_token()
    access_token = token_data['access_token']

    if 'refresh_token' in token_data:
        print("=" * 50)
        print("NEW REFRESH TOKEN ISSUED → 자동 회전 시도")
        if not update_github_secret("KAKAO_REFRESH_TOKEN", token_data['refresh_token']):
            print(f"새 refresh_token: {token_data['refresh_token']}")
            print("→ GitHub Secrets의 KAKAO_REFRESH_TOKEN 수동 교체 필요")
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
