import argparse
import json
import os
import sys
import urllib.request
from datetime import datetime, timedelta, timezone

try:
    from dotenv import load_dotenv
except ModuleNotFoundError:
    load_dotenv = None


def load_simple_env(path: str, override: bool = False) -> None:
    if not os.path.exists(path):
        return
    with open(path, encoding="utf-8") as f:
        for raw_line in f:
            line = raw_line.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            key, value = line.split("=", 1)
            key = key.strip()
            value = value.strip().strip('"').strip("'")
            if override or key not in os.environ:
                os.environ[key] = value


if load_dotenv:
    load_dotenv()
    load_dotenv(r"D:\60 Obsidian\10_operations\secrets\.env", override=True)
else:
    load_simple_env(".env")
    load_simple_env(r"D:\60 Obsidian\10_operations\secrets\.env", override=True)

try:
    sys.stdout.reconfigure(encoding="utf-8")
except Exception:
    pass


JST = timezone(timedelta(hours=9))
WEBHOOK_ENV = "DISCORD_WEBHOOK_MARKET_NISA"


MARKET_LINKS = {
    "USD/JPY": "https://www.google.com/finance/quote/USD-JPY",
    "日経平均": "https://www.google.com/finance/quote/NI225:INDEXNIKKEI",
    "TOPIX": "https://www.google.com/finance/quote/TOPIX:INDEXTOPIX",
    "VIX": "https://www.google.com/finance/quote/VIX:INDEXCBOE",
    "S&P500": "https://www.google.com/finance/quote/.INX:INDEXSP",
    "NASDAQ100": "https://www.google.com/finance/quote/NDX:INDEXNASDAQ",
    "SOX": "https://www.google.com/finance/quote/SOX:INDEXNASDAQ",
    "Gold": "https://www.google.com/finance/quote/GCW00:COMEX",
}


MARKET_TICKERS = {
    "USD/JPY": "JPY=X",
    "日経平均": "^N225",
    "TOPIX": "1306.T",
    "VIX": "^VIX",
    "S&P500": "^GSPC",
    "NASDAQ100": "^NDX",
    "SOX": "^SOX",
    "Gold": "GC=F",
}


FUND_LINKS = {
    "eMAXIS Slim オルカン": "https://emaxis.am.mufg.jp/fund/253425.html",
    "楽天オルカン": "https://www.rakuten-toushin.co.jp/fund/nav/9I31223C/",
    "楽天S&P500": "https://www.rakuten-toushin.co.jp/fund/nav/9I31223E/",
    "ニッセイNASDAQ100": "https://www.nam.co.jp/fundinfo/nn100if/main.html",
    "ニッセイSOX": "https://www.nam.co.jp/fundinfo/nsoxif/main.html",
    "ゴールドファンド": "https://www.am.mufg.jp/fund/140567.html",
    "FANG+": "https://www.daiwa-am.co.jp/funds/detail/3344/detail_top.html",
    "野村世界半導体": "https://www.nomura-am.co.jp/fund/funddetail.php?fundcd=140779",
}


def markdown_link(label: str, url: str) -> str:
    return f"[{label}](<{url}>)"


def today_label() -> str:
    return datetime.now(JST).strftime("%Y/%m/%d")


def fmt_value(value: float | None, digits: int = 2) -> str:
    if value is None:
        return "--"
    return f"{value:,.{digits}f}"


def fmt_pct(value: float | None) -> str:
    if value is None:
        return "--%"
    sign = "+" if value >= 0 else ""
    return f"{sign}{value:.2f}%"


def fetch_market_rows() -> dict[str, dict]:
    try:
        import yfinance as yf
    except ModuleNotFoundError as exc:
        return {name: {"error": str(exc)} for name in MARKET_TICKERS}

    rows: dict[str, dict] = {}
    for name, ticker in MARKET_TICKERS.items():
        try:
            hist = yf.download(ticker, period="5d", interval="1d", progress=False, auto_adjust=False)
            if hist.empty or "Close" not in hist:
                rows[name] = {}
                continue
            closes = hist["Close"].dropna()
            if len(closes) < 1:
                rows[name] = {}
                continue
            latest = float(closes.iloc[-1])
            previous = float(closes.iloc[-2]) if len(closes) >= 2 else None
            change_pct = ((latest / previous) - 1) * 100 if previous else None
            rows[name] = {"value": latest, "change_pct": change_pct}
        except Exception as exc:
            rows[name] = {"error": str(exc)}
    return rows


def build_morning_message() -> str:
    market_rows = fetch_market_rows()
    lines = [
        f"🌅朝の地合いメモ {today_label()}",
        "",
        "前日分の市場確認用です。",
        "",
    ]
    for name in ["USD/JPY", "日経平均", "TOPIX", "VIX", "S&P500", "NASDAQ100", "SOX", "Gold"]:
        row = market_rows.get(name, {})
        digits = 3 if name == "USD/JPY" else 2
        value = fmt_value(row.get("value"), digits=digits)
        change_pct = fmt_pct(row.get("change_pct"))
        lines.append(f"{name} {value}（前日比 {change_pct}） {markdown_link('確認', MARKET_LINKS[name])}")

    lines.extend(
        [
            "",
            "見方：",
            "VIX低下＋SOX強めならリスクオン寄り。日経平均とTOPIXの差で、大型寄りか全体地合いかを確認。",
        ]
    )
    return "\n".join(lines)


def build_evening_message() -> str:
    lines = [
        f"🌆夕方の投信・指数メモ {today_label()}",
        "",
        "確定基準価額ベースの確認メモです。",
        "",
        "【保有・確認】",
    ]
    for name in [
        "eMAXIS Slim オルカン",
        "楽天オルカン",
        "楽天S&P500",
        "ニッセイNASDAQ100",
        "ニッセイSOX",
        "ゴールドファンド",
    ]:
        lines.append(f"{name} --%（年初来 --%） {markdown_link('確認', FUND_LINKS[name])}")

    lines.extend(["", "【ウォッチ】"])
    for name in ["FANG+", "野村世界半導体"]:
        lines.append(f"{name} --%（年初来 --%） {markdown_link('確認', FUND_LINKS[name])}")

    lines.extend(
        [
            "",
            "ひとこと：",
            "SOX・NASDAQ・FANG+の強弱で、半導体/AI/グロース候補の追い風を確認。",
        ]
    )
    return "\n".join(lines)


def send_discord(webhook: str, content: str) -> None:
    payload = json.dumps({"content": content}, ensure_ascii=False).encode("utf-8")
    req = urllib.request.Request(
        webhook,
        data=payload,
        headers={
            "Content-Type": "application/json",
            "User-Agent": "MaaSwingMarketNisaBot (github-actions, 1.0)",
        },
    )
    urllib.request.urlopen(req, timeout=10)


def main() -> None:
    parser = argparse.ArgumentParser(description="Post market/NISA memo templates to Discord.")
    parser.add_argument("--mode", choices=["morning", "evening"], default="evening")
    parser.add_argument("--post", action="store_true", help="Post to Discord webhook.")
    args = parser.parse_args()

    content = build_morning_message() if args.mode == "morning" else build_evening_message()
    if args.post:
        webhook = os.getenv(WEBHOOK_ENV)
        if not webhook:
            raise SystemExit(f"{WEBHOOK_ENV} is not set.")
        send_discord(webhook, content)
        print("posted")
    else:
        print(content)


if __name__ == "__main__":
    main()
