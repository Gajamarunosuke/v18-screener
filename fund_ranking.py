#!/usr/bin/env python3
"""Post Rakuten Securities fund activity rankings to Discord.

The ranking is meant as a "where money is active" memo for #03market-nisa,
not as a recommendation list.
"""

from __future__ import annotations

import argparse
import html
import json
import os
import re
import sys
from dataclasses import dataclass
from datetime import datetime
from typing import Iterable
from urllib import parse, request


RAKUTEN_RANKING_URL = "https://www.rakuten-sec.co.jp/web/fund/find/ranking/ranking.html"
RAKUTEN_NISA_BUY_AMOUNT_TYPE = "500027"
USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
    "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0 Safari/537.36"
)


@dataclass(frozen=True)
class FundRank:
    rank: int
    name: str
    manager: str
    nav: str
    nav_change: str
    asset_type: str


def normalize_text(value: str) -> str:
    value = re.sub(r"<[^>]+>", " ", value)
    value = html.unescape(value)
    value = value.replace("\xa0", " ")
    value = re.sub(r"\s+", " ", value)
    return value.strip()


def fetch_rakuten_html(period: str) -> str:
    params = {
        "type": RAKUTEN_NISA_BUY_AMOUNT_TYPE,
        "freqid": "3" if period == "monthly" else "2",
        "tget": "1",
    }
    url = f"{RAKUTEN_RANKING_URL}?{parse.urlencode(params)}"
    req = request.Request(url, headers={"User-Agent": USER_AGENT})
    with request.urlopen(req, timeout=20) as response:
        charset = response.headers.get_content_charset() or "utf-8"
        return response.read().decode(charset, errors="replace")


def extract_period_label(page_text: str) -> str:
    match = re.search(r"(\d{4}/\d{2}/\d{2}\s*[～~-]\s*\d{4}/\d{2}/\d{2})", page_text)
    return normalize_text(match.group(1)) if match else "期間不明"


def parse_ranking(html_text: str, limit: int) -> tuple[str, list[FundRank]]:
    plain = normalize_text(html_text)
    period_label = extract_period_label(plain)

    start = html_text.find('<div id="table1"')
    end = html_text.find('<div id="table2"', start) if start >= 0 else -1
    target = html_text[start:end] if start >= 0 and end > start else html_text

    # The first "基本情報" table keeps ranking order but the rank icons have no
    # text alt for the top row. Enumerate the rows in appearance order.
    row_pattern = re.compile(
        r"<tr[^>]*>.*?"
        r"<th[^>]*>.*?</th>\s*"
        r"<td>\s*<a[^>]*>(?P<name>.*?)</a>\s*</td>\s*"
        r"<td>(?P<manager>.*?)</td>.*?"
        r"<!-- 基準価格（前日比）-->.*?"
        r"<td[^>]*>(?P<nav>[\d,]+円)<br\s*/?>（\s*<span[^>]*>(?P<change>[+-][\d,]+円)</span>\s*）</td>.*?"
        r"<!-- アセットタイプ -->\s*"
        r"<td>(?P<asset_type>.*?)</td>",
        re.DOTALL,
    )

    rows: list[FundRank] = []
    for rank, match in enumerate(row_pattern.finditer(target), start=1):
        rows.append(
            FundRank(
                rank=rank,
                name=normalize_text(match.group("name")),
                manager=normalize_text(match.group("manager")),
                nav=normalize_text(match.group("nav")),
                nav_change=normalize_text(match.group("change")),
                asset_type=normalize_text(match.group("asset_type")),
            )
        )
        if len(rows) >= limit:
            break

    if not rows:
        raise RuntimeError("楽天証券ランキングの行を抽出できませんでした。ページ構造が変わった可能性があります。")
    return period_label, rows


def build_message(period: str, period_label: str, rows: Iterable[FundRank]) -> str:
    period_name = "月間" if period == "monthly" else "週間"
    lines = [
        f"📊投信ランキングメモ {period_name} {datetime.now().strftime('%Y/%m/%d')}",
        "",
        "楽天証券 NISA投資信託 買付金額ランキング",
        f"集計期間：{period_label}",
        "",
        "【上位】",
    ]
    for row in rows:
        lines.append(
            f"{row.rank}. {row.name} / {row.asset_type} / 基準価額 {row.nav}（{row.nav_change}）"
        )
    lines.extend(
        [
            "",
            "見方：",
            "楽天証券のNISA口座で買付金額が大きかった投信の確認メモです。",
            "NISA資金がどこに集まっているか、活況感を見る入口として使います。",
            "",
            "※人気ランキングであり、買い推奨ではありません。",
            "※最終的な投資判断はご自身でお願いします。",
            "",
            "出典：楽天証券",
        ]
    )
    return "\n".join(lines)


def post_discord(message: str, webhook_url: str) -> None:
    payload = json.dumps({"content": message, "username": "market-nisa Hook"}).encode("utf-8")
    req = request.Request(
        webhook_url,
        data=payload,
        headers={
            "Content-Type": "application/json",
            "User-Agent": "DiscordBot (https://github.com, 1.0)",
        },
        method="POST",
    )
    with request.urlopen(req, timeout=20):
        return


def resolve_webhook_url() -> str | None:
    # #03market-nisa への既存 webhook (DISCORD_WEBHOOK_MARKET_NISA) を最優先で使う。
    # 互換のため MARKET_NISA_WEBHOOK_URL / DISCORD_WEBHOOK_URL もフォールバックで受ける。
    return (
        os.environ.get("DISCORD_WEBHOOK_MARKET_NISA")
        or os.environ.get("MARKET_NISA_WEBHOOK_URL")
        or os.environ.get("DISCORD_WEBHOOK_URL")
    )


def main() -> int:
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")
        sys.stderr.reconfigure(encoding="utf-8")

    parser = argparse.ArgumentParser(description="Post fund activity rankings to Discord.")
    parser.add_argument("--period", choices=["weekly", "monthly"], default="weekly")
    parser.add_argument("--limit", type=int, default=10)
    parser.add_argument("--dry-run", action="store_true", help="Print message without posting")
    parser.add_argument("--save-html", default="", help="Save fetched source HTML for debugging")
    args = parser.parse_args()

    html_text = fetch_rakuten_html(args.period)
    if args.save_html:
        with open(args.save_html, "w", encoding="utf-8") as fh:
            fh.write(html_text)
    period_label, rows = parse_ranking(html_text, args.limit)
    message = build_message(args.period, period_label, rows)

    if args.dry_run:
        print(message)
        return 0

    webhook_url = resolve_webhook_url()
    if not webhook_url:
        print(
            "DISCORD_WEBHOOK_MARKET_NISA（または MARKET_NISA_WEBHOOK_URL / DISCORD_WEBHOOK_URL）が未設定です。",
            file=sys.stderr,
        )
        print(message)
        return 2

    post_discord(message, webhook_url)
    print("Discordへランキングメモを投稿しました。")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
