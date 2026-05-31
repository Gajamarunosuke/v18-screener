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
from datetime import datetime, timezone, timedelta
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent
LOCAL_DEPS = BASE_DIR / ".deps"
if LOCAL_DEPS.exists():
    sys.path.insert(0, str(LOCAL_DEPS))

import pandas as pd
import yfinance as yf
from dotenv import load_dotenv


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


def load_symbols(args: argparse.Namespace) -> dict[str, str]:
    if args.symbols:
        return {symbol.strip().upper(): symbol.strip().upper() for symbol in args.symbols.split(",") if symbol.strip()}
    if args.symbols_file:
        return read_symbols_file(Path(args.symbols_file))
    return load_nasdaq100(refresh=args.refresh_universe)


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


def build_discord_message(results: list[dict], universe: str) -> str:
    now = datetime.now(JST)
    sorted_results = sorted(results, key=lambda item: item["dist_m"])

    if not sorted_results:
        return f"**US V18 {universe} {now:%Y-%m-%d %H:%M JST}**\n本日の候補なし"

    rows = [f"{'Symbol':<8} {'Name':<18} {'Close':>8} {'Near':<4}", "-" * 44]
    for r in sorted_results[:25]:
        rows.append(f"{r['code']:<8} {r['name'][:18]:<18} {r['close']:>8.2f} {r['near']:<4}")
    more = "" if len(sorted_results) <= 25 else f"\n...and {len(sorted_results) - 25} more"
    return "\n".join(
        [
            f"**US V18 {universe} {now:%Y-%m-%d %H:%M JST}** — **{len(results)}銘柄**ヒット",
            "```",
            *rows,
            "```",
            more,
        ]
    )


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
    content: str,
    label: str,
    *,
    webhook_env: str,
    channel_env: str,
    channel_name: str,
) -> None:
    webhook_url = os.getenv(webhook_env, "")
    if webhook_url:
        post_json(webhook_url, {"content": content})
        print(f"[US V18] {label} notification sent via webhook")
        return

    token = os.getenv("DISCORD_BOT_TOKEN", "")
    channel_id = os.getenv(channel_env, "")
    if token and not channel_id and os.getenv("DISCORD_GUILD_ID", ""):
        channel_id = find_discord_channel_id(token, os.getenv("DISCORD_GUILD_ID", ""), channel_name)
    if token and channel_id:
        post_json(
            f"https://discord.com/api/v10/channels/{channel_id}/messages",
            {"content": content},
            headers={"Authorization": f"Bot {token}"},
        )
        print(f"[US V18] {label} notification sent via bot token")
        return

    raise SystemExit(
        f"{webhook_env}, {channel_env}, or Discord channel {channel_name!r} is not available."
    )


def send_to_discord(results: list[dict], universe: str, targets: list[str]) -> None:
    content = build_discord_message(results, universe)
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
            post_to_target(content, **config)
        except Exception as exc:
            failures.append(f"{config['label']}: {type(exc).__name__}: {exc}")
            print(f"[US V18] {config['label']} notification failed: {type(exc).__name__}: {exc}")
    if failures:
        raise SystemExit("Discord notification failed: " + " / ".join(failures))


def main() -> list[dict]:
    parser = argparse.ArgumentParser(description="US V18 screener")
    parser.add_argument("--universe", default="nasdaq100", choices=["nasdaq100"])
    parser.add_argument("--symbols", default="", help="Comma-separated symbols for a small test run")
    parser.add_argument("--symbols-file", default="", help="Text/CSV file. First column is symbol; rest is name")
    parser.add_argument("--refresh-universe", action="store_true", help="Refresh NASDAQ-100 from the web instead of static file")
    parser.add_argument("--limit", type=int, default=0, help="Limit symbols for testing")
    parser.add_argument("--post-workspace", action="store_true", help=f"Post results to {WORKSPACE_WEBHOOK_ENV}")
    parser.add_argument("--post", action="store_true", help="Post results to workspace-us and #81maa-us-watch")
    args = parser.parse_args()

    print("=" * 60)
    print(f"US V18 screener [{args.universe}]")
    print(f"Run: {datetime.now(JST):%Y-%m-%d %H:%M:%S JST}")
    print("=" * 60)

    symbols = load_symbols(args)
    results = run_screener(symbols, limit=args.limit)
    save_report(results, args.universe)

    if args.post:
        send_to_discord(results, args.universe, ["workspace", "uswatch"])
    elif args.post_workspace:
        send_to_discord(results, args.universe, ["workspace"])

    print(f"Done: {len(results)} hits")
    return results


if __name__ == "__main__":
    main()
