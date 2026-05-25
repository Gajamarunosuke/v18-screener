import argparse
import html
import json
import os
import re
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
    "日経平均": "https://finance.yahoo.co.jp/quote/998407.O",
    "TOPIX": "https://finance.yahoo.co.jp/quote/998405.T",
    "VIX": "https://www.google.com/finance/quote/VIX:INDEXCBOE",
    "S&P500": "https://www.google.com/finance/quote/.INX:INDEXSP",
    "NASDAQ100": "https://www.google.com/finance/quote/NDX:INDEXNASDAQ",
    "SOX": "https://www.google.com/finance/quote/SOX:INDEXNASDAQ",
    "Gold": "https://www.google.com/finance/quote/GCW00:COMEX",
}


MARKET_TICKERS = {
    "USD/JPY": "JPY=X",
    "VIX": "^VIX",
    "S&P500": "^GSPC",
    "NASDAQ100": "^NDX",
    "SOX": "^SOX",
    "Gold": "GC=F",
}


FUND_LINKS = {
    "eMAXIS Slim オルカン": "https://finance.yahoo.co.jp/quote/0331418A/history",
    "楽天オルカン": "https://finance.yahoo.co.jp/quote/9I31123A/history",
    "楽天S&P500": "https://finance.yahoo.co.jp/quote/9I31223A/history",
    "ニッセイNASDAQ100": "https://finance.yahoo.co.jp/quote/29313233/history",
    "ニッセイSOX": "https://finance.yahoo.co.jp/quote/29314233/history",
    "ゴールドファンド": "https://finance.yahoo.co.jp/quote/02312177/history",
    "FANG+": "https://finance.yahoo.co.jp/quote/04311181/history",
    "野村世界半導体": "https://finance.yahoo.co.jp/quote/01313098/history",
}


FUND_CODES = {
    "eMAXIS Slim オルカン": "0331418A",
    "楽天オルカン": "9I31123A",
    "楽天S&P500": "9I31223A",
    "ニッセイNASDAQ100": "29313233",
    "ニッセイSOX": "29314233",
    "ゴールドファンド": "02312177",
    "FANG+": "04311181",
    "野村世界半導体": "01313098",
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


def parse_number(value: str) -> float | None:
    cleaned = value.replace(",", "").replace("+", "").replace("−", "-").strip()
    try:
        return float(cleaned)
    except ValueError:
        return None


def fetch_market_rows() -> dict[str, dict]:
    try:
        import yfinance as yf
    except ModuleNotFoundError as exc:
        return {name: {"error": str(exc)} for name in MARKET_TICKERS}

    rows: dict[str, dict] = {}
    for name, ticker in MARKET_TICKERS.items():
        try:
            hist = yf.Ticker(ticker).history(period="5d")
            if hist.empty or "Close" not in hist.columns:
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
    rows["日経平均"] = fetch_yahoo_index_row("998407.O")
    rows["TOPIX"] = fetch_yahoo_index_row("998405.T")
    return rows


def fetch_yahoo_index_row(code: str) -> dict:
    url = f"https://finance.yahoo.co.jp/quote/{code}"
    headers = {"User-Agent": "Mozilla/5.0"}
    try:
        req = urllib.request.Request(url, headers=headers)
        with urllib.request.urlopen(req, timeout=15) as resp:
            text = resp.read().decode("utf-8", errors="replace")
        text = html.unescape(text)
        value_match = re.search(
            r'PriceBoard__price__1V0k.*?StyledNumber__value__3rXW">([\d,]+\.\d+)'
            r'.*?PriceChangeLabel__primary__Y_ut.*?StyledNumber__value__3rXW">([+\-−][\d,]+\.\d+)'
            r'.*?PriceChangeLabel__secondary__3BXI.*?StyledNumber__value__3rXW">([+\-−]?\d+\.\d+)',
            text,
            re.S,
        )
        if not value_match:
            return {}
        return {
            "value": parse_number(value_match.group(1)),
            "change_pct": parse_number(value_match.group(3)),
        }
    except Exception as exc:
        return {"error": str(exc)}


def fetch_yahoo_fund_rows() -> dict[str, dict]:
    rows: dict[str, dict] = {}
    headers = {"User-Agent": "Mozilla/5.0"}
    year = datetime.now(JST).year
    from_date = f"{year}0101"
    to_date = datetime.now(JST).strftime("%Y%m%d")

    for name, code in FUND_CODES.items():
        page_url = f"https://finance.yahoo.co.jp/quote/{code}/history"
        try:
            req = urllib.request.Request(page_url, headers=headers)
            with urllib.request.urlopen(req, timeout=15) as resp:
                page_text = resp.read().decode("utf-8", errors="replace")
            token_match = re.search(r'jwtToken":"([^"]+)', page_text)
            if not token_match:
                rows[name] = {}
                continue

            api_url = (
                f"https://finance.yahoo.co.jp/bff-pc/v1/main/fund/chart/history/{code}"
                f"?fromDate={from_date}&size=300&timeFrame=daily&toDate={to_date}"
            )
            api_headers = {
                **headers,
                "Referer": page_url,
                "jwt-token": token_match.group(1),
            }
            req = urllib.request.Request(api_url, headers=api_headers)
            with urllib.request.urlopen(req, timeout=15) as resp:
                data = json.load(resp)
            histories = data.get("priceHistories", [])
            if len(histories) < 2:
                rows[name] = {}
                continue

            histories = sorted(histories, key=lambda row: row.get("baseDate", ""))
            first = histories[0]
            previous = histories[-2]
            latest = histories[-1]
            latest_value = float(latest["closePrice"])
            previous_value = float(previous["closePrice"])
            first_value = float(first["closePrice"])
            change_pct = ((latest_value / previous_value) - 1) * 100 if previous_value else None
            ytd_pct = ((latest_value / first_value) - 1) * 100 if first_value else None
            rows[name] = {
                "value": latest_value,
                "change_pct": change_pct,
                "ytd_pct": ytd_pct,
                "date": latest.get("baseDate"),
            }
        except Exception as exc:
            rows[name] = {"error": str(exc)}
    return rows


def build_morning_message() -> str:
    market_rows = fetch_market_rows()
    fetch_errors = []
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
        lines.append(f"{name} {value}（前日比 {change_pct}） {markdown_link('Yahoo/Google', MARKET_LINKS[name])}")
        if row.get("error") or value == "--":
            fetch_errors.append(name)

    lines.extend(
        [
            "",
            "見方：",
            "VIX低下＋SOX強めならリスクオン寄り。日経平均とTOPIXの差で、大型寄りか全体地合いかを確認。",
        ]
    )
    if fetch_errors:
        lines.extend(["", f"未取得：{', '.join(fetch_errors)}"])
    return "\n".join(lines)


def build_evening_message() -> str:
    fund_rows = fetch_yahoo_fund_rows()
    fetch_errors = []
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
        row = fund_rows.get(name, {})
        line = (
            f"{name} {fmt_pct(row.get('change_pct'))}"
            f"（年初来 {fmt_pct(row.get('ytd_pct'))} / 基準価額 {fmt_value(row.get('value'), digits=0)}） {markdown_link('Yahoo', FUND_LINKS[name])}"
        )
        lines.append(line)
        if row.get("error") or row.get("change_pct") is None:
            fetch_errors.append(name)

    lines.extend(["", "【ウォッチ】"])
    for name in ["FANG+", "野村世界半導体"]:
        row = fund_rows.get(name, {})
        line = (
            f"{name} {fmt_pct(row.get('change_pct'))}"
            f"（年初来 {fmt_pct(row.get('ytd_pct'))} / 基準価額 {fmt_value(row.get('value'), digits=0)}） {markdown_link('Yahoo', FUND_LINKS[name])}"
        )
        lines.append(line)
        if row.get("error") or row.get("change_pct") is None:
            fetch_errors.append(name)

    lines.extend(
        [
            "",
            "ひとこと：",
            "SOX・NASDAQ・FANG+の強弱で、半導体/AI/グロース候補の追い風を確認。",
        ]
    )
    if fetch_errors:
        lines.extend(["", f"未取得：{', '.join(fetch_errors)}"])
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
