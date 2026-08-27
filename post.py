#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
3コマ漫画を X と Threads に自動投稿するスクリプト。

やっていること（ざっくり）:
  1. posts.csv を読む
  2. 「今日の日付」の行を探す（なければ何もせず正常終了）
  3. Threads に投稿する
  4. X に投稿する
  5. 結果を logs/posted.csv に記録し、posts.csv のステータスを更新する

片方が失敗しても、もう片方は投稿します。
どちらかが失敗した場合は終了コード 1 で終わります
（GitHub Actions が「失敗」になり、メール通知が飛びます）。
"""

import argparse
import csv
import os
import sys
import time
import unicodedata
from datetime import datetime
from pathlib import Path

import requests
from requests_oauthlib import OAuth1

try:
    from zoneinfo import ZoneInfo
except ImportError:  # Python 3.8 以下は対象外だが念のため
    ZoneInfo = None

# ---------------------------------------------------------------------------
# 設定（ここの数字を変えれば挙動が変わります）
# ---------------------------------------------------------------------------

BASE_DIR = Path(__file__).resolve().parent
POSTS_CSV = BASE_DIR / "posts.csv"
LOG_CSV = BASE_DIR / "logs" / "posted.csv"
INSTAGRAM_CSV = BASE_DIR / "instagram.csv"
TEXT_POSTS_CSV = BASE_DIR / "text-posts.csv"

JST = ZoneInfo("Asia/Tokyo") if ZoneInfo else None

# X の文字数上限。日本語は1文字=2としてカウントされ、上限は280（＝日本語140文字）
X_WEIGHTED_LIMIT = 280
# Threads の文字数上限
THREADS_LIMIT = 500
# Instagram のキャプション上限
INSTAGRAM_CAPTION_LIMIT = 2200

# Threads のメディアコンテナが準備できるまで待つ最大秒数
THREADS_CONTAINER_TIMEOUT = 90

# CSV のカラム名（依頼者が見てわかる日本語）
COL_DATE = "投稿日"
COL_IMAGE = "画像ファイル"
COL_X_TEXT = "X本文"
COL_TH_TEXT = "Threads本文"
COL_STATUS = "ステータス"
COL_CAPTION = "キャプション"
COL_BODY = "本文"
CSV_COLUMNS = [COL_DATE, COL_IMAGE, COL_X_TEXT, COL_TH_TEXT, COL_STATUS]

LOG_COLUMNS = ["日時", "投稿日", "画像ファイル", "プラットフォーム", "結果", "投稿ID", "エラー内容"]


# ---------------------------------------------------------------------------
# 小さな道具
# ---------------------------------------------------------------------------

def log(message: str) -> None:
    """画面（GitHub Actions のログ）に出力する。"""
    print(message, flush=True)


def now_jst() -> datetime:
    return datetime.now(JST) if JST else datetime.now()


def x_weighted_length(text: str) -> int:
    """X の文字数カウント。全角（日本語・絵文字など）は2、半角は1で数える。"""
    total = 0
    for ch in text:
        if unicodedata.east_asian_width(ch) in ("F", "W", "A"):
            total += 2
        else:
            total += 1
    return total


class PostError(Exception):
    """投稿に失敗したときの例外。message は依頼者が読む日本語メッセージ。"""


# ---------------------------------------------------------------------------
# CSV の読み書き
# ---------------------------------------------------------------------------

def read_posts() -> list[dict]:
    if not POSTS_CSV.exists():
        raise PostError(f"posts.csv が見つかりません: {POSTS_CSV}")

    # utf-8-sig: Excel で保存した CSV の先頭にある見えない文字(BOM)も読めるようにする
    with POSTS_CSV.open("r", encoding="utf-8-sig", newline="") as f:
        rows = list(csv.DictReader(f))

    if not rows:
        return []

    missing = [c for c in CSV_COLUMNS if c not in rows[0]]
    if missing:
        raise PostError(
            "posts.csv の見出し行が違います。足りないカラム: " + "、".join(missing)
        )
    return rows


def write_posts(rows: list[dict]) -> None:
    with POSTS_CSV.open("w", encoding="utf-8-sig", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=CSV_COLUMNS)
        writer.writeheader()
        for row in rows:
            writer.writerow({c: row.get(c, "") for c in CSV_COLUMNS})


def read_log() -> list[dict]:
    if not LOG_CSV.exists():
        return []
    with LOG_CSV.open("r", encoding="utf-8-sig", newline="") as f:
        return list(csv.DictReader(f))


def append_log(post_date: str, image: str, platform: str, ok: bool,
               post_id: str = "", error: str = "") -> None:
    LOG_CSV.parent.mkdir(parents=True, exist_ok=True)
    is_new = not LOG_CSV.exists()
    with LOG_CSV.open("a", encoding="utf-8-sig", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=LOG_COLUMNS)
        if is_new:
            writer.writeheader()
        writer.writerow({
            "日時": now_jst().strftime("%Y-%m-%d %H:%M:%S"),
            "投稿日": post_date,
            "画像ファイル": image,
            "プラットフォーム": platform,
            "結果": "成功" if ok else "失敗",
            "投稿ID": post_id,
            "エラー内容": error,
        })


def posted_id(image_rel: str, platform: str) -> str:
    """その画像・そのSNSに既に投稿済みなら、その投稿IDを返す（未投稿なら空文字）。

    1日に複数枚を投稿するので、日付ではなく画像ファイル名で判定します。
    投稿IDを返すのは、途中まで投稿済みの日に再実行したとき、
    ツリーの続きを正しくぶら下げられるようにするためです。
    """
    for entry in read_log():
        if (entry.get("画像ファイル") == image_rel
                and entry.get("プラットフォーム") == platform
                and entry.get("結果") == "成功"):
            return (entry.get("投稿ID") or "").strip() or "投稿済み"
    return ""


def already_posted(image_rel: str, platform: str) -> bool:
    """その画像・そのSNSに既に「成功」の記録があるか（二重投稿の防止）。"""
    return bool(posted_id(image_rel, platform))


# ---------------------------------------------------------------------------
# Threads への投稿
# ---------------------------------------------------------------------------

THREADS_API = "https://graph.threads.net/v1.0"


def _threads_error_message(response: requests.Response) -> str:
    """Threads API のエラーを、依頼者が読んでわかる日本語にする。"""
    try:
        err = response.json().get("error", {})
    except ValueError:
        return f"HTTP {response.status_code}: {response.text[:300]}"

    code = err.get("code")
    subcode = err.get("error_subcode")
    detail = err.get("message", response.text[:300])

    if code == 190 or subcode in (463, 467):
        return (
            "Threadsのアクセストークンが切れました。再取得が必要です。"
            "（Meta for Developers で長期トークンを取り直し、"
            "GitHub の Settings → Secrets → THREADS_ACCESS_TOKEN を更新してください）"
            f" / 元のメッセージ: {detail}"
        )
    if code == 4 or code == 32:
        return f"Threadsの投稿回数の上限に達しました。時間をおいて再試行してください。 / {detail}"
    return f"Threadsのエラー (code={code}): {detail}"


def fetch_threads_user_id(token: str) -> str:
    """アクセストークンから自分のThreadsユーザーIDを取得する。

    THREADS_USER_ID を手で登録しなくて済むように、毎回APIで取ってきます。
    """
    res = requests.get(
        f"{THREADS_API}/me",
        params={"fields": "id,username", "access_token": token},
        timeout=30,
    )
    if res.status_code != 200:
        raise PostError(_threads_error_message(res))

    body = res.json()
    user_id = str(body.get("id", ""))
    if not user_id:
        raise PostError(f"ThreadsのユーザーIDを取得できませんでした: {res.text[:200]}")

    log(f"  [Threads] 投稿先アカウント: @{body.get('username', '(不明)')}")
    return user_id


def post_text_to_threads(text: str, reply_to_id: str = "") -> str:
    """Threads に「文章だけ」の投稿をする（画像なし）。

    夜のテキスト投稿で使います。画像の取り込み待ちがないぶん速く終わります。
    reply_to_id を渡すと、その投稿への返信として繋がります（ツリー投稿）。
    """
    token = os.environ.get("THREADS_ACCESS_TOKEN", "").strip()
    if not token:
        raise PostError(
            "Threadsの設定がありません。GitHub の Settings → Secrets に "
            "THREADS_ACCESS_TOKEN を登録してください。"
        )

    user_id = os.environ.get("THREADS_USER_ID", "").strip()
    if not user_id:
        user_id = fetch_threads_user_id(token)

    kind = "返信" if reply_to_id else "1つ目"
    log(f"  [Threads] テキスト投稿を作成中（{kind}）…")
    payload = {"media_type": "TEXT", "text": text, "access_token": token}
    if reply_to_id:
        payload["reply_to_id"] = reply_to_id

    res = requests.post(
        f"{THREADS_API}/{user_id}/threads",
        data=payload,
        timeout=60,
    )
    if res.status_code != 200:
        raise PostError(_threads_error_message(res))

    container_id = res.json().get("id")
    if not container_id:
        raise PostError(f"Threadsのコンテナ作成に失敗しました: {res.text[:300]}")

    # 画像がないので待ち時間は短くて済みますが、念のため少しだけ待ちます
    time.sleep(3)

    log("  [Threads] 公開中…")
    publish_res = requests.post(
        f"{THREADS_API}/{user_id}/threads_publish",
        data={"creation_id": container_id, "access_token": token},
        timeout=60,
    )
    if publish_res.status_code != 200:
        raise PostError(_threads_error_message(publish_res))

    return str(publish_res.json().get("id", ""))


def post_to_threads(text: str, image_url: str, reply_to_id: str = "") -> str:
    """Threads に画像付きで投稿し、投稿IDを返す。失敗したら PostError を投げる。

    reply_to_id を渡すと、その投稿への「返信」として投稿します。
    これを数珠つなぎにすることで、1日3枚のツリー投稿になります。
    """
    token = os.environ.get("THREADS_ACCESS_TOKEN", "").strip()
    if not token:
        raise PostError(
            "Threadsの設定がありません。GitHub の Settings → Secrets に "
            "THREADS_ACCESS_TOKEN を登録してください。"
        )

    # ユーザーIDは登録されていれば使い、なければトークンから自動取得する
    user_id = os.environ.get("THREADS_USER_ID", "").strip()
    if not user_id:
        user_id = fetch_threads_user_id(token)

    # --- ステップ1: メディアコンテナを作る -------------------------------
    kind = "返信" if reply_to_id else "1枚目"
    log(f"  [Threads] メディアコンテナを作成中（{kind}）… image_url={image_url}")
    payload = {
        "media_type": "IMAGE",
        "image_url": image_url,
        "text": text,
        "access_token": token,
    }
    if reply_to_id:
        payload["reply_to_id"] = reply_to_id

    res = requests.post(
        f"{THREADS_API}/{user_id}/threads",
        data=payload,
        timeout=60,
    )
    if res.status_code != 200:
        raise PostError(_threads_error_message(res))

    container_id = res.json().get("id")
    if not container_id:
        raise PostError(f"Threadsのコンテナ作成に失敗しました: {res.text[:300]}")

    # --- ステップ2: 画像の取り込みが終わるまで待つ -----------------------
    # Meta 側が image_url を取りに行くので、少し時間がかかります。
    deadline = time.time() + THREADS_CONTAINER_TIMEOUT
    while True:
        time.sleep(5)
        status_res = requests.get(
            f"{THREADS_API}/{container_id}",
            params={"fields": "status,error_message", "access_token": token},
            timeout=30,
        )
        if status_res.status_code != 200:
            raise PostError(_threads_error_message(status_res))

        info = status_res.json()
        status = info.get("status")
        if status == "FINISHED":
            break
        if status == "ERROR":
            raise PostError(
                "Threadsが画像を読み込めませんでした。"
                "画像URLがインターネットから見える状態か確認してください。"
                f" URL={image_url} / 詳細: {info.get('error_message')}"
            )
        if time.time() > deadline:
            raise PostError(
                f"Threadsの画像取り込みが{THREADS_CONTAINER_TIMEOUT}秒以内に終わりませんでした。"
                f" URL={image_url}"
            )
        log(f"  [Threads] 画像の取り込み待ち… (status={status})")

    # --- ステップ3: 公開する ---------------------------------------------
    log("  [Threads] 公開中…")
    publish_res = requests.post(
        f"{THREADS_API}/{user_id}/threads_publish",
        data={"creation_id": container_id, "access_token": token},
        timeout=60,
    )
    if publish_res.status_code != 200:
        raise PostError(_threads_error_message(publish_res))

    return str(publish_res.json().get("id", ""))


# ---------------------------------------------------------------------------
# X への投稿
# ---------------------------------------------------------------------------

def _x_auth() -> OAuth1:
    keys = {
        "X_API_KEY": os.environ.get("X_API_KEY", "").strip(),
        "X_API_SECRET": os.environ.get("X_API_SECRET", "").strip(),
        "X_ACCESS_TOKEN": os.environ.get("X_ACCESS_TOKEN", "").strip(),
        "X_ACCESS_TOKEN_SECRET": os.environ.get("X_ACCESS_TOKEN_SECRET", "").strip(),
    }
    missing = [k for k, v in keys.items() if not v]
    if missing:
        raise PostError(
            "Xの設定がありません。GitHub の Secrets に次を登録してください: "
            + "、".join(missing)
        )
    return OAuth1(
        keys["X_API_KEY"], keys["X_API_SECRET"],
        keys["X_ACCESS_TOKEN"], keys["X_ACCESS_TOKEN_SECRET"],
    )


def _x_error_message(response: requests.Response) -> str:
    """X API のエラーを日本語にする。"""
    try:
        body = response.json()
    except ValueError:
        body = {}
    detail = body.get("detail") or body.get("title") or response.text[:300]

    if response.status_code in (401, 403):
        return (
            "Xの認証に失敗しました。APIキー／アクセストークンが正しいか、"
            "アプリの権限が「Read and write」になっているか確認してください。"
            f" / 元のメッセージ: {detail}"
        )
    if response.status_code == 402:
        return (
            "Xの残高（クレジット）が足りません。X Developer Portal で"
            "クレジットを追加してください。"
            f" / 元のメッセージ: {detail}"
        )
    if response.status_code == 429:
        return f"Xの投稿回数の上限に達しました。時間をおいて再試行してください。 / {detail}"
    return f"Xのエラー (HTTP {response.status_code}): {detail}"


def _x_upload_media(image_path: Path, auth: OAuth1) -> str:
    """画像をアップロードして media_id を返す。v2 → 旧v1.1 の順に試す。"""
    endpoints = [
        "https://api.x.com/2/media/upload",
        "https://upload.twitter.com/1.1/media/upload.json",
    ]
    last_error = ""
    for url in endpoints:
        with image_path.open("rb") as f:
            res = requests.post(url, auth=auth, files={"media": f}, timeout=120)
        if res.status_code in (200, 201):
            body = res.json()
            media_id = (
                body.get("data", {}).get("id")
                or body.get("media_id_string")
                or body.get("id")
            )
            if media_id:
                return str(media_id)
            last_error = f"media_id が返りませんでした: {res.text[:200]}"
        else:
            last_error = _x_error_message(res)
            # 認証エラーや残高不足は、別のエンドポイントを試しても同じなので即中断
            if res.status_code in (401, 402, 403):
                raise PostError(last_error)
        log(f"  [X] {url} での画像アップロードに失敗。次を試します。")

    raise PostError(f"Xへの画像アップロードに失敗しました: {last_error}")


def post_to_x(text: str, image_path: Path, reply_to_id: str = "") -> str:
    """X に画像付きで投稿し、投稿IDを返す。失敗したら PostError を投げる。

    reply_to_id を渡すと、その投稿への返信（ツリー）として投稿します。
    """
    auth = _x_auth()

    log("  [X] 画像をアップロード中…")
    media_id = _x_upload_media(image_path, auth)

    log("  [X] 投稿中…")
    body = {"text": text, "media": {"media_ids": [media_id]}}
    if reply_to_id:
        body["reply"] = {"in_reply_to_tweet_id": reply_to_id}

    res = requests.post(
        "https://api.x.com/2/tweets",
        auth=auth,
        json=body,
        timeout=60,
    )
    if res.status_code not in (200, 201):
        raise PostError(_x_error_message(res))

    return str(res.json().get("data", {}).get("id", ""))


# ---------------------------------------------------------------------------
# Instagram への投稿
# ---------------------------------------------------------------------------

INSTAGRAM_API = "https://graph.instagram.com/v23.0"


def _instagram_error_message(response: requests.Response) -> str:
    """Instagram API のエラーを、依頼者が読んでわかる日本語にする。"""
    try:
        err = response.json().get("error", {})
    except ValueError:
        return f"HTTP {response.status_code}: {response.text[:300]}"

    code = err.get("code")
    detail = err.get("error_user_msg") or err.get("message", response.text[:300])

    if code == 190:
        return (
            "Instagramのアクセストークンが切れました。再取得が必要です。"
            "（Meta for Developers でトークンを取り直し、GitHub の Secrets → "
            "INSTAGRAM_ACCESS_TOKEN を更新してください）"
            f" / 元のメッセージ: {detail}"
        )
    if code == 4 or code == 9:
        return (
            "Instagramの1日の投稿上限（25件）に達しました。時間をおいて再試行してください。"
            f" / {detail}"
        )
    if code == 36003 or "aspect ratio" in str(detail).lower():
        return (
            "Instagramが画像の縦横比を受け付けませんでした。"
            "images_ig/ の画像（4:5に調整したもの）を使っているか確認してください。"
            f" / {detail}"
        )
    return f"Instagramのエラー (code={code}): {detail}"


def fetch_instagram_user_id(token: str) -> str:
    """アクセストークンから自分のInstagramユーザーIDを取得する。"""
    res = requests.get(
        f"{INSTAGRAM_API}/me",
        params={"fields": "user_id,username", "access_token": token},
        timeout=30,
    )
    if res.status_code != 200:
        raise PostError(_instagram_error_message(res))

    body = res.json()
    user_id = str(body.get("user_id") or body.get("id") or "")
    if not user_id:
        raise PostError(f"InstagramのユーザーIDを取得できませんでした: {res.text[:200]}")

    log(f"  [Instagram] 投稿先アカウント: @{body.get('username', '(不明)')}")
    return user_id


def _instagram_wait(container_id: str, token: str) -> None:
    """コンテナの準備が終わるまで待つ。"""
    deadline = time.time() + THREADS_CONTAINER_TIMEOUT
    while True:
        time.sleep(5)
        res = requests.get(
            f"{INSTAGRAM_API}/{container_id}",
            params={"fields": "status_code,status", "access_token": token},
            timeout=30,
        )
        if res.status_code != 200:
            raise PostError(_instagram_error_message(res))

        status = res.json().get("status_code")
        if status == "FINISHED":
            return
        if status == "ERROR":
            raise PostError(
                "Instagramが画像を読み込めませんでした。"
                f"詳細: {res.json().get('status')}"
            )
        if time.time() > deadline:
            raise PostError(
                f"Instagramの画像取り込みが{THREADS_CONTAINER_TIMEOUT}秒以内に終わりませんでした。"
            )
        log(f"  [Instagram] 画像の取り込み待ち… (status={status})")


def post_to_instagram(caption: str, image_urls: list[str]) -> str:
    """Instagram にカルーセル（複数枚を横スワイプ）で投稿し、投稿IDを返す。

    Threads のようなツリー返信はInstagramにないため、
    1日分の3枚を「1つのカルーセル投稿」にまとめます。
    """
    token = os.environ.get("INSTAGRAM_ACCESS_TOKEN", "").strip()
    if not token:
        raise PostError(
            "Instagramの設定がありません。GitHub の Settings → Secrets に "
            "INSTAGRAM_ACCESS_TOKEN を登録してください。"
        )

    user_id = os.environ.get("INSTAGRAM_USER_ID", "").strip()
    if not user_id:
        user_id = fetch_instagram_user_id(token)

    # 1枚だけならカルーセルにせず、普通の画像投稿にする
    if len(image_urls) == 1:
        log("  [Instagram] 画像1枚のため、通常の投稿として作成します。")
        res = requests.post(
            f"{INSTAGRAM_API}/{user_id}/media",
            data={"image_url": image_urls[0], "caption": caption, "access_token": token},
            timeout=60,
        )
        if res.status_code != 200:
            raise PostError(_instagram_error_message(res))
        container_id = res.json().get("id")
        _instagram_wait(container_id, token)
    else:
        # --- ステップ1: 1枚ずつ「カルーセルの部品」を作る -------------------
        children = []
        for i, url in enumerate(image_urls, start=1):
            log(f"  [Instagram] {i}枚目を準備中… {url}")
            res = requests.post(
                f"{INSTAGRAM_API}/{user_id}/media",
                data={
                    "image_url": url,
                    "is_carousel_item": "true",
                    "access_token": token,
                },
                timeout=60,
            )
            if res.status_code != 200:
                raise PostError(_instagram_error_message(res))
            child_id = res.json().get("id")
            if not child_id:
                raise PostError(f"Instagramの画像準備に失敗しました: {res.text[:300]}")
            _instagram_wait(child_id, token)
            children.append(str(child_id))

        # --- ステップ2: 部品をまとめてカルーセルにする ----------------------
        log(f"  [Instagram] {len(children)}枚をカルーセルにまとめています…")
        res = requests.post(
            f"{INSTAGRAM_API}/{user_id}/media",
            data={
                "media_type": "CAROUSEL",
                "children": ",".join(children),
                "caption": caption,
                "access_token": token,
            },
            timeout=60,
        )
        if res.status_code != 200:
            raise PostError(_instagram_error_message(res))
        container_id = res.json().get("id")
        if not container_id:
            raise PostError(f"Instagramのカルーセル作成に失敗しました: {res.text[:300]}")
        _instagram_wait(container_id, token)

    # --- ステップ3: 公開する -------------------------------------------------
    log("  [Instagram] 公開中…")
    pub = requests.post(
        f"{INSTAGRAM_API}/{user_id}/media_publish",
        data={"creation_id": container_id, "access_token": token},
        timeout=60,
    )
    if pub.status_code != 200:
        raise PostError(_instagram_error_message(pub))

    return str(pub.json().get("id", ""))


def build_instagram_caption(target_date: str, rows_for_day: list[dict]) -> str:
    """Instagramのキャプションを決める。

    instagram.csv にその日のキャプションがあればそれを使います。
    なければ、Threads本文を3枚分つないだものを使います（保険）。
    """
    if INSTAGRAM_CSV.exists():
        with INSTAGRAM_CSV.open("r", encoding="utf-8-sig", newline="") as f:
            for entry in csv.DictReader(f):
                if (entry.get(COL_DATE) or "").strip() == target_date:
                    caption = (entry.get(COL_CAPTION) or "").strip()
                    if caption:
                        if len(caption) > INSTAGRAM_CAPTION_LIMIT:
                            raise PostError(
                                f"Instagramのキャプションが長すぎます"
                                f"（{len(caption)}文字 / 上限{INSTAGRAM_CAPTION_LIMIT}文字）。"
                                f"instagram.csv の {target_date} の行を短くしてください。"
                            )
                        log("  [Instagram] instagram.csv のキャプションを使います。")
                        return caption

    log("  [Instagram] instagram.csv に該当行がないため、Threads本文をつないで使います。")
    parts = []
    for row in rows_for_day:
        text = (row.get(COL_TH_TEXT) or "").strip()
        if text:
            parts.append(text)
    return "\n\n────────\n\n".join(parts)


# ---------------------------------------------------------------------------
# 事前チェック
# ---------------------------------------------------------------------------

def validate_row(row: dict, index: int) -> list[str]:
    """1行分の内容をチェックして、問題点のリストを返す（空なら問題なし）。"""
    problems = []
    line = index + 2  # 見出し行のぶん +2

    image_rel = (row.get(COL_IMAGE) or "").strip()
    if not image_rel:
        problems.append(f"{line}行目: 画像ファイルが空です")
    elif not (BASE_DIR / image_rel).exists():
        problems.append(f"{line}行目: 画像が見つかりません → {image_rel}")

    x_text = (row.get(COL_X_TEXT) or "").strip()
    if not x_text:
        problems.append(f"{line}行目: X本文が空です")
    else:
        weighted = x_weighted_length(x_text)
        if weighted > X_WEIGHTED_LIMIT:
            problems.append(
                f"{line}行目: X本文が長すぎます"
                f"（日本語{weighted // 2}文字相当 / 上限140文字相当）"
            )

    th_text = (row.get(COL_TH_TEXT) or "").strip()
    if not th_text:
        problems.append(f"{line}行目: Threads本文が空です")
    elif len(th_text) > THREADS_LIMIT:
        problems.append(
            f"{line}行目: Threads本文が長すぎます（{len(th_text)}文字 / 上限{THREADS_LIMIT}文字）"
        )

    return problems


def build_image_url(image_rel: str) -> str:
    """images/1-1.jpg → https://.../images/1-1.jpg（ネットから見えるURL）に変換する。"""
    base = os.environ.get("IMAGE_BASE_URL", "").strip()
    if not base:
        raise PostError(
            "IMAGE_BASE_URL が設定されていません。"
            "GitHub Actions の設定（daily-post.yml）を確認してください。"
        )
    return base.rstrip("/") + "/" + image_rel.replace("\\", "/").lstrip("/")


def build_instagram_image_url(image_rel: str) -> str:
    """Instagram用の画像URLに変換する。

    Instagramは縦横比 4:5 までしか受け付けないので、
    左右に白い余白を足した images_ig/ の画像を使います。
    """
    ig_rel = image_rel.replace("\\", "/").lstrip("/")
    if ig_rel.startswith("images/"):
        ig_rel = "images_ig/" + ig_rel[len("images/"):]
    return build_image_url(ig_rel)


# ---------------------------------------------------------------------------
# 夜のテキスト投稿
# ---------------------------------------------------------------------------

def run_text_mode(args) -> int:
    """text-posts.csv から、その日の1本をテキストだけで投稿する。"""
    target_date = args.date or now_jst().strftime("%Y-%m-%d")
    log(f"■ 夜のテキスト投稿 / 対象日: {target_date}")

    if not TEXT_POSTS_CSV.exists():
        log("text-posts.csv がありません。何もせず終了します。")
        return 0

    with TEXT_POSTS_CSV.open("r", encoding="utf-8-sig", newline="") as f:
        rows = list(csv.DictReader(f))

    # その日の行をすべて集める（CSVに並んでいる順が、そのままツリーの順になります）
    targets = [row for row in rows if (row.get(COL_DATE) or "").strip() == target_date]

    if not targets:
        log("本日のテキスト投稿はありませんでした。何もせず終了します。")
        return 0

    log(f"　この日は {len(targets)} 本をツリー投稿します。")

    # --- 事前チェック（1本でもおかしければ、この日は投稿しない）-------------
    for i, row in enumerate(targets, start=1):
        text = (row.get(COL_BODY) or "").strip()
        if not text:
            log(f"エラー: {i}本目の本文が空です。")
            return 1
        if len(text) > THREADS_LIMIT:
            log(f"エラー: {i}本目が長すぎます（{len(text)}文字 / 上限{THREADS_LIMIT}文字）。")
            return 1

    if args.dry_run:
        for i, row in enumerate(targets, start=1):
            text = (row.get(COL_BODY) or "").strip()
            log(f"\n  [確認のみ] {i}本目（{len(text)}文字）")
            log(text)
        return 0

    # --- 1本目を投稿し、2本目以降はその返信としてぶら下げる -----------------
    parent_id = ""
    exit_code = 0

    for i, row in enumerate(targets, start=1):
        text = (row.get(COL_BODY) or "").strip()
        marker = f"text:{target_date}:{i}"

        log(f"\n▼ {target_date} / {i}本目（{len(text)}文字）")
        log(text)

        done_id = posted_id(marker, "Threads")
        if done_id:
            log("  既に投稿済みのためスキップします。")
            parent_id = done_id if done_id != "投稿済み" else parent_id
            continue

        try:
            post_id = post_text_to_threads(text, reply_to_id=parent_id)
            log(f"  ✓ Threads 投稿成功 (id={post_id})")
            append_log(target_date, marker, "Threads", True, post_id)
            parent_id = post_id
        except PostError as e:
            log(f"  ✗ Threads 投稿失敗: {e}")
            append_log(target_date, marker, "Threads", False, error=str(e))
            log("  ツリーが途切れるため、この日の残りは中止します。")
            exit_code = 1
            break
        except Exception as e:
            log(f"  ✗ Threads 投稿失敗（想定外のエラー）: {e}")
            append_log(target_date, marker, "Threads", False, error=repr(e))
            log("  ツリーが途切れるため、この日の残りは中止します。")
            exit_code = 1
            break

    return exit_code


# ---------------------------------------------------------------------------
# メイン処理
# ---------------------------------------------------------------------------

def main() -> int:
    parser = argparse.ArgumentParser(description="3コマ漫画を X と Threads に投稿します")
    parser.add_argument("--date", help="投稿する日付（例 2026-08-20）。省略時は今日（日本時間）")
    parser.add_argument("--dry-run", action="store_true",
                        help="実際には投稿せず、内容チェックだけ行う")
    parser.add_argument("--only", choices=["x", "threads", "instagram"],
                        help="片方のSNSだけに投稿する（テスト用）")
    parser.add_argument("--validate-all", action="store_true",
                        help="posts.csv の全行をチェックする（投稿はしない）")
    parser.add_argument("--mode", choices=["manga", "text"], default="manga",
                        help="manga=朝の漫画投稿（既定） / text=夜のテキスト投稿")
    args = parser.parse_args()

    # --- 夜のテキスト投稿モード --------------------------------------------
    if args.mode == "text":
        return run_text_mode(args)

    rows = read_posts()

    # --- 全行チェックモード ------------------------------------------------
    if args.validate_all:
        problems = []
        for i, row in enumerate(rows):
            problems += validate_row(row, i)
        if problems:
            log("posts.csv に問題が見つかりました:")
            for p in problems:
                log("  - " + p)
            return 1
        log(f"posts.csv は問題ありません（{len(rows)}行）。")
        return 0

    target_date = args.date or now_jst().strftime("%Y-%m-%d")
    log(f"■ 対象日: {target_date}（日本時間 {now_jst().strftime('%Y-%m-%d %H:%M')}）")

    # --- 今日の行を探す ----------------------------------------------------
    # ステータス列では絞り込みません。二重投稿の防止は logs/posted.csv を使って
    # SNSごとに判定しています（Threadsに投稿済みでも、Instagramにはこれから
    # 投稿する、という状況があるため）。
    targets = [
        (i, row) for i, row in enumerate(rows)
        if (row.get(COL_DATE) or "").strip() == target_date
    ]

    if not targets:
        # 「今日の分はない」は異常ではないので、正常終了する
        log("本日投稿する行はありませんでした。何もせず終了します。")
        return 0

    exit_code = 0
    log(f"　この日は {len(targets)} 枚をツリー投稿します。")

    # --- 事前チェック（1枚でもおかしければ、この日は投稿しない）-------------
    all_problems = []
    for index, row in targets:
        all_problems += validate_row(row, index)
    if all_problems:
        for p in all_problems:
            log("  ✗ " + p)
        append_log(target_date, "", "検証", False, error=" / ".join(all_problems))
        return 1

    # --- 確認のみモード ----------------------------------------------------
    if args.dry_run:
        for order, (index, row) in enumerate(targets, start=1):
            image_rel = (row.get(COL_IMAGE) or "").strip()
            th_text = (row.get(COL_TH_TEXT) or "").strip()
            log(f"\n  [確認のみ] {order}枚目 {image_rel}")
            log(f"    画像URL: {build_image_url(image_rel)}")
            log(f"    本文（{len(th_text)}文字）: {th_text}")
        return 0

    # X を使うかどうか。GitHub Actions の ENABLE_X で切り替えます。
    # （最初は Threads だけで運用し、あとから X を足せるようにしています）
    enable_x = os.environ.get("ENABLE_X", "false").strip().lower() in ("1", "true", "yes")
    want_threads = args.only in (None, "threads")
    want_x = args.only == "x" or (args.only is None and enable_x)

    if args.only is None and not enable_x:
        log("  [X] ENABLE_X が false のため、Xへの投稿はスキップします。")

    # --- Threads へツリー投稿 ----------------------------------------------
    # 1枚目を普通に投稿し、2枚目以降は「直前の投稿への返信」として繋げます。
    if want_threads:
        parent_id = ""
        for order, (index, row) in enumerate(targets, start=1):
            image_rel = (row.get(COL_IMAGE) or "").strip()
            th_text = (row.get(COL_TH_TEXT) or "").strip()

            log(f"\n▼ {target_date} / {order}枚目 / {image_rel}")

            done_id = posted_id(image_rel, "Threads")
            if done_id:
                log("  [Threads] 既に投稿済みのためスキップします。")
                rows[index][COL_STATUS] = "済"
                # 次の1枚が、この投稿にぶら下がるようにしておく
                parent_id = done_id if done_id != "投稿済み" else parent_id
                continue

            try:
                post_id = post_to_threads(
                    th_text, build_image_url(image_rel), reply_to_id=parent_id
                )
                log(f"  ✓ Threads 投稿成功 (id={post_id})")
                append_log(target_date, image_rel, "Threads", True, post_id)
                rows[index][COL_STATUS] = "済"
                parent_id = post_id  # 次の1枚をこの投稿にぶら下げる
            except PostError as e:
                log(f"  ✗ Threads 投稿失敗: {e}")
                append_log(target_date, image_rel, "Threads", False, error=str(e))
                rows[index][COL_STATUS] = "失敗"
                exit_code = 1
                log("  ツリーが途切れるため、この日の残りの投稿は中止します。")
                break
            except Exception as e:
                log(f"  ✗ Threads 投稿失敗（想定外のエラー）: {e}")
                append_log(target_date, image_rel, "Threads", False, error=repr(e))
                rows[index][COL_STATUS] = "失敗"
                exit_code = 1
                log("  ツリーが途切れるため、この日の残りの投稿は中止します。")
                break

    # --- Instagram へカルーセル投稿 -----------------------------------------
    # Instagramにはツリー返信がないので、3枚を1つの「横スワイプ投稿」にまとめます。
    # Threads が失敗しても Instagram は投稿します。
    enable_ig = os.environ.get("ENABLE_INSTAGRAM", "false").strip().lower() in ("1", "true", "yes")
    want_ig = args.only == "instagram" or (args.only is None and enable_ig)

    if args.only is None and not enable_ig:
        log("  [Instagram] ENABLE_INSTAGRAM が false のため、Instagramへの投稿はスキップします。")

    if want_ig:
        day_rows = [row for _, row in targets]
        images = [(row.get(COL_IMAGE) or "").strip() for row in day_rows]
        marker = "instagram:" + images[0]  # カルーセルは1投稿なので1枚目の名前で記録

        log(f"\n▼ [Instagram] {target_date} / {len(images)}枚のカルーセル")

        if already_posted(marker, "Instagram"):
            log("  [Instagram] 既に投稿済みのためスキップします。")
        else:
            try:
                post_id = post_to_instagram(
                    build_instagram_caption(target_date, day_rows),
                    [build_instagram_image_url(img) for img in images],
                )
                log(f"  ✓ Instagram 投稿成功 (id={post_id})")
                append_log(target_date, marker, "Instagram", True, post_id)
            except PostError as e:
                log(f"  ✗ Instagram 投稿失敗: {e}")
                append_log(target_date, marker, "Instagram", False, error=str(e))
                exit_code = 1
            except Exception as e:
                log(f"  ✗ Instagram 投稿失敗（想定外のエラー）: {e}")
                append_log(target_date, marker, "Instagram", False, error=repr(e))
                exit_code = 1

    # --- X へツリー投稿 -----------------------------------------------------
    # Threads が失敗しても X は投稿する（片方の失敗で全体を止めない）
    if want_x:
        parent_id = ""
        for order, (index, row) in enumerate(targets, start=1):
            image_rel = (row.get(COL_IMAGE) or "").strip()
            x_text = (row.get(COL_X_TEXT) or "").strip()
            image_path = BASE_DIR / image_rel

            log(f"\n▼ [X] {target_date} / {order}枚目 / {image_rel}")

            done_id = posted_id(image_rel, "X")
            if done_id:
                log("  [X] 既に投稿済みのためスキップします。")
                parent_id = done_id if done_id != "投稿済み" else parent_id
                continue

            try:
                post_id = post_to_x(x_text, image_path, reply_to_id=parent_id)
                log(f"  ✓ X 投稿成功 (id={post_id})")
                append_log(target_date, image_rel, "X", True, post_id)
                parent_id = post_id
            except PostError as e:
                log(f"  ✗ X 投稿失敗: {e}")
                append_log(target_date, image_rel, "X", False, error=str(e))
                exit_code = 1
                log("  ツリーが途切れるため、この日の残りの投稿は中止します。")
                break
            except Exception as e:
                log(f"  ✗ X 投稿失敗（想定外のエラー）: {e}")
                append_log(target_date, image_rel, "X", False, error=repr(e))
                exit_code = 1
                log("  ツリーが途切れるため、この日の残りの投稿は中止します。")
                break

    if not args.dry_run:
        write_posts(rows)

    if exit_code:
        log("\n■ 投稿に失敗したものがあります。上のログを確認してください。")
    else:
        log("\n■ すべて正常に完了しました。")
    return exit_code


if __name__ == "__main__":
    try:
        sys.exit(main())
    except PostError as e:
        log(f"エラー: {e}")
        sys.exit(1)
