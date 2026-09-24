#!/usr/bin/env python3
"""
Claude 게스트 패스(claude.ai/referral/...) 신규 링크 감시 → 카톡 알림.

reddit.com은 클라우드 IP를 403으로 막지만 Arctic Shift(Reddit 아카이브) 경유라
클라우드·PC 어디서든 실행 가능.

감시 대상
  - Reddit r/ClaudeCode, r/ClaudeAI, r/Anthropic, r/claude 새 글 + 새 댓글 (Arctic Shift 경유)
  - claudecoworkcourse.com 게스트 패스 디렉터리
  - 아시아: 디시인사이드 클로드·AI활용 갤러리(韓), V2EX(中), Qiita(日)
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

SUBREDDITS = "ClaudeCode+ClaudeAI+Anthropic+claude"
DIRECTORY_URL = "https://claudecoworkcourse.com/claude-guest-passes"
# Reddit API 규칙: 식별 가능한 User-Agent 필수
USER_AGENT = "windows:claude-referral-watcher:v1.0 (personal use)"

INTERVAL_SEC = 180   # 확인 주기 (3분)
MAX_AGE_MIN = 10     # 이 시간 이내에 올라온 링크만 알림

LINK_RE = re.compile(r"claude\.ai/referral/[A-Za-z0-9_-]+")  # 스킴 없이 붙여넣는 경우 포함
BROWSER_UA = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
              "(KHTML, like Gecko) Chrome/128.0 Safari/537.36")
DC_GALLERIES = ("claude", "ai_utilize")  # 디시 마이너갤: 클로드(Claude), AI 활용
SEEN_FILE = Path(__file__).with_name(".referral_seen.json")
TOKEN_FILE = Path(__file__).with_name(".kakao_refresh_token")

KAKAO_REST_API_KEY = os.environ.get("KAKAO_REST_API_KEY")


# ---------------------------------------------------------------- 수집

def get_json(url, **kw):
    res = requests.get(url, headers={"User-Agent": USER_AGENT}, timeout=20, **kw)
    res.raise_for_status()
    return res.json()


def find_links(text):
    return {"https://" + m for m in LINK_RE.findall(text or "")}


def extract(d, found):
    text = " ".join(str(d.get(k) or "") for k in ("title", "selftext", "url", "body"))
    for link in find_links(text):
        found.append((link, d["created_utc"], "https://www.reddit.com" + d.get("permalink", "")))


def fetch_reddit():
    """새 글 + 새 댓글에서 (링크, 올라온시각, 출처URL) 추출.

    reddit.com 직접 조회는 데이터센터 IP에서 403 → Arctic Shift(Reddit 아카이브,
    수집 지연 1~5분)를 기본으로 쓰고, reddit.com은 PC 실행 시 보조로 시도.
    """
    found = []
    after = int(time.time()) - MAX_AGE_MIN * 60
    for sub in SUBREDDITS.split("+"):
        for kind in ("posts", "comments"):
            url = (f"https://arctic-shift.photon-reddit.com/api/{kind}/search"
                   f"?subreddit={sub}&after={after}&limit=100&sort=desc")
            try:
                for d in get_json(url).get("data") or []:
                    extract(d, found)
            except Exception as e:
                print(f"  [arctic/{sub}/{kind}] 실패: {e}")
            time.sleep(1)  # API 부하 배려
    for kind in ("new", "comments"):
        url = f"https://www.reddit.com/r/{SUBREDDITS}/{kind}.json?limit=100&raw_json=1"
        try:
            for c in get_json(url)["data"]["children"]:
                extract(c["data"], found)
        except Exception:
            pass  # 클라우드에선 403이 정상
    return found


def fetch_dcinside():
    """디시 갤러리 목록에서 MAX_AGE_MIN 이내 글만 본문 열어 링크 추출 (KST 기준 시각)"""
    found = []
    cutoff = time.time() - MAX_AGE_MIN * 60
    row_re = re.compile(r'gall_num">(\d+)</td>.*?gall_date" title="([^"]+)"', re.S)
    for gid in DC_GALLERIES:
        base = "https://gall.dcinside.com/mgallery/board"
        try:
            html = requests.get(f"{base}/lists/?id={gid}", headers={"User-Agent": BROWSER_UA}, timeout=20).text
        except Exception as e:
            print(f"  [dc/{gid}] 실패: {e}")
            continue
        for no, date in row_re.findall(html):
            created = datetime.strptime(date + " +0900", "%Y-%m-%d %H:%M:%S %z").timestamp()
            if created < cutoff:
                continue
            url = f"{base}/view/?id={gid}&no={no}"
            try:
                body = requests.get(url, headers={"User-Agent": BROWSER_UA}, timeout=20).text
            except Exception:
                continue
            for link in find_links(body):
                found.append((link, created, url))
            time.sleep(1)
    return found


def fetch_v2ex():
    """V2EX 최신 글(API) + sov2ex 본문·댓글 검색"""
    found = []
    try:
        for t in get_json("https://www.v2ex.com/api/topics/latest.json"):
            for link in find_links(t.get("title", "") + " " + t.get("content", "")):
                found.append((link, t["created"], t["url"]))
    except Exception as e:
        print(f"  [v2ex] 실패: {e}")
    gte = int(time.time()) - MAX_AGE_MIN * 60
    try:
        res = get_json("https://www.sov2ex.com/api/search?q=claude.ai%2Freferral"
                       f"&sort=created&order=0&size=20&gte={gte}")
        for h in res.get("hits", []):
            src = h["_source"]
            text = json.dumps(h.get("highlight", {})).replace("<em>", "").replace("</em>", "")
            created = datetime.fromisoformat(src["created"] + "+00:00").timestamp()
            for link in find_links(text):
                found.append((link, created, f"https://www.v2ex.com/t/{src['id']}"))
    except Exception as e:
        print(f"  [sov2ex] 실패: {e}")
    return found


def fetch_qiita():
    """Qiita 본문 검색 (비로그인 60회/시간 제한 → 3분 주기면 20회/시간)"""
    found = []
    try:
        for item in get_json("https://qiita.com/api/v2/items?query=claude.ai%2Freferral&per_page=20"):
            created = datetime.fromisoformat(item["created_at"]).timestamp()
            for link in find_links(item["body"]):
                found.append((link, created, item["url"]))
    except Exception as e:
        print(f"  [qiita] 실패: {e}")
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
    sources = fetch_reddit() + fetch_directory() + fetch_dcinside() + fetch_v2ex() + fetch_qiita()
    for link, created, source in sources:
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
