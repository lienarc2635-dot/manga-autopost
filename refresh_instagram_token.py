#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Instagram の長期アクセストークン（60日で切れる）を自動で延長するスクリプト。

refresh_threads_token.py と同じく、週に1回 GitHub Actions から実行され、
新しいトークンを GitHub の Secrets（INSTAGRAM_ACCESS_TOKEN）に上書き保存します。

※ Instagramのトークンは「発行から24時間以上たっていて、まだ切れていない」ときだけ延長できます。
   一度切れてしまうと延長できないので、Meta for Developers で取り直してください。
"""

import os
import sys

import requests

from refresh_threads_token import log, update_github_secret


def refresh_token(current_token: str) -> tuple[str, int]:
    """トークンを延長し、(新しいトークン, 残り秒数) を返す。"""
    res = requests.get(
        "https://graph.instagram.com/refresh_access_token",
        params={"grant_type": "ig_refresh_token", "access_token": current_token},
        timeout=60,
    )
    if res.status_code != 200:
        try:
            detail = res.json().get("error", {}).get("message", res.text[:300])
        except ValueError:
            detail = res.text[:300]
        raise RuntimeError(
            "Instagramのトークン延長に失敗しました。"
            "トークンが既に切れている可能性があります。"
            "Meta for Developers で Instagram のトークンを取り直し、"
            "GitHub の Settings → Secrets → INSTAGRAM_ACCESS_TOKEN を更新してください。"
            f" / 元のメッセージ: {detail}"
        )

    body = res.json()
    return body["access_token"], int(body.get("expires_in", 0))


def main() -> int:
    current = os.environ.get("INSTAGRAM_ACCESS_TOKEN", "").strip()
    if not current:
        log("INSTAGRAM_ACCESS_TOKEN が設定されていないため、Instagramの延長はスキップします。")
        return 0

    new_token, expires_in = refresh_token(current)
    days = expires_in // 86400
    log(f"Instagramのトークンを延長しました。次の期限まで約 {days} 日です。")

    repo = os.environ.get("GITHUB_REPOSITORY", "").strip()
    pat = os.environ.get("GH_PAT", "").strip()

    if not pat:
        log(
            "警告: GH_PAT が登録されていないため、新しいトークンを保存できませんでした。\n"
            "      このままだと約60日でトークンが切れて Instagram への投稿が止まります。"
        )
        return 1

    update_github_secret(repo, pat, "INSTAGRAM_ACCESS_TOKEN", new_token)
    log("新しいInstagramトークンを GitHub Secrets に保存しました。")
    return 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    except Exception as e:
        log(f"エラー: {e}")
        sys.exit(1)
