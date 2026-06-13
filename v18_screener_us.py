"""
v18_screener_us.py - US V18 screener for MaaSwing US Watch.

Default universe is NASDAQ-100. Results can be posted to workspace-us
and #81maa-us-watch via `--post`.
"""

import argparse
import io
import json
import os
import sys
import urllib.request
from collections import Counter
from datetime import datetime, timezone, timedelta
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent
LOCAL_DEPS = BASE_DIR / ".deps"
if LOCAL_DEPS.exists():
    sys.path.insert(0, str(LOCAL_DEPS))

import pandas as pd
import yfinance as yf
from dotenv import load_dotenv

from sector_heatmap import (
    aggregate_sector_history,
    normalize_us_symbol,
    render_sector_heatmap,
    send_discord_image,
)

try:
    import gspread
    from google.oauth2.service_account import Credentials as SACredentials
    _GSPREAD_OK = True
except ImportError:
    _GSPREAD_OK = False


YF_CACHE_DIR = BASE_DIR / ".yf_cache"
YF_CACHE_DIR.mkdir(parents=True, exist_ok=True)
try:
    yf.set_tz_cache_location(str(YF_CACHE_DIR))
except AttributeError:
    pass

load_dotenv()
load_dotenv(Path(r"D:\60 Obsidian\10_operations\secrets\.env"))

JST = timezone(timedelta(hours=9))
OUTPUT_DIR = Path(os.getenv("US_WATCH_OUTPUT_DIR", BASE_DIR / "us_watch_output"))
OUTPUT_DIR.mkdir(parents=True, exist_ok=True)

MIN_VOL = 100_000
MAX_PRICE = 50_000
MA_S = 5
MA_M = 20
MA_L = 60
WMA_S = 5
WMA_M = 20
WMA_L = 60
NEAR_M20_PCT = 2.5
NEAR_M5_PCT = 1.5
CHUNK = 50

NASDAQ100_WIKI = "https://en.wikipedia.org/wiki/Nasdaq-100"
NASDAQ100_FILE = BASE_DIR / "nasdaq100.txt"
SP500_WIKI = "https://en.wikipedia.org/wiki/List_of_S%26P_500_companies"
SP500_FILE = BASE_DIR / "sp500.txt"
WORKSPACE_WEBHOOK_ENV = "DISCORD_WEBHOOK_WORKSPACE_US"
WORKSPACE_CHANNEL_ENV = "US_WORKSPACE_CHANNEL_ID"
WORKSPACE_CHANNEL_NAME = "workspace-us"
US_WATCH_WEBHOOK_ENV = "DISCORD_WEBHOOK_US_WATCH"
US_WATCH_CHANNEL_ENV = "US_WATCH_POST_CHANNEL_ID"
US_WATCH_CHANNEL_NAME = "81maa-us-watch"


FALLBACK_NASDAQ100 = {
    "AAPL": "Apple",
    "ADBE": "Adobe",
    "ADI": "Analog Devices",
    "ADP": "Automatic Data Processing",
    "ADSK": "Autodesk",
    "AEP": "American Electric Power",
    "AMD": "Advanced Micro Devices",
    "AMGN": "Amgen",
    "AMZN": "Amazon",
    "ANSS": "Ansys",
    "APP": "AppLovin",
    "ARM": "Arm Holdings",
    "ASML": "ASML Holding",
    "AVGO": "Broadcom",
    "AZN": "AstraZeneca",
    "BIIB": "Biogen",
    "BKNG": "Booking Holdings",
    "BKR": "Baker Hughes",
    "CCEP": "Coca-Cola Europacific Partners",
    "CDNS": "Cadence Design Systems",
    "CDW": "CDW",
    "CEG": "Constellation Energy",
    "CHTR": "Charter Communications",
    "CMCSA": "Comcast",
    "COST": "Costco Wholesale",
    "CPRT": "Copart",
    "CRWD": "CrowdStrike",
    "CSCO": "Cisco",
    "CSGP": "CoStar Group",
    "CSX": "CSX",
    "CTAS": "Cintas",
    "CTSH": "Cognizant",
    "DASH": "DoorDash",
    "DDOG": "Datadog",
    "DXCM": "DexCom",
    "EA": "Electronic Arts",
    "EXC": "Exelon",
    "FANG": "Diamondback Energy",
    "FAST": "Fastenal",
    "FTNT": "Fortinet",
    "GEHC": "GE HealthCare",
    "GFS": "GlobalFoundries",
    "GILD": "Gilead Sciences",
    "GOOG": "Alphabet Class C",
    "GOOGL": "Alphabet Class A",
    "HON": "Honeywell",
    "IDXX": "IDEXX Laboratories",
    "INTC": "Intel",
    "INTU": "Intuit",
    "ISRG": "Intuitive Surgical",
    "KDP": "Keurig Dr Pepper",
    "KHC": "Kraft Heinz",
    "KLAC": "KLA",
    "LIN": "Linde",
    "LRCX": "Lam Research",
    "LULU": "Lululemon Athletica",
    "MAR": "Marriott International",
    "MCHP": "Microchip Technology",
    "MDLZ": "Mondelez",
    "MELI": "MercadoLibre",
    "META": "Meta Platforms",
    "MNST": "Monster Beverage",
    "MRVL": "Marvell Technology",
    "MSFT": "Microsoft",
    "MSTR": "MicroStrategy",
    "MU": "Micron Technology",
    "NFLX": "Netflix",
    "NVDA": "NVIDIA",
    "NXPI": "NXP Semiconductors",
    "ODFL": "Old Dominion Freight Line",
    "ON": "ON Semiconductor",
    "ORLY": "O'Reilly Automotive",
    "PANW": "Palo Alto Networks",
    "PAYX": "Paychex",
    "PCAR": "PACCAR",
    "PDD": "PDD Holdings",
    "PEP": "PepsiCo",
    "PLTR": "Palantir",
    "PYPL": "PayPal",
    "QCOM": "Qualcomm",
    "REGN": "Regeneron",
    "ROP": "Roper Technologies",
    "ROST": "Ross Stores",
    "SBUX": "Starbucks",
    "SNPS": "Synopsys",
    "TEAM": "Atlassian",
    "TMUS": "T-Mobile US",
    "TSLA": "Tesla",
    "TTD": "The Trade Desk",
    "TTWO": "Take-Two Interactive",
    "TXN": "Texas Instruments",
    "VRSK": "Verisk Analytics",
    "VRTX": "Vertex Pharmaceuticals",
    "WBD": "Warner Bros. Discovery",
    "WDAY": "Workday",
    "XEL": "Xcel Energy",
    "ZS": "Zscaler",
}


def read_symbols_file(path: Path) -> dict[str, str]:
    symbols: dict[str, str] = {}
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        parts = [part.strip() for part in line.replace(",", " ").split()]
        if parts:
            symbols[parts[0].upper()] = " ".join(parts[1:]) or parts[0].upper()
    return symbols


def write_symbols_file(path: Path, symbols: dict[str, str]) -> None:
    lines = [
        "# Static NASDAQ-100 universe for US V18 daily watch.",
        "# Format: SYMBOL Name",
    ]
    for symbol, name in sorted(symbols.items()):
        lines.append(f"{symbol} {name}")
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def load_nasdaq100(refresh: bool = False) -> dict[str, str]:
    if NASDAQ100_FILE.exists() and not refresh:
        symbols = read_symbols_file(NASDAQ100_FILE)
        if symbols:
            print(f"[US V18] NASDAQ-100 static file: {len(symbols)} symbols")
            return symbols

    try:
        request = urllib.request.Request(
            NASDAQ100_WIKI,
            headers={"User-Agent": "Mozilla/5.0 (MaaSwing-US-V18)"},
        )
        with urllib.request.urlopen(request, timeout=20) as response:
            html = response.read().decode("utf-8", errors="replace")
        tables = pd.read_html(io.StringIO(html))
        for df in tables:
            cols = {str(col).strip().lower(): col for col in df.columns}
            symbol_col = cols.get("ticker") or cols.get("symbol")
            name_col = cols.get("company")
            if symbol_col is None or name_col is None:
                continue
            rows = df[[symbol_col, name_col]].dropna()
            symbols = {
                str(row[symbol_col]).strip().replace(".", "-").upper(): str(row[name_col]).strip()
                for _, row in rows.iterrows()
            }
            if len(symbols) >= 50:
                print(f"[US V18] NASDAQ-100: {len(symbols)} symbols")
                if refresh:
                    write_symbols_file(NASDAQ100_FILE, symbols)
                    print(f"[US V18] NASDAQ-100 static file updated: {NASDAQ100_FILE}")
                return symbols
    except Exception as exc:
        print(f"[US V18] NASDAQ-100 list fetch failed, fallback used: {type(exc).__name__}")
    print(f"[US V18] NASDAQ-100 fallback: {len(FALLBACK_NASDAQ100)} symbols")
    return FALLBACK_NASDAQ100


def read_sp500_file(path: Path) -> tuple[dict[str, str], dict[str, str]]:
    symbols: dict[str, str] = {}
    sectors: dict[str, str] = {}
    for line in path.read_text(encoding="utf-8").splitlines():
        if not line.strip() or line.startswith("#"):
            continue
        parts = line.split("\t")
        if len(parts) < 3:
            continue
        symbol = normalize_us_symbol(parts[0])
        sectors[symbol] = parts[1].strip()
        symbols[symbol] = parts[2].strip() or symbol
    return symbols, sectors


def write_sp500_file(path: Path, symbols: dict[str, str], sectors: dict[str, str]) -> None:
    lines = [
        "# Static S&P500 universe for US V18 daily watch.",
        "# Format: SYMBOL<TAB>GICS Sector<TAB>Name",
    ]
    for symbol in sorted(symbols):
        lines.append(f"{symbol}\t{sectors.get(symbol, '')}\t{symbols[symbol]}")
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def load_sp500(refresh: bool = False) -> tuple[dict[str, str], dict[str, str]]:
    """S&P500の (symbol→name, symbol→GICS Sector) を返す。静的ファイル優先・無ければWikipedia取得。"""
    if SP500_FILE.exists() and not refresh:
        symbols, sectors = read_sp500_file(SP500_FILE)
        if symbols:
            print(f"[US V18] S&P500 static file: {len(symbols)} symbols")
            return symbols, sectors

    try:
        request = urllib.request.Request(
            SP500_WIKI,
            headers={"User-Agent": "Mozilla/5.0 (MaaSwing-US-V18)"},
        )
        with urllib.request.urlopen(request, timeout=25) as response:
            html = response.read().decode("utf-8", errors="replace")
        tables = pd.read_html(io.StringIO(html))
        for df in tables:
            cols = {str(col).strip().lower(): col for col in df.columns}
            symbol_col = cols.get("symbol") or cols.get("ticker")
            name_col = cols.get("security")
            sector_col = cols.get("gics sector")
            if symbol_col is None or sector_col is None or name_col is None:
                continue
            rows = df[[symbol_col, name_col, sector_col]].dropna()
            symbols: dict[str, str] = {}
            sectors: dict[str, str] = {}
            for _, row in rows.iterrows():
                symbol = normalize_us_symbol(row[symbol_col])
                symbols[symbol] = str(row[name_col]).strip()
                sectors[symbol] = str(row[sector_col]).strip()
            if len(symbols) >= 400:
                print(f"[US V18] S&P500: {len(symbols)} symbols")
                write_sp500_file(SP500_FILE, symbols, sectors)  # 取得できたら必ずキャッシュ
                return symbols, sectors
    except Exception as exc:
        print(f"[US V18] S&P500 list fetch failed: {type(exc).__name__}: {exc}")

    if SP500_FILE.exists():
        symbols, sectors = read_sp500_file(SP500_FILE)
        if symbols:
            print(f"[US V18] S&P500 fallback to static file: {len(symbols)} symbols")
            return symbols, sectors
    raise SystemExit("S&P500 universe could not be loaded (no cache and fetch failed).")


def load_universe(args: argparse.Namespace) -> tuple[dict[str, str], dict[str, str]]:
    """(symbols{sym→name}, sectors{sym→GICS Sector}) を返す。sectorsはS&P500時のみ埋まる。"""
    if args.symbols:
        syms = {s.strip().upper(): s.strip().upper() for s in args.symbols.split(",") if s.strip()}
        return syms, {}
    if args.symbols_file:
        return read_symbols_file(Path(args.symbols_file)), {}
    if args.universe == "sp500":
        return load_sp500(refresh=args.refresh_universe)
    return load_nasdaq100(refresh=args.refresh_universe), {}


def fetch_batch(tickers: list[str], period: str, interval: str) -> pd.DataFrame:
    return yf.download(
        tickers,
        period=period,
        interval=interval,
        group_by="ticker",
        auto_adjust=True,
        progress=False,
        threads=False,
    )


def one_symbol_frame(raw: pd.DataFrame, ticker: str) -> pd.DataFrame:
    if isinstance(raw.columns, pd.MultiIndex):
        if ticker not in raw.columns.get_level_values(0):
            return pd.DataFrame()
        return raw[ticker].dropna()
    return raw.dropna()


def check_v18(daily: pd.DataFrame, weekly: pd.DataFrame) -> dict | None:
    if daily is None or len(daily) < MA_L + 5:
        return None
    if weekly is None or len(weekly) < WMA_L + 5:
        return None

    d = daily.copy()
    d["ma5"] = d["Close"].rolling(MA_S).mean()
    d["ma20"] = d["Close"].rolling(MA_M).mean()
    d["ma60"] = d["Close"].rolling(MA_L).mean()
    d["vol20"] = d["Volume"].rolling(20).mean()

    w = weekly.copy()
    w["wma5"] = w["Close"].rolling(WMA_S).mean()
    w["wma20"] = w["Close"].rolling(WMA_M).mean()
    w["wma60"] = w["Close"].rolling(WMA_L).mean()

    row = d.iloc[-1]
    prev = d.iloc[-2]
    if len(w) < 3:
        return None
    wprev = w.iloc[-2]
    wprev2 = w.iloc[-3]

    weekly_ok = (
        (wprev["wma5"] > wprev["wma20"])
        and (wprev["wma60"] < wprev["wma20"])
        and (wprev["wma20"] > wprev2["wma20"])
    )
    if not weekly_ok:
        return None

    ma5 = row["ma5"]
    ma20 = row["ma20"]
    ma60 = row["ma60"]
    if pd.isna(ma5) or pd.isna(ma20) or pd.isna(ma60):
        return None

    is_perfect = (ma5 > ma20) and (ma20 > ma60)
    is_m_up = ma20 > prev["ma20"]
    is_bull = row["Close"] > row["Open"]
    filt_ok = (row["vol20"] >= MIN_VOL) and (row["Close"] <= MAX_PRICE)

    dist_m = abs(row["Low"] - ma20) / ma20 * 100
    dist_s = abs(row["Low"] - ma5) / ma5 * 100
    near_m20 = (row["Low"] > ma20) and (dist_m < NEAR_M20_PCT)
    near_m5 = (row["Low"] > ma5) and (dist_s < NEAR_M5_PCT)

    if not (is_perfect and is_m_up and is_bull and filt_ok and (near_m20 or near_m5)):
        return None

    return {
        "close": round(float(row["Close"]), 2),
        "ma5": round(float(ma5), 2),
        "ma20": round(float(ma20), 2),
        "ma60": round(float(ma60), 2),
        "dist_m": round(float(dist_m), 2),
        "dist_s": round(float(dist_s), 2),
        "near": "MA20" if near_m20 else "MA5",
        "vol20": int(row["vol20"]),
    }


def run_screener(symbols: dict[str, str], limit: int = 0) -> list[dict]:
    items = list(symbols.items())
    if limit > 0:
        items = items[:limit]
    tickers = [symbol for symbol, _ in items]
    total = len(tickers)
    results: list[dict] = []

    for start in range(0, total, CHUNK):
        chunk_items = items[start : start + CHUNK]
        chunk = [symbol for symbol, _ in chunk_items]
        print(f"  [{start + 1}-{min(start + CHUNK, total)}/{total}] fetching...")
        try:
            daily_all = fetch_batch(chunk, period="1y", interval="1d")
            weekly_all = fetch_batch(chunk, period="5y", interval="1wk")
        except Exception as exc:
            print(f"    [WARN] fetch failed: {exc}")
            continue

        for symbol, name in chunk_items:
            try:
                daily = one_symbol_frame(daily_all, symbol)
                weekly = one_symbol_frame(weekly_all, symbol)
                info = check_v18(daily, weekly)
                if not info:
                    continue
                info["code"] = symbol
                info["ticker"] = symbol
                info["name"] = name
                results.append(info)
                print(f"    OK {symbol} {name[:18]} close={info['close']} near={info['near']}")
            except Exception:
                continue

    return results


def format_report(results: list[dict], universe: str) -> str:
    now = datetime.now(JST)
    lines = [
        f"# US V18スクリーナー結果 {now:%Y-%m-%d}",
        f"実行日時: {now:%Y-%m-%d %H:%M JST}",
        f"母集団: {universe}",
        f"ヒット銘柄: {len(results)}件",
        "",
        "## エントリー候補",
        "",
    ]
    if results:
        lines += [
            "| Symbol | Name | Close | MA5 | MA20 | MA60 | MA距離 | 近接 | Vol20 |",
            "|---|---|---:|---:|---:|---:|---:|---|---:|",
        ]
        for r in sorted(results, key=lambda item: item["dist_m"]):
            lines.append(
                f"| {r['code']} | {r['name']} | {r['close']:.2f} | {r['ma5']:.2f} | "
                f"{r['ma20']:.2f} | {r['ma60']:.2f} | {r['dist_m']:.2f}% | "
                f"{r['near']} | {r['vol20']:,} |"
            )
    else:
        lines.append("本日の候補なし")

    lines += [
        "",
        "## 次アクション",
        "- MCPで1銘柄ずつKITRA(KNN)確認",
        "- まーが3銘柄を目視選択",
        "- `!us post` で #81maa-us-watch に正式投稿",
    ]
    return "\n".join(lines)


def save_report(results: list[dict], universe: str) -> Path:
    path = OUTPUT_DIR / f"{datetime.now(JST):%Y-%m-%d}_v18_us_{universe}.md"
    path.write_text(format_report(results, universe), encoding="utf-8")
    print(f"[US V18] report saved: {path}")
    return path


def build_discord_messages(results: list[dict], universe: str) -> list[str]:
    """全ヒット銘柄を25件ずつのチャンクに分割して複数メッセージで返す（JP版V18/V10と同方式）。"""
    now = datetime.now(JST)
    sorted_results = sorted(results, key=lambda item: item["dist_m"])

    if not sorted_results:
        return [f"**US V18 {universe} {now:%Y-%m-%d %H:%M JST}**\n本日の候補なし"]

    CHUNK_SIZE = 25
    chunks = [sorted_results[i:i + CHUNK_SIZE] for i in range(0, len(sorted_results), CHUNK_SIZE)]
    total = len(sorted_results)
    messages = []
    for idx, chunk in enumerate(chunks):
        header = (
            f"**US V18 {universe} {now:%Y-%m-%d %H:%M JST}** — **{total}銘柄**ヒット"
            if idx == 0
            else f"**US V18 {universe} {now:%Y-%m-%d}** ({idx + 1}/{len(chunks)})"
        )
        rows = [f"{'Symbol':<8} {'Name':<18} {'Close':>8} {'Near':<4}", "-" * 44]
        for r in chunk:
            rows.append(f"{r['code']:<8} {r['name'][:18]:<18} {r['close']:>8.2f} {r['near']:<4}")
        messages.append("\n".join([header, "```", *rows, "```"]))
    return messages


def post_json(url: str, payload: dict, headers: dict | None = None) -> None:
    data = json.dumps(payload, ensure_ascii=False).encode("utf-8")
    req = urllib.request.Request(
        url,
        data=data,
        headers={"Content-Type": "application/json", "User-Agent": "MaaSwing-US-V18", **(headers or {})},
    )
    urllib.request.urlopen(req, timeout=15)


def find_discord_channel_id(token: str, guild_id: str, channel_name: str) -> str:
    req = urllib.request.Request(
        f"https://discord.com/api/v10/guilds/{guild_id}/channels",
        headers={"Authorization": f"Bot {token}", "User-Agent": "MaaSwing-US-V18"},
    )
    with urllib.request.urlopen(req, timeout=15) as response:
        channels = json.load(response)
    for channel in channels:
        name = str(channel.get("name", ""))
        if name == channel_name or name.startswith(channel_name):
            return str(channel.get("id", ""))
    return ""


def post_to_target(
    contents: list[str],
    label: str,
    *,
    webhook_env: str,
    channel_env: str,
    channel_name: str,
) -> None:
    webhook_url = os.getenv(webhook_env, "")
    if webhook_url:
        for content in contents:
            post_json(webhook_url, {"content": content})
        print(f"[US V18] {label} notification sent via webhook ({len(contents)} msg)")
        return

    token = os.getenv("DISCORD_BOT_TOKEN", "")
    channel_id = os.getenv(channel_env, "")
    if token and not channel_id and os.getenv("DISCORD_GUILD_ID", ""):
        channel_id = find_discord_channel_id(token, os.getenv("DISCORD_GUILD_ID", ""), channel_name)
    if token and channel_id:
        for content in contents:
            post_json(
                f"https://discord.com/api/v10/channels/{channel_id}/messages",
                {"content": content},
                headers={"Authorization": f"Bot {token}"},
            )
        print(f"[US V18] {label} notification sent via bot token ({len(contents)} msg)")
        return

    raise SystemExit(
        f"{webhook_env}, {channel_env}, or Discord channel {channel_name!r} is not available."
    )


def send_to_discord(results: list[dict], universe: str, targets: list[str]) -> None:
    messages = build_discord_messages(results, universe)
    configs = {
        "workspace": {
            "label": "workspace-us",
            "webhook_env": WORKSPACE_WEBHOOK_ENV,
            "channel_env": WORKSPACE_CHANNEL_ENV,
            "channel_name": WORKSPACE_CHANNEL_NAME,
        },
        "uswatch": {
            "label": "81maa-us-watch",
            "webhook_env": US_WATCH_WEBHOOK_ENV,
            "channel_env": US_WATCH_CHANNEL_ENV,
            "channel_name": US_WATCH_CHANNEL_NAME,
        },
    }
    failures = []
    for target in targets:
        config = configs[target]
        try:
            post_to_target(messages, **config)
        except Exception as exc:
            failures.append(f"{config['label']}: {type(exc).__name__}: {exc}")
            print(f"[US V18] {config['label']} notification failed: {type(exc).__name__}: {exc}")
    if failures:
        raise SystemExit("Discord notification failed: " + " / ".join(failures))


HEATMAP_CONTENT = "**US 業種シグナル・ヒートマップ（直近10営業日）**"


def save_to_gsheet_us(
    results: list[dict],
    sectors: dict[str, str],
    spreadsheet_id: str,
) -> list[list[str]]:
    """US V18結果を gsheet の US_最新 / US_履歴 に書き込み、履歴の全行を返す。"""
    if not _GSPREAD_OK:
        print("[US V18] gspread未インストール。pip install gspread google-auth が必要。")
        return []
    creds_path = os.environ.get("GOOGLE_APPLICATION_CREDENTIALS", "")
    if not creds_path or not Path(creds_path).exists():
        print(f"[US V18] GOOGLE_APPLICATION_CREDENTIALS が未設定/不在: {creds_path!r}")
        return []

    scopes = [
        "https://www.googleapis.com/auth/spreadsheets",
        "https://www.googleapis.com/auth/drive",
    ]
    creds = SACredentials.from_service_account_file(creds_path, scopes=scopes)
    gc = gspread.authorize(creds)
    sh = gc.open_by_key(spreadsheet_id)

    today = datetime.now(JST).strftime("%Y-%m-%d")
    run_time = datetime.now(JST).strftime("%H:%M")
    headers = ["Symbol", "Name", "Close", "MA5", "MA20", "MA60", "MA距離(%)", "近接", "Sector", "Vol20"]

    data_rows = []
    for r in sorted(results, key=lambda x: x["dist_m"]):
        data_rows.append([
            r["code"], r["name"], r["close"], r["ma5"], r["ma20"], r["ma60"],
            r["dist_m"], r["near"], sectors.get(r["code"], ""), r["vol20"],
        ])

    # ── 「US_最新」シート（常に上書き）──
    try:
        latest = sh.worksheet("US_最新")
        latest.clear()
    except gspread.exceptions.WorksheetNotFound:
        latest = sh.add_worksheet(title="US_最新", rows=600, cols=12)
    latest.update(
        [[f"US V18 {today} {run_time} 実行 / {len(results)}銘柄ヒット"]] +
        [headers] +
        (data_rows if data_rows else [["本日の候補なし"]]),
        value_input_option="USER_ENTERED",
    )

    # ── 「US_履歴」シート（末尾追記）──
    hist_headers = ["日付", "実行時刻"] + headers
    try:
        hist = sh.worksheet("US_履歴")
    except gspread.exceptions.WorksheetNotFound:
        hist = sh.add_worksheet(title="US_履歴", rows=10000, cols=14)
        hist.append_row(hist_headers)
    hist_rows = [[today, run_time] + row for row in (data_rows if data_rows else [["本日の候補なし"]])]
    hist.append_rows(hist_rows, value_input_option="USER_ENTERED")
    history_values = hist.get_all_values()

    print("[US V18] Spreadsheet更新完了（US_最新 + US_履歴）")
    return history_values


def send_heatmap_to_targets(image_path: Path, targets: list[str]) -> None:
    """ヒートマップ画像をwebhook経由でtargetへ投稿（webhook未設定のtargetはスキップ）。"""
    webhook_envs = {"workspace": WORKSPACE_WEBHOOK_ENV, "uswatch": US_WATCH_WEBHOOK_ENV}
    for target in targets:
        webhook_url = os.getenv(webhook_envs.get(target, ""), "")
        if not webhook_url:
            print(f"[US V18] heatmap skipped for {target}: webhook未設定")
            continue
        try:
            send_discord_image(webhook_url, image_path, HEATMAP_CONTENT)
        except Exception as exc:
            print(f"[US V18] heatmap post failed for {target}: {type(exc).__name__}: {exc}")


def build_us_heatmap(history_rows: list[list[str]], sectors: dict[str, str]) -> Path | None:
    """US_履歴とGICSセクターからハイブリッドUS heatmapを生成しPNGパスを返す（不可ならNone）。"""
    if not history_rows or not sectors:
        return None
    denominators = dict(Counter(sectors.values()))
    heatmap = aggregate_sector_history(
        history_rows,
        sectors,
        sector_denominators=denominators,
        code_normalizer=normalize_us_symbol,
        code_header="Symbol",
    )
    if not heatmap.dates:
        return None
    output = OUTPUT_DIR / f"{heatmap.dates[-1]}_v18_us_sector_heatmap.png"
    render_sector_heatmap(heatmap, output, title="US 業種シグナル・ヒートマップ")
    print(f"[US V18] heatmap生成完了: {output}")
    return output


def main() -> list[dict]:
    parser = argparse.ArgumentParser(description="US V18 screener")
    parser.add_argument("--universe", default="sp500", choices=["sp500", "nasdaq100"])
    parser.add_argument("--symbols", default="", help="Comma-separated symbols for a small test run")
    parser.add_argument("--symbols-file", default="", help="Text/CSV file. First column is symbol; rest is name")
    parser.add_argument("--refresh-universe", action="store_true", help="母集団リストをWebから再取得（静的ファイルを更新）")
    parser.add_argument("--gsheet-id", default="", help="Google Spreadsheet ID（省略時は環境変数 GSHEET_ID）")
    parser.add_argument("--limit", type=int, default=0, help="Limit symbols for testing")
    parser.add_argument("--post-workspace", action="store_true", help=f"Post results to {WORKSPACE_WEBHOOK_ENV}")
    parser.add_argument("--post", action="store_true", help="Post results to workspace-us and #81maa-us-watch")
    args = parser.parse_args()

    print("=" * 60)
    print(f"US V18 screener [{args.universe}]")
    print(f"Run: {datetime.now(JST):%Y-%m-%d %H:%M:%S JST}")
    print("=" * 60)

    symbols, sectors = load_universe(args)
    results = run_screener(symbols, limit=args.limit)
    save_report(results, args.universe)

    spreadsheet_id = args.gsheet_id or os.getenv("GSHEET_ID", "")
    history_rows: list[list[str]] = []
    if spreadsheet_id:
        history_rows = save_to_gsheet_us(results, sectors, spreadsheet_id)

    heatmap_path = None
    try:
        heatmap_path = build_us_heatmap(history_rows, sectors)
    except Exception as exc:
        print(f"[US V18] heatmap生成をスキップ: {type(exc).__name__}: {exc}")

    targets: list[str] = []
    if args.post:
        targets = ["workspace", "uswatch"]
    elif args.post_workspace:
        targets = ["workspace"]
    if targets:
        send_to_discord(results, args.universe, targets)
        if heatmap_path:
            send_heatmap_to_targets(heatmap_path, targets)

    print(f"Done: {len(results)} hits")
    return results


if __name__ == "__main__":
    main()
