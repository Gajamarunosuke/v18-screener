"""
fund_theme_map.py — 投信テーマ・トレンドマップ（発見コンテンツ用）

10の資産クラス/テーマの代表指数・ETFについて、週足トレンドの強弱を赤緑グラデの
ヒートマップにする。個別株スクリーナーの「業種内シグナル集中」とは別物で、
こちらは「テーマの値動きの方向と強さ」を俯瞰する地図。

色 = 週足トレンドの強弱（強い上昇〜強い下降）。母数（割合）は使わない。
"""

from __future__ import annotations

import argparse
import os
from datetime import datetime
from pathlib import Path

import pandas as pd
import yfinance as yf

from sector_heatmap import _font_path, send_discord_image

BASE_DIR = Path(__file__).resolve().parent
_obsidian_env = os.environ.get("OBSIDIAN_DIR", "")
OUTPUT_DIR = Path(_obsidian_env) if _obsidian_env else BASE_DIR / "output"
OUTPUT_DIR.mkdir(parents=True, exist_ok=True)

# NISAランキングメモと同じチャンネルに相乗り（既存webhookを流用）
WEBHOOK_ENV = "DISCORD_WEBHOOK_MARKET_NISA"

# (表示名, yfinanceティッカー)。並びは攻め→守り→話題。日本株は日経225（TOPIX ETFはデータ不連続のため）。
THEMES: list[tuple[str, str]] = [
    ("全世界株(オルカン)", "ACWI"),
    ("米国株(S&P500)", "^GSPC"),
    ("ナスダック100", "^NDX"),
    ("半導体(SOX)", "^SOX"),
    ("日本株(日経225)", "^N225"),
    ("米国高配当", "VYM"),
    ("インド株", "INDA"),
    ("ゴールド", "GLD"),
    ("米国債(長期)", "TLT"),
    ("宇宙", "ARKX"),
]

# トレンドスコア(-2〜+2)→色。赤=下降・緑=上昇。
_TREND_COLORS = {
    2: (16, 176, 110),
    1: (38, 112, 86),
    0: (55, 60, 74),
    -1: (150, 70, 70),
    -2: (200, 60, 60),
    None: (31, 34, 45),
}

# トレンド判定：半年線(26週移動平均)からの乖離率(%)で5段階
DEV_MA_WEEKS = 26
DEV_STRONG = 10.0   # ±10%以上 → 強い上昇/下降
DEV_MILD = 3.0      # ±3〜10%   → 上昇/下降（±3%以内は中立）


def fetch_weekly_close(ticker: str) -> pd.Series:
    frame = yf.download(ticker, period="2y", interval="1wk", progress=False, auto_adjust=True)
    if frame is None or frame.empty:
        return pd.Series(dtype="float64")
    close = frame["Close"]
    if isinstance(close, pd.DataFrame):
        close = close.iloc[:, 0]
    return close.dropna()


def _trend_scores(close: pd.Series, weeks: int) -> list[int | None]:
    """直近weeks週ぶんのトレンドスコア(-2〜+2)。半年線(26週)からの乖離率(%)で5段階。
    データ不足の週はNone。"""
    if close is None or len(close) < DEV_MA_WEEKS + weeks:
        return [None] * weeks
    ma = close.rolling(DEV_MA_WEEKS).mean()
    scores: list[int | None] = []
    for i in range(len(close) - weeks, len(close)):
        if i < DEV_MA_WEEKS - 1 or pd.isna(ma.iloc[i]):
            scores.append(None)
            continue
        deviation = (close.iloc[i] / ma.iloc[i] - 1) * 100  # 半年線からの乖離率(%)
        if deviation >= DEV_STRONG:
            scores.append(2)
        elif deviation >= DEV_MILD:
            scores.append(1)
        elif deviation <= -DEV_STRONG:
            scores.append(-2)
        elif deviation <= -DEV_MILD:
            scores.append(-1)
        else:
            scores.append(0)
    return scores


def build_theme_trends(weeks: int = 10) -> tuple[list[str], dict[str, list[int | None]]]:
    series: dict[str, pd.Series] = {}
    for name, ticker in THEMES:
        try:
            series[name] = fetch_weekly_close(ticker)
            print(f"[theme-map] {name} ({ticker}): {len(series[name])}週")
        except Exception as exc:  # noqa: BLE001
            print(f"[theme-map] {name} ({ticker}) 取得失敗: {type(exc).__name__}")
            series[name] = pd.Series(dtype="float64")

    valid = [s for s in series.values() if s is not None and not s.empty]
    if not valid:
        raise SystemExit("テーマ指数を1つも取得できませんでした。")
    reference = max(valid, key=len)
    dates = [d.strftime("%m/%d") for d in reference.index[-weeks:]]

    scores = {name: _trend_scores(series.get(name), weeks) for name, _ in THEMES}
    return dates, scores


def theme_rank_label(rank: int) -> str:
    return f"#{rank:02d} 固定テーマ"


def render_theme_map(
    dates: list[str],
    scores: dict[str, list[int | None]],
    output_path: Path,
    title: str = "投信テーマ・トレンドマップ",
) -> Path:
    from PIL import Image, ImageDraw, ImageFont

    if not dates:
        raise ValueError("週データが空です")

    themes = [name for name, _ in THEMES]
    week_count = len(dates)
    left = 58
    label_width = 320
    width = max(1420, left * 2 + label_width + week_count * 104)
    row_height = 48
    table_top = 168
    height = table_top + row_height * (len(themes) + 1) + 96

    image = Image.new("RGB", (width, height), (18, 20, 27))
    draw = ImageDraw.Draw(image)

    regular = _font_path()
    bold = _font_path(bold=True)
    fonts = {
        "title": ImageFont.truetype(bold, 38),
        "subtitle": ImageFont.truetype(regular, 17),
        "header": ImageFont.truetype(bold, 18),
        "label": ImageFont.truetype(regular, 18),
        "small": ImageFont.truetype(regular, 14),
    }
    text = (238, 241, 247)
    muted = (157, 164, 181)
    panel = (28, 31, 42)

    draw.text((58, 36), title, font=fonts["title"], fill=text)
    draw.text(
        (60, 88),
        f"{dates[0]} - {dates[-1]}  |  直近{week_count}週・週足  |  色＝半年線(26週)からの乖離率",
        font=fonts["subtitle"],
        fill=muted,
    )

    draw.text(
        (60, 116),
        f"固定{len(themes)}テーマ  |  左=#表示順",
        font=fonts["small"],
        fill=muted,
    )

    table_width = width - left * 2
    cell_width = (table_width - label_width) / week_count

    # 見出し行
    draw.text((left + 10, table_top + 12), "順位 / テーマ", font=fonts["header"], fill=muted)
    for index, date in enumerate(dates):
        x0 = left + label_width + index * cell_width
        box = draw.textbbox((0, 0), date, font=fonts["header"])
        draw.text((x0 + (cell_width - (box[2] - box[0])) / 2, table_top + 12), date, font=fonts["header"], fill=text)

    # 各テーマ行
    for row_index, theme in enumerate(themes):
        y0 = table_top + row_height + row_index * row_height
        if row_index % 2 == 0:
            draw.rectangle((left, y0, left + label_width, y0 + row_height - 2), fill=panel)
        label = theme if len(theme) <= 22 else f"{theme[:21]}..."
        draw.text((left + 10, y0 + 7), label, font=fonts["label"], fill=text)
        draw.text((left + 10, y0 + 29), theme_rank_label(row_index + 1), font=fonts["small"], fill=muted)

        for column_index, score in enumerate(scores[theme]):
            x0 = left + label_width + column_index * cell_width
            draw.rectangle(
                (x0 + 2, y0 + 2, x0 + cell_width - 2, y0 + row_height - 2),
                fill=_TREND_COLORS[score],
            )

    # 凡例
    legend_y = table_top + row_height * (len(themes) + 1) + 24
    draw.line((left, legend_y - 14, width - left, legend_y - 14), fill=(59, 64, 78), width=1)
    legend = [
        (2, "強い上昇 +10%↑"),
        (1, "上昇 +3〜10%"),
        (0, "中立 ±3%"),
        (-1, "下降 −3〜−10%"),
        (-2, "強い下降 −10%↓"),
    ]
    x = left
    for score, label in legend:
        draw.rectangle((x, legend_y, x + 30, legend_y + 22), fill=_TREND_COLORS[score])
        draw.text((x + 38, legend_y + 2), label, font=fonts["small"], fill=muted)
        x += 38 + draw.textlength(label, font=fonts["small"]) + 32

    output_path.parent.mkdir(parents=True, exist_ok=True)
    image.save(output_path, "PNG", optimize=True)
    return output_path


def main() -> Path:
    parser = argparse.ArgumentParser(description="投信テーマ・トレンドマップ")
    parser.add_argument("--weeks", type=int, default=10, help="表示する週数")
    parser.add_argument("--post", action="store_true", help=f"{WEBHOOK_ENV} に画像を投稿")
    args = parser.parse_args()

    print("=" * 56)
    print("投信テーマ・トレンドマップ")
    print(f"Run: {datetime.now():%Y-%m-%d %H:%M}")
    print("=" * 56)
    dates, scores = build_theme_trends(weeks=args.weeks)
    output = OUTPUT_DIR / f"{datetime.now():%Y-%m-%d}_fund_theme_map.png"
    render_theme_map(dates, scores, output)
    print(f"\n保存: {output}")

    if args.post:
        webhook = os.getenv(WEBHOOK_ENV, "")
        if not webhook:
            print(f"[theme-map] {WEBHOOK_ENV} 未設定のため投稿スキップ")
        else:
            send_discord_image(
                webhook,
                output,
                f"**📊 投信テーマ・トレンドマップ（直近{args.weeks}週・週足）**",
            )
    return output


if __name__ == "__main__":
    main()
