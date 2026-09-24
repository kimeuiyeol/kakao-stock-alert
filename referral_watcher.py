#!/usr/bin/env python3
"""
Claude 게스트 패스(claude.ai/referral/...) 신규 링크 감시 → 카톡 알림.

Reddit은 클라우드(데이터센터) IP를 403으로 막기 때문에 GitHub Actions가 아닌
개인 PC(가정/회사 IP)에서 실행해야 함.

감시 대상
  - Reddit r/ClaudeCode, r/ClaudeAI 새 글 + 새 댓글
  - claudecoworkcourse.com 게스트 패스 디렉터리
올라온 지 MAX_AGE_MIN분 이내 링크만 알림. 한 번 알린 링크는 seen 파일에 기록해 재알림 안 함.

실행
  python referral_watcher.py              # 콘솔 출력만 (카톡 env 없으면)
  python referral_watcher.py --open       # 새 링크를 브라우저로 바로 열기 (선착순 대응)
  python referral_watcher.py --once       # 1회만 확인하고 종료 (작업 스케줄러용)

카톡 알림(선택): 환경변수 KAKAO_REST_API_KEY, KAKAO_REFRESH_TOKEN 설정.
  ※ 매일 시황 알림(GitHub Secret)과 같은 refresh_token을 쓰면 토큰 회전 시
    한쪽이 끊길 수 있음 → reauth_kakao.py로 PC용 토큰을 따로 발급하고
    Secret 자동 교체는 'n' 선택 권장.
"""
import argparse
import json
import os
import re
import sys
import time
import webbrowser
from datetime import datetime
from pathlib import Path

import requests

SUBREDDITS = "ClaudeCode+ClaudeAI"
DIRECTORY_URL = "https://claudecoworkcourse.com/claude-guest-passes"
# Reddit API 규칙: 식별 가능한 User-Agent 필수
USER_AGENT = "windows:claude-referral-watcher:v1.0 (personal use)"

INTERVAL_SEC = 180   # 확인 주기 (3분)
MAX_AGE_MIN = 10     # 이 시간 이내에 올라온 링크만 알림

LINK_RE = re.compile(r"https?://claude\.ai/referral/[A-Za-z0-9_-]+")
SEEN_FILE = Path(__file__).with_name(".referral_seen.json")
TOKEN_FILE = Path(__file__).with_name(".kakao_refresh_token")

KAKAO_REST_API_KEY = os.environ.get("KAKAO_REST_API_KEY")


# ---------------------------------------------------------------- 수집

def get_json(url, **kw):
    res = requests.get(url, headers={"User-Agent": USER_AGENT}, timeout=20, **kw)
    res.raise_for_status()
    return res.json()


def fetch_reddit():
    """새 글 + 새 댓글에서 (링크, 올라온시각, 출처URL) 추출"""
    found = []
    for kind in ("new", "comments"):
        url = f"https://www.reddit.com/r/{SUBREDDITS}/{kind}.json?limit=100&raw_json=1"
        try:
            items = get_json(url)["data"]["children"]
        except Exception as e:
            print(f"  [reddit/{kind}] 실패: {e}")
            continue
        for c in items:
            d = c["data"]
            text = " ".join(d.get(k) or "" for k in ("title", "selftext", "url", "body"))
            for link in set(LINK_RE.findall(text)):
                found.append((link, d["created_utc"], "https://www.reddit.com" + d["permalink"]))
    return found


def fetch_directory():
    """디렉터리 페이지의 __NEXT_DATA__ JSON에서 활성 코드 추출"""
    try:
        html = requests.get(DIRECTORY_URL, headers={"User-Agent": USER_AGENT}, timeout=20).text
        m = re.search(r'<script id="__NEXT_DATA__"[^>]*>(.*?)</script>', html, re.S)
        codes = json.loads(m.group(1))["props"]["pageProps"]["codes"]
    except Exception as e:
        print(f"  [directory] 실패: {e}")
        return []
    found = []
    for c in codes:
        if c.get("directory_status") != "active":
            continue
        created = datetime.fromisoformat(c["created_at"]).timestamp()
        found.append((c["referral_url"], created, DIRECTORY_URL))
    return found


# ---------------------------------------------------------------- 카톡

def kakao_access_token():
    """PC용 refresh_token으로 access_token 발급. 회전되면 로컬 파일에 저장."""
    refresh = TOKEN_FILE.read_text().strip() if TOKEN_FILE.exists() else os.environ.get("KAKAO_REFRESH_TOKEN")
    if not (KAKAO_REST_API_KEY and refresh):
        return None
    res = requests.post("https://kauth.kakao.com/oauth/token", data={
        "grant_type": "refresh_token",
        "client_id": KAKAO_REST_API_KEY,
        "refresh_token": refresh,
    }, timeout=15)
    res.raise_for_status()
    tok = res.json()
    if "refresh_token" in tok:
        TOKEN_FILE.write_text(tok["refresh_token"])
        print("  [kakao] 새 refresh_token 로컬 저장")
    return tok["access_token"]


def send_kakao(link, age_min, source):
    try:
        access = kakao_access_token()
    except Exception as e:
        print(f"  [kakao] 토큰 갱신 실패: {e}")
        return
    if not access:
        return
    template = {
        "object_type": "text",
        "text": f"🎟 Claude 게스트 패스 ({age_min}분 전)\n{link}\n출처: {source}"[:200],
        "link": {"web_url": link, "mobile_web_url": link},
        "button_title": "바로 열기",
    }
    try:
        res = requests.post(
            "https://kapi.kakao.com/v2/api/talk/memo/default/send",
            headers={"Authorization": f"Bearer {access}"},
            data={"template_object": json.dumps(template)},
            timeout=15,
        )
        res.raise_for_status()
        print("  [kakao] 발송 완료")
    except Exception as e:
        print(f"  [kakao] 발송 실패: {e}")


# ---------------------------------------------------------------- 메인

def load_seen():
    try:
        return set(json.loads(SEEN_FILE.read_text()))
    except Exception:
        return set()


def check(seen, open_browser):
    now = time.time()
    new = []
    for link, created, source in fetch_reddit() + fetch_directory():
        age_min = int((now - created) // 60)
        if link in seen or age_min > MAX_AGE_MIN:
            continue
        seen.add(link)
        new.append((link, age_min, source))

    stamp = datetime.now().strftime("%H:%M:%S")
    if not new:
        print(f"[{stamp}] 신규 없음")
        return
    SEEN_FILE.write_text(json.dumps(sorted(seen)))
    for link, age_min, source in sorted(new, key=lambda x: x[1]):
        print(f"[{stamp}] 🎟 NEW ({age_min}분 전) {link}\n           출처: {source}")
        if open_browser:
            webbrowser.open(link)
        send_kakao(link, age_min, source)


def main():
    ap = argparse.ArgumentParser(description="Claude 게스트 패스 신규 링크 감시")
    ap.add_argument("--once", action="store_true", help="1회만 확인하고 종료")
    ap.add_argument("--open", action="store_true", help="새 링크를 브라우저로 자동 열기")
    args = ap.parse_args()

    if not KAKAO_REST_API_KEY:
        print("※ KAKAO_REST_API_KEY 없음 → 카톡 알림 없이 콘솔 출력만")
    seen = load_seen()
    while True:
        check(seen, args.open)
        if args.once:
            break
        time.sleep(INTERVAL_SEC)


if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        sys.exit(0)
