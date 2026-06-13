"""
v18_screener.py — V18シグナル 東証プライム全銘柄スクリーナー

V18 = KITRA - KNN（KNN除外版）
エントリー条件:
  週足: wma5 > wma20 かつ wma60 < wma20 かつ wma20上昇（前週確定）
  日足: MA5 > MA20 > MA60 かつ MA20上昇 かつ 陽線
  近接: 安値がMA20の2.5%以内 or MA5の1.5%以内
  フィルター: 出来高≥10万 かつ 株価≤5万円
"""

import sys
import os
import json
import unicodedata
import urllib.request
from pathlib import Path
from datetime import datetime, timedelta

import pandas as pd
import yfinance as yf
import pytz

from sector_heatmap import (
    aggregate_sector_history,
    load_jpx_sector_map,
    render_sector_heatmap,
    send_discord_image,
)

_JST = pytz.timezone("Asia/Tokyo")


def display_width(text: str) -> int:
    return sum(2 if unicodedata.east_asian_width(ch) in {"F", "W", "A"} else 1 for ch in str(text))


def fit_display(text: str, width: int, align: str = "<") -> str:
    text = str(text)
    clipped = ""
    used = 0
    for ch in text:
        ch_width = 2 if unicodedata.east_asian_width(ch) in {"F", "W", "A"} else 1
        if used + ch_width > width:
            break
        clipped += ch
        used += ch_width
    pad = " " * max(width - used, 0)
    return pad + clipped if align == ">" else clipped + pad

try:
    import gspread
    from google.oauth2.service_account import Credentials as SACredentials
    _GSPREAD_OK = True
except ImportError:
    _GSPREAD_OK = False

BASE_DIR     = Path(__file__).resolve().parent
DATA_DIR     = BASE_DIR / "data" / "storage"
DATA_DIR.mkdir(parents=True, exist_ok=True)

_obsidian_env = os.environ.get("OBSIDIAN_DIR", "")
OBSIDIAN_DIR = Path(_obsidian_env) if _obsidian_env else BASE_DIR / "output"
OBSIDIAN_DIR.mkdir(parents=True, exist_ok=True)

JPX_CACHE = DATA_DIR / "jpx_listing.xls"
JPX_URL   = (
    "https://www.jpx.co.jp/markets/statistics-equities/misc/"
    "tvdivq0000001vg2-att/data_j.xls"
)

# V18デフォルト設定（Pine Scriptと同値）
MIN_VOL     = 100_000
MAX_PRICE   = 50_000
MA_S        = 5
MA_M        = 20
MA_L        = 60
WMA_S       = 5
WMA_M       = 20
WMA_L       = 60
NEAR_M20_PCT = 2.5
NEAR_M5_PCT  = 1.5

CHUNK = 50   # yfinance 一括取得のバッチサイズ


# ── JPXリスト ────────────────────────────────────────────────────────────────

def get_prime_codes(refresh: bool = False) -> tuple[list[str], dict[str, str]]:
    if refresh or not JPX_CACHE.exists():
        print("[V18] JPX銘柄リスト取得中...")
        urllib.request.urlretrieve(JPX_URL, JPX_CACHE)

    df = pd.read_excel(JPX_CACHE, header=0)
    df.columns = [str(c).strip() for c in df.columns]
    mask = df["市場・商品区分"].str.contains("プライム", na=False)
    prime = df[mask].copy()
    codes = prime["コード"].astype(str).str.zfill(4).tolist()
    name_col = df.columns[2]  # 銘柄名
    names = dict(zip(prime["コード"].astype(str).str.zfill(4), prime[name_col].astype(str)))
    print(f"[V18] 東証プライム: {len(codes)}銘柄")
    return codes, names


# ── yfinanceバッチ取得 ───────────────────────────────────────────────────────

def fetch_batch(tickers: list[str], period: str, interval: str) -> pd.DataFrame:
    """複数ティッカーを一括ダウンロードしてMultiIndex DataFrameを返す"""
    raw = yf.download(
        tickers,
        period=period,
        interval=interval,
        group_by="ticker",
        auto_adjust=True,
        progress=False,
        threads=True,
    )
    return raw


def to_yf_ticker(code: str) -> str:
    return f"{code}.T"


# ── V18条件判定（1銘柄） ─────────────────────────────────────────────────────

def check_v18(daily: pd.DataFrame, weekly: pd.DataFrame) -> dict | None:
    """
    daily  : 日足 DataFrame（Close/Open/High/Low/Volume）
    weekly : 週足 DataFrame（Close）
    戻り値 : シグナルONの場合は詳細dict、OFFはNone
    """
    if daily is None or len(daily) < MA_L + 5:
        return None
    if weekly is None or len(weekly) < WMA_L + 5:
        return None

    # 日足MA
    d = daily.copy()
    d["ma5"]  = d["Close"].rolling(MA_S).mean()
    d["ma20"] = d["Close"].rolling(MA_M).mean()
    d["ma60"] = d["Close"].rolling(MA_L).mean()
    d["vol20"] = d["Volume"].rolling(20).mean()

    # 週足MA（前週確定 = 最終確定週バーの値）
    w = weekly.copy()
    w["wma5"]  = w["Close"].rolling(WMA_S).mean()
    w["wma20"] = w["Close"].rolling(WMA_M).mean()
    w["wma60"] = w["Close"].rolling(WMA_L).mean()

    # 日足の確定バー選択
    # 東証は15:30クローズ。市場開場中（JST 9:00-15:30）は今日の足が未確定
    jst = pytz.timezone("Asia/Tokyo")
    now = datetime.now(jst)
    market_open = (now.weekday() < 5) and (9 <= now.hour) and not (now.hour > 15 or (now.hour == 15 and now.minute >= 30))
    if market_open:
        # 市場開場中: 今日の足は未確定 → 前日確定足を使用
        row  = d.iloc[-2]
        prev = d.iloc[-3]
    else:
        # 市場クローズ後: 今日の足は確定済み
        row  = d.iloc[-1]
        prev = d.iloc[-2]

    # 週足は最後から2行目（前週確定）をV18の[1]とする
    if len(w) < 2:
        return None
    wrow  = w.iloc[-1]   # 今週（まだ確定していない可能性）
    wprev = w.iloc[-2]   # 前週確定 ← Pine Scriptの[1]に相当

    # 週足条件（前週確定データで判定）
    weekly_ok = (
        (wprev["wma5"]  > wprev["wma20"]) and
        (wprev["wma60"] < wprev["wma20"]) and
        (wprev["wma20"] > w.iloc[-3]["wma20"] if len(w) >= 3 else False)
    )
    if not weekly_ok:
        return None

    # 日足条件
    ma5  = row["ma5"]
    ma20 = row["ma20"]
    ma60 = row["ma60"]
    if pd.isna(ma5) or pd.isna(ma20) or pd.isna(ma60):
        return None

    is_perfect = (ma5 > ma20) and (ma20 > ma60)
    is_m_up    = ma20 > prev["ma20"]
    is_bull    = row["Close"] > row["Open"]
    filt_ok    = (row["vol20"] >= MIN_VOL) and (row["Close"] <= MAX_PRICE)

    dist_m = abs(row["Low"] - ma20) / ma20 * 100
    dist_s = abs(row["Low"] - ma5)  / ma5  * 100
    near_m20 = (row["Low"] > ma20) and (dist_m < NEAR_M20_PCT)
    near_m5  = (row["Low"] > ma5)  and (dist_s < NEAR_M5_PCT)

    sig_in = is_perfect and is_m_up and is_bull and filt_ok and (near_m20 or near_m5)

    if not sig_in:
        return None

    return {
        "close":   round(row["Close"], 0),
        "ma5":     round(ma5, 1),
        "ma20":    round(ma20, 1),
        "ma60":    round(ma60, 1),
        "dist_m":  round(dist_m, 2),
        "dist_s":  round(dist_s, 2),
        "near":    "MA20" if near_m20 else "MA5",
        "vol20":   int(row["vol20"]),
    }


# ── スクリーニング本体 ────────────────────────────────────────────────────────

def run_screener(refresh_jpx: bool = False) -> list[dict]:
    codes, name_map = get_prime_codes(refresh=refresh_jpx)
    tickers = [to_yf_ticker(c) for c in codes]

    results = []
    total = len(tickers)

    for start in range(0, total, CHUNK):
        chunk = tickers[start:start + CHUNK]
        chunk_codes = codes[start:start + CHUNK]
        print(f"  [{start+1}-{min(start+CHUNK, total)}/{total}] 取得中...")

        try:
            daily_all  = fetch_batch(chunk, period="1y",  interval="1d")
            weekly_all = fetch_batch(chunk, period="5y",  interval="1wk")
        except Exception as e:
            print(f"    [警告] 取得失敗: {e}")
            continue

        for code, ticker in zip(chunk_codes, chunk):
            try:
                # MultiIndex の場合
                if isinstance(daily_all.columns, pd.MultiIndex):
                    if ticker not in daily_all.columns.get_level_values(0):
                        continue
                    d = daily_all[ticker].dropna()
                    w = weekly_all[ticker].dropna()
                else:
                    # 単一銘柄の場合（チャンクサイズ1）
                    d = daily_all.dropna()
                    w = weekly_all.dropna()

                info = check_v18(d, w)
                if info:
                    info["code"]   = code
                    info["ticker"] = ticker
                    info["name"]   = name_map.get(code, "")
                    results.append(info)
                    print(f"    OK {code} {info['name'][:8]} close={info['close']} dist={info['dist_m']}%")

            except Exception as e:
                pass  # 個別銘柄のエラーは無視して続行

    return results


# ── Obsidian出力 ─────────────────────────────────────────────────────────────

def save_report(results: list[dict]) -> Path:
    today = datetime.now().strftime("%Y-%m-%d")
    path  = OBSIDIAN_DIR / f"{today}_v18_screener.md"

    lines = [
        f"# V18スクリーナー結果 {today}",
        f"実行日時: {datetime.now().strftime('%Y-%m-%d %H:%M')}",
        f"ヒット銘柄: {len(results)}件",
        "",
        "## エントリー候補",
        "",
    ]

    if results:
        lines += [
            "| コード | 終値 | MA5 | MA20 | MA60 | MA距離 | 近接 | 出来高(20均) |",
            "|--------|------|-----|------|------|--------|------|------------|",
        ]
        for r in sorted(results, key=lambda x: x["dist_m"]):
            lines.append(
                f"| [[{r['code']}]] | {r['close']:.0f} | {r['ma5']:.1f} | "
                f"{r['ma20']:.1f} | {r['ma60']:.1f} | {r['dist_m']:.2f}% | "
                f"{r['near']} | {r['vol20']:,} |"
            )
    else:
        lines.append("本日の候補なし")

    lines += [
        "",
        "## 条件（V18 = KITRA - KNN）",
        "- 週足: wMA5 > wMA20, wMA60 < wMA20, wMA20上昇（前週確定）",
        "- 日足: MA5 > MA20 > MA60, MA20上昇, 陽線",
        "- 近接: 安値がMA20の2.5%以内 or MA5の1.5%以内",
        "- フィルター: 出来高≥10万, 株価≤5万円",
    ]

    path.write_text("\n".join(lines), encoding="utf-8")
    print(f"[V18] レポート保存: {path}")
    return path


# ── Discord通知 ──────────────────────────────────────────────────────────────

def send_discord(webhook_url: str, results: list[dict]) -> None:
    _now     = datetime.now(_JST)
    today    = _now.strftime("%Y-%m-%d")
    run_time = _now.strftime("%H:%M JST")

    def _post(content: str) -> None:
        payload = json.dumps({"content": content}).encode("utf-8")
        req = urllib.request.Request(
            webhook_url, data=payload,
            headers={
                "Content-Type": "application/json",
                "User-Agent": "DiscordBot (https://github.com, 1.0)",
            },
        )
        urllib.request.urlopen(req, timeout=10)

    if not results:
        _post(f"**V18スクリーナー {today}**\n本日の候補なし")
        print("[V18] Discord通知送信完了")
        return

    sorted_results = sorted(results, key=lambda x: x["dist_m"])
    CHUNK_SIZE = 25
    chunks = [sorted_results[i:i + CHUNK_SIZE] for i in range(0, len(sorted_results), CHUNK_SIZE)]
    total = len(results)

    for idx, chunk in enumerate(chunks):
        header = (
            f"**V18スクリーナー {today} {run_time}** — **{total}銘柄**ヒット"
            if idx == 0
            else f"**V18スクリーナー {today}** ({idx + 1}/{len(chunks)})"
        )
        rows = [
            f"{'Code':<6} {'Close':>7} {'Dist':>6} {'Near':<4} Name",
            "-" * 47,
        ]
        for r in chunk:
            close_text = f"{r['close']:.0f}"
            dist_text = f"{r['dist_m']:.2f}%"
            rows.append(
                f"{r['code']:<6} "
                f"{close_text:>7} "
                f"{dist_text:>6} "
                f"{r['near']:<4} "
                f"{r.get('name', '')}"
            )
        _post("\n".join([header, "```", *rows, "```"]))

    print(f"[V18] Discord通知送信完了 ({len(chunks)}メッセージ)")


# ── Google Spreadsheet出力 ────────────────────────────────────────────────────

def save_to_gsheet(results: list[dict], spreadsheet_id: str) -> tuple[str, list[list[str]]]:
    """V18スクリーナー結果をGoogle Spreadsheetに書き込む。
    認証: 環境変数 GOOGLE_APPLICATION_CREDENTIALS にサービスアカウントJSONパスを指定。
    """
    if not _GSPREAD_OK:
        print("[V18] gspread未インストール。pip install gspread google-auth を実行してください。")
        return "", []

    creds_path = os.environ.get("GOOGLE_APPLICATION_CREDENTIALS", "")
    if not creds_path or not Path(creds_path).exists():
        print(f"[V18] GOOGLE_APPLICATION_CREDENTIALS が未設定または存在しません: {creds_path!r}")
        return "", []

    scopes = [
        "https://www.googleapis.com/auth/spreadsheets",
        "https://www.googleapis.com/auth/drive",
    ]
    creds = SACredentials.from_service_account_file(creds_path, scopes=scopes)
    gc = gspread.authorize(creds)
    sh = gc.open_by_key(spreadsheet_id)

    today    = datetime.now().strftime("%Y-%m-%d")
    run_time = datetime.now().strftime("%H:%M")

    headers = ["コード", "終値", "MA5", "MA20", "MA60", "MA距離(%)", "近接", "出来高(20均)"]

    data_rows = []
    for r in sorted(results, key=lambda x: x["dist_m"]):
        data_rows.append([
            r["code"],
            r["close"],
            r["ma5"],
            r["ma20"],
            r["ma60"],
            r["dist_m"],
            r["near"],
            r["vol20"],
        ])

    # ── 「最新」シート（常に上書き）──
    try:
        latest = sh.worksheet("最新")
        latest.clear()
    except gspread.exceptions.WorksheetNotFound:
        latest = sh.add_worksheet(title="最新", rows=300, cols=10)

    latest.update(
        [[f"V18スクリーナー {today} {run_time} 実行 / {len(results)}銘柄ヒット"]] +
        [headers] +
        (data_rows if data_rows else [["本日の候補なし"]]),
        value_input_option="USER_ENTERED",
    )

    # ── 「V18_履歴」シート（末尾追記）──
    hist_headers = ["日付", "実行時刻"] + headers
    try:
        hist = sh.worksheet("V18_履歴")
    except gspread.exceptions.WorksheetNotFound:
        hist = sh.add_worksheet(title="V18_履歴", rows=10000, cols=12)
        hist.append_row(hist_headers)

    hist_rows = [[today, run_time] + row for row in (data_rows if data_rows else [["本日の候補なし"]])]
    hist.append_rows(hist_rows, value_input_option="USER_ENTERED")
    history_values = hist.get_all_values()

    url = f"https://docs.google.com/spreadsheets/d/{spreadsheet_id}"
    print(f"[V18] Spreadsheet更新完了（最新+履歴）: {url}")
    return url, history_values


# ── メイン ───────────────────────────────────────────────────────────────────

def main():
    import argparse
    parser = argparse.ArgumentParser(description="V18スクリーナー")
    parser.add_argument("--refresh-jpx", action="store_true", help="JPXリストを再取得")
    parser.add_argument("--gsheet-id",      default="",  help="Google Spreadsheet ID（省略時はスキップ）")
    parser.add_argument("--discord-webhook", default="",  help="Discord Webhook URL（省略時はスキップ）")
    args = parser.parse_args()

    print(f"\n{'='*60}")
    print(f"V18 スクリーナー [東証プライム全銘柄]")
    print(f"実行日時: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    print(f"{'='*60}\n")

    # 月曜日は自動的にJPXリストをリフレッシュ
    auto_refresh = args.refresh_jpx or (datetime.now().weekday() == 0)
    results = run_screener(refresh_jpx=auto_refresh)
    path = save_report(results)

    history_rows = []
    if args.gsheet_id:
        _, history_rows = save_to_gsheet(results, args.gsheet_id)

    heatmap_path = None
    if history_rows:
        try:
            sector_map = load_jpx_sector_map(JPX_CACHE)
            heatmap = aggregate_sector_history(history_rows, sector_map)
            if heatmap.dates:
                heatmap_path = OBSIDIAN_DIR / f"{heatmap.dates[-1]}_v18_sector_heatmap.png"
                render_sector_heatmap(heatmap, heatmap_path)
                print(f"[V18] ヒートマップ生成完了: {heatmap_path}")
        except Exception as exc:
            print(f"[V18] ヒートマップ生成をスキップ: {exc}")

    webhook = args.discord_webhook or os.environ.get("DISCORD_WEBHOOK", "")
    if webhook:
        send_discord(webhook, results)
        if heatmap_path:
            try:
                send_discord_image(
                    webhook,
                    heatmap_path,
                    "**V18 業種シグナル・ヒートマップ（直近10営業日）**",
                )
            except Exception as exc:
                print(f"[V18] ヒートマップ投稿に失敗（一覧投稿は完了）: {exc}")

    print(f"\n完了: {len(results)}銘柄ヒット → {path}")
    return results


if __name__ == "__main__":
    main()
