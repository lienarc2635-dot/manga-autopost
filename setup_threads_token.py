#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Threads の「短期アクセストークン」を「長期アクセストークン（60日）」に変換し、
ユーザーIDと一緒に GitHub の Secrets に保存する初期設定用スクリプト。

依頼者がトークンをチャットやメールに貼らなくて済むように、
GitHub Actions の中だけで変換が完結するようにしています。

必要な Secrets:
  THREADS_APP_SECRET   … Meta のアプリのシークレット
  THREADS_SHORT_TOKEN  … 取得したばかりの短期トークン
  GH_PAT               … Secrets を書き込める個人アクセストークン

実行すると次の2つが自動で登録されます:
  THREADS_ACCESS_TOKEN
  THREADS_USER_ID
"""

import os
import sys

import requests

from refresh_threads_token import update_github_secret


def log(message: str) -> None:
    print(message, flush=True)


def exchange_for_long_lived(short_token: str, app_secret: str) -> tuple[str, int]:
    """短期トークンを長期トークン（60日）に変換する。"""
    res = requests.get(
        "https://graph.threads.net/access_token",
        params={
            "grant_type": "th_exchange_token",
            "client_secret": app_secret,
            "access_token": short_token,
        },
        timeout=60,
    )
    if res.status_code != 200:
        try:
            detail = res.json().get("error", {}).get("message", res.text[:300])
        except ValueError:
            detail = res.text[:300]
        raise RuntimeError(
            "長期トークンへの変換に失敗しました。\n"
            "  ・短期トークンが1時間で切れている（取り直してください）\n"
            "  ・アプリのシークレットが違う\n"
            "  のどちらかが原因です。\n"
            f"  元のメッセージ: {detail}"
        )

    body = res.json()
    return body["access_token"], int(body.get("expires_in", 0))


def fetch_user_id(token: str) -> tuple[str, str]:
    """自分の Threads ユーザーID と ユーザー名 を取得する。"""
    res = requests.get(
        "https://graph.threads.net/v1.0/me",
        params={"fields": "id,username", "access_token": token},
        timeout=60,
    )
    if res.status_code != 200:
        try:
            detail = res.json().get("error", {}).get("message", res.text[:300])
        except ValueError:
            detail = res.text[:300]
        raise RuntimeError(f"ユーザー情報の取得に失敗しました: {detail}")

    body = res.json()
    return str(body["id"]), str(body.get("username", "(不明)"))


def main() -> int:
    short_token = os.environ.get("THREADS_SHORT_TOKEN", "").strip()
    app_secret = os.environ.get("THREADS_APP_SECRET", "").strip()
    pat = os.environ.get("GH_PAT", "").strip()
    repo = os.environ.get("GITHUB_REPOSITORY", "").strip()

    missing = []
    if not short_token:
        missing.append("THREADS_SHORT_TOKEN")
    if not app_secret:
        missing.append("THREADS_APP_SECRET")
    if not pat:
        missing.append("GH_PAT")
    if missing:
        log("エラー: 次の Secrets が登録されていません → " + "、".join(missing))
        return 1

    log("1/3 短期トークンを長期トークンに変換しています…")
    long_token, expires_in = exchange_for_long_lived(short_token, app_secret)
    log(f"    変換できました。有効期間は約 {expires_in // 86400} 日です。")

    log("2/3 Threads のユーザーIDを取得しています…")
    user_id, username = fetch_user_id(long_token)
    log(f"    アカウント: @{username}")

    log("3/3 GitHub の Secrets に保存しています…")
    update_github_secret(repo, pat, "THREADS_ACCESS_TOKEN", long_token)
    update_github_secret(repo, pat, "THREADS_USER_ID", user_id)

    log("")
    log("完了しました。THREADS_ACCESS_TOKEN と THREADS_USER_ID が登録されました。")
    log("これ以降、トークンは毎週自動で延長されるので、手作業の更新は不要です。")
    log("")
    log("※ THREADS_SHORT_TOKEN はもう使いません。Secrets から削除して構いません。")
    return 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    except Exception as e:
        log(f"エラー: {e}")
        sys.exit(1)
