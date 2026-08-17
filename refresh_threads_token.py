#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Threads の長期アクセストークン（60日で切れる）を自動で延長するスクリプト。

週に1回 GitHub Actions から実行され、
新しいトークンを GitHub の Secrets に上書き保存します。
依頼者が2ヶ月ごとに手作業で更新する必要はありません。

※ Secrets を書き換えるには、書き込み権限のある個人アクセストークン（GH_PAT）が必要です。
   GH_PAT が登録されていない場合は、延長だけ行って警告を出します。
"""

import base64
import os
import sys

import requests

try:
    from nacl import encoding, public
except ImportError:
    public = None


def log(message: str) -> None:
    print(message, flush=True)


def refresh_token(current_token: str) -> tuple[str, int]:
    """トークンを延長し、(新しいトークン, 残り秒数) を返す。"""
    res = requests.get(
        "https://graph.threads.net/refresh_access_token",
        params={"grant_type": "th_refresh_token", "access_token": current_token},
        timeout=60,
    )
    if res.status_code != 200:
        try:
            detail = res.json().get("error", {}).get("message", res.text[:300])
        except ValueError:
            detail = res.text[:300]
        raise RuntimeError(
            "Threadsのトークン延長に失敗しました。"
            "トークンが既に切れている可能性があります。"
            "Meta for Developers で長期トークンを取り直し、"
            "GitHub の Settings → Secrets → THREADS_ACCESS_TOKEN を更新してください。"
            f" / 元のメッセージ: {detail}"
        )

    body = res.json()
    return body["access_token"], int(body.get("expires_in", 0))


def update_github_secret(repo: str, pat: str, name: str, value: str) -> None:
    """GitHub の Secret を上書きする（値は公開鍵で暗号化して送る）。"""
    if public is None:
        raise RuntimeError("pynacl がインストールされていません（requirements.txt を確認）")

    headers = {
        "Authorization": f"Bearer {pat}",
        "Accept": "application/vnd.github+json",
        "X-GitHub-Api-Version": "2022-11-28",
    }

    key_res = requests.get(
        f"https://api.github.com/repos/{repo}/actions/secrets/public-key",
        headers=headers, timeout=30,
    )
    if key_res.status_code != 200:
        raise RuntimeError(
            "GitHub の公開鍵を取得できませんでした。"
            "GH_PAT の権限（Secrets: Read and write）を確認してください。"
            f" / HTTP {key_res.status_code}: {key_res.text[:200]}"
        )
    key_data = key_res.json()

    sealed_box = public.SealedBox(
        public.PublicKey(key_data["key"].encode("utf-8"), encoding.Base64Encoder())
    )
    encrypted = base64.b64encode(sealed_box.encrypt(value.encode("utf-8"))).decode("utf-8")

    put_res = requests.put(
        f"https://api.github.com/repos/{repo}/actions/secrets/{name}",
        headers=headers,
        json={"encrypted_value": encrypted, "key_id": key_data["key_id"]},
        timeout=30,
    )
    if put_res.status_code not in (201, 204):
        raise RuntimeError(
            f"Secret の更新に失敗しました / HTTP {put_res.status_code}: {put_res.text[:200]}"
        )


def main() -> int:
    current = os.environ.get("THREADS_ACCESS_TOKEN", "").strip()
    if not current:
        log("エラー: THREADS_ACCESS_TOKEN が設定されていません。")
        return 1

    new_token, expires_in = refresh_token(current)
    days = expires_in // 86400
    log(f"トークンを延長しました。次の期限まで約 {days} 日です。")

    repo = os.environ.get("GITHUB_REPOSITORY", "").strip()
    pat = os.environ.get("GH_PAT", "").strip()

    if not pat:
        log(
            "警告: GH_PAT が登録されていないため、新しいトークンを保存できませんでした。\n"
            "      このままだと約60日でトークンが切れて投稿が止まります。\n"
            "      README の「トークンの自動更新」の手順で GH_PAT を登録してください。"
        )
        return 1

    update_github_secret(repo, pat, "THREADS_ACCESS_TOKEN", new_token)
    log("新しいトークンを GitHub Secrets に保存しました。")
    return 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    except Exception as e:
        log(f"エラー: {e}")
        sys.exit(1)
