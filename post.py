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

JST = ZoneInfo("Asia/Tokyo") if ZoneInfo else None

# X の文字数上限。日本語は1文字=2としてカウントされ、上限は280（＝日本語140文字）
X_WEIGHTED_LIMIT = 280
# Threads の文字数上限
THREADS_LIMIT = 500

# Threads のメディアコンテナが準備できるまで待つ最大秒数
THREADS_CONTAINER_TIMEOUT = 90

# CSV のカラム名（依頼者が見てわかる日本語）
COL_DATE = "投稿日"
COL_IMAGE = "画像ファイル"
COL_X_TEXT = "X本文"
COL_TH_TEXT = "Threads本文"
COL_STATUS = "ステータス"
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


def already_posted(post_date: str, platform: str) -> bool:
    """その日・そのSNSに既に「成功」の記録があるか（二重投稿の防止）。"""
    for entry in read_log():
        if (entry.get("投稿日") == post_date
                and entry.get("プラットフォーム") == platform
                and entry.get("結果") == "成功"):
            return True
    return False


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


def post_to_threads(text: str, image_url: str) -> str:
    """Threads に画像付きで投稿し、投稿IDを返す。失敗したら PostError を投げる。"""
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
    log(f"  [Threads] メディアコンテナを作成中… image_url={image_url}")
    res = requests.post(
        f"{THREADS_API}/{user_id}/threads",
        data={
            "media_type": "IMAGE",
            "image_url": image_url,
            "text": text,
            "access_token": token,
        },
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


def post_to_x(text: str, image_path: Path) -> str:
    """X に画像付きで投稿し、投稿IDを返す。失敗したら PostError を投げる。"""
    auth = _x_auth()

    log("  [X] 画像をアップロード中…")
    media_id = _x_upload_media(image_path, auth)

    log("  [X] 投稿中…")
    res = requests.post(
        "https://api.x.com/2/tweets",
        auth=auth,
        json={"text": text, "media": {"media_ids": [media_id]}},
        timeout=60,
    )
    if res.status_code not in (200, 201):
        raise PostError(_x_error_message(res))

    return str(res.json().get("data", {}).get("id", ""))


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
    """images/01.png → https://.../images/01.png（ネットから見えるURL）に変換する。"""
    base = os.environ.get("IMAGE_BASE_URL", "").strip()
    if not base:
        raise PostError(
            "IMAGE_BASE_URL が設定されていません。"
            "GitHub Actions の設定（daily-post.yml）を確認してください。"
        )
    return base.rstrip("/") + "/" + image_rel.replace("\\", "/").lstrip("/")


# ---------------------------------------------------------------------------
# メイン処理
# ---------------------------------------------------------------------------

def main() -> int:
    parser = argparse.ArgumentParser(description="3コマ漫画を X と Threads に投稿します")
    parser.add_argument("--date", help="投稿する日付（例 2026-08-20）。省略時は今日（日本時間）")
    parser.add_argument("--dry-run", action="store_true",
                        help="実際には投稿せず、内容チェックだけ行う")
    parser.add_argument("--only", choices=["x", "threads"],
                        help="片方のSNSだけに投稿する（テスト用）")
    parser.add_argument("--validate-all", action="store_true",
                        help="posts.csv の全行をチェックする（投稿はしない）")
    args = parser.parse_args()

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
    targets = [
        (i, row) for i, row in enumerate(rows)
        if (row.get(COL_DATE) or "").strip() == target_date
        and (row.get(COL_STATUS) or "").strip() != "済"
    ]

    if not targets:
        # 「今日の分はない」は異常ではないので、正常終了する
        log("本日投稿する行はありませんでした。何もせず終了します。")
        return 0

    exit_code = 0

    for index, row in targets:
        image_rel = (row.get(COL_IMAGE) or "").strip()
        x_text = (row.get(COL_X_TEXT) or "").strip()
        th_text = (row.get(COL_TH_TEXT) or "").strip()
        image_path = BASE_DIR / image_rel

        log(f"\n▼ {target_date} / {image_rel}")

        problems = validate_row(row, index)
        if problems:
            for p in problems:
                log("  ✗ " + p)
            append_log(target_date, image_rel, "検証", False, error=" / ".join(problems))
            exit_code = 1
            continue

        if args.dry_run:
            log(f"  [確認のみ] X本文（{x_weighted_length(x_text) // 2}文字相当）: {x_text}")
            log(f"  [確認のみ] Threads本文（{len(th_text)}文字）: {th_text}")
            log(f"  [確認のみ] 画像URL: {build_image_url(image_rel)}")
            continue

        results = {}

        # X を使うかどうか。GitHub Actions の ENABLE_X で切り替えます。
        # （最初は Threads だけで運用し、あとから X を足せるようにしています）
        enable_x = os.environ.get("ENABLE_X", "false").strip().lower() in ("1", "true", "yes")
        want_threads = args.only in (None, "threads")
        want_x = args.only == "x" or (args.only is None and enable_x)

        if args.only is None and not enable_x:
            log("  [X] ENABLE_X が false のため、Xへの投稿はスキップします。")

        # --- Threads ------------------------------------------------------
        if want_threads:
            if already_posted(target_date, "Threads"):
                log("  [Threads] 既に投稿済みのためスキップします。")
                results["Threads"] = True
            else:
                try:
                    post_id = post_to_threads(th_text, build_image_url(image_rel))
                    log(f"  ✓ Threads 投稿成功 (id={post_id})")
                    append_log(target_date, image_rel, "Threads", True, post_id)
                    results["Threads"] = True
                except PostError as e:
                    log(f"  ✗ Threads 投稿失敗: {e}")
                    append_log(target_date, image_rel, "Threads", False, error=str(e))
                    results["Threads"] = False
                except Exception as e:  # 想定外のエラーでも X の投稿は続ける
                    log(f"  ✗ Threads 投稿失敗（想定外のエラー）: {e}")
                    append_log(target_date, image_rel, "Threads", False, error=repr(e))
                    results["Threads"] = False

        # --- X ------------------------------------------------------------
        # Threads が失敗しても X は投稿する（片方の失敗で全体を止めない）
        if want_x:
            if already_posted(target_date, "X"):
                log("  [X] 既に投稿済みのためスキップします。")
                results["X"] = True
            else:
                try:
                    post_id = post_to_x(x_text, image_path)
                    log(f"  ✓ X 投稿成功 (id={post_id})")
                    append_log(target_date, image_rel, "X", True, post_id)
                    results["X"] = True
                except PostError as e:
                    log(f"  ✗ X 投稿失敗: {e}")
                    append_log(target_date, image_rel, "X", False, error=str(e))
                    results["X"] = False
                except Exception as e:
                    log(f"  ✗ X 投稿失敗（想定外のエラー）: {e}")
                    append_log(target_date, image_rel, "X", False, error=repr(e))
                    results["X"] = False

        # --- ステータスを更新 ----------------------------------------------
        if all(results.values()):
            rows[index][COL_STATUS] = "済"
        elif any(results.values()):
            rows[index][COL_STATUS] = "一部失敗"
            exit_code = 1
        else:
            rows[index][COL_STATUS] = "失敗"
            exit_code = 1

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
