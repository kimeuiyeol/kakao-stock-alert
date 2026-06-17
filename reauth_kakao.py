#!/usr/bin/env python3
"""
카카오 refresh_token 재발급 헬퍼.

리프레시 토큰이 만료(약 60일)되면 알림이 안 옴. 이 스크립트로 새 토큰을
받아 GitHub Secret(KAKAO_REFRESH_TOKEN)을 교체하면 복구됨.

실행:  python3 reauth_kakao.py
필요:  카카오 REST API 키, 등록된 Redirect URI (카카오 디벨로퍼스 콘솔)
       gh CLI 로그인 (secret 자동 교체용, 선택)
"""
import json
import subprocess
import sys
import urllib.parse
import urllib.request
import webbrowser

AUTH_URL = "https://kauth.kakao.com/oauth/authorize"
TOKEN_URL = "https://kauth.kakao.com/oauth/token"


def post(url, data):
    body = urllib.parse.urlencode(data).encode()
    req = urllib.request.Request(url, data=body)
    try:
        with urllib.request.urlopen(req, timeout=15) as r:
            return json.load(r)
    except urllib.error.HTTPError as e:
        print("\n[에러] 카카오 응답:", e.read().decode())
        sys.exit(1)


def main():
    print("=== 카카오 refresh_token 재발급 ===\n")
    rest_key = input("1) 카카오 REST API 키: ").strip()
    redirect = input("2) 등록된 Redirect URI (예: https://localhost): ").strip() or "https://localhost"

    # 1단계: 인가 코드 받기 (브라우저 로그인)
    q = urllib.parse.urlencode({
        "client_id": rest_key,
        "redirect_uri": redirect,
        "response_type": "code",
        "scope": "talk_message",
    })
    auth = f"{AUTH_URL}?{q}"
    print("\n3) 아래 주소가 브라우저에서 열림. 카카오 로그인/동의하면")
    print(f"   '{redirect}/?code=XXXX' 로 이동됨. 그 code 값만 복사.\n   {auth}\n")
    try:
        webbrowser.open(auth)
    except Exception:
        pass

    code = input("4) 받은 code 값 붙여넣기: ").strip()

    # 2단계: 코드 → 토큰 교환
    tok = post(TOKEN_URL, {
        "grant_type": "authorization_code",
        "client_id": rest_key,
        "redirect_uri": redirect,
        "code": code,
    })
    refresh = tok.get("refresh_token")
    if not refresh:
        print("\n[에러] refresh_token 없음:", tok)
        sys.exit(1)

    print("\n✅ 새 refresh_token 발급됨.")
    print(f"   (유효기간 약 {tok.get('refresh_token_expires_in', 0)//86400}일)\n")

    # 3단계: GitHub Secret 교체 (gh 있으면 자동)
    ans = input("5) GitHub Secret(KAKAO_REFRESH_TOKEN) 자동 교체할까? [Y/n]: ").strip().lower()
    if ans in ("", "y", "yes"):
        try:
            subprocess.run(
                ["gh", "secret", "set", "KAKAO_REFRESH_TOKEN", "--body", refresh],
                check=True, cwd=sys.path[0] or ".",
            )
            print("✅ Secret 교체 완료. 이제 워크플로 수동 실행으로 확인:")
            print("   gh workflow run market-summary.yml")
        except Exception as e:
            print("[자동 교체 실패]", e)
            print("수동으로 GitHub → Settings → Secrets → KAKAO_REFRESH_TOKEN 에 아래 값 입력:")
            print(refresh)
    else:
        print("수동 교체용 값:")
        print(refresh)


if __name__ == "__main__":
    main()
