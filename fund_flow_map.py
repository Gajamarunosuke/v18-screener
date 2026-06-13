"""Render weekly NISA fund-flow momentum from Rakuten ranking history."""

from __future__ import annotations

import argparse
import os
import re
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path

from fund_ranking import FundRank, fetch_rakuten_html, parse_ranking
from sector_heatmap import _font_path, send_discord_image

BASE_DIR = Path(__file__).resolve().parent
OUTPUT_DIR = Path(os.environ.get("OBSIDIAN_DIR", "")) if os.environ.get("OBSIDIAN_DIR") else BASE_DIR / "output"
WEBHOOK_ENV = "DISCORD_WEBHOOK_MARKET_NISA"
SHEET_NAME = "NISA資金フロー履歴"
HISTORY_HEADERS = ["集計週", "取得日", "順位", "投信名", "運用会社", "資産タイプ"]


@dataclass(frozen=True)
class FundFlowHistory:
    weeks: list[str]
    funds: list[str]
    ranks: dict[str, list[int | None]]
    changes: dict[str, list[int | None]]
    asset_types: dict[str, str]


def _period_end(period_label: str) -> str:
    dates = re.findall(r"\d{4}/\d{2}/\d{2}", period_label)
    return dates[-1] if dates else period_label.strip()


def _week_label(period_label: str) -> str:
    end = _period_end(period_label)
    match = re.search(r"(\d{2})/(\d{2})$", end)
    return f"{match.group(1)}/{match.group(2)}" if match else end


def build_fund_flow_history(
    rows: list[list[str]],
    max_weeks: int = 10,
    max_funds: int = 15,
) -> FundFlowHistory:
    if not rows:
        return FundFlowHistory([], [], {}, {}, {})

    headers = [str(value).strip() for value in rows[0]]
    required = HISTORY_HEADERS
    if any(header not in headers for header in required):
        return FundFlowHistory([], [], {}, {}, {})
    indexes = {header: headers.index(header) for header in required}

    # A repeated run for the same ranking period replaces the older snapshot.
    snapshots: dict[tuple[str, str], tuple[str, int, str]] = {}
    period_keys: set[str] = set()
    for row in rows[1:]:
        if len(row) <= max(indexes.values()):
            continue
        period = str(row[indexes["集計週"]]).strip()
        fund = str(row[indexes["投信名"]]).strip()
        fetched_on = str(row[indexes["取得日"]]).strip()
        asset_type = str(row[indexes["資産タイプ"]]).strip()
        try:
            rank = int(str(row[indexes["順位"]]).strip())
        except ValueError:
            continue
        if not period or not fund:
            continue
        period_key = _period_end(period)
        period_keys.add(period_key)
        key = (period_key, fund)
        previous = snapshots.get(key)
        if previous is None or fetched_on >= previous[0]:
            snapshots[key] = (fetched_on, rank, asset_type)

    selected_periods = sorted(period_keys)[-max_weeks:]
    if not selected_periods:
        return FundFlowHistory([], [], {}, {}, {})

    all_funds = {fund for period, fund in snapshots if period in selected_periods}
    latest_period = selected_periods[-1]

    def fund_order(fund: str) -> tuple[int, int, str]:
        latest = snapshots.get((latest_period, fund))
        best = min(
            snapshots[(period, fund)][1]
            for period in selected_periods
            if (period, fund) in snapshots
        )
        return (latest[1] if latest else 10_000, best, fund)

    funds = sorted(all_funds, key=fund_order)[:max_funds]
    ranks: dict[str, list[int | None]] = {}
    changes: dict[str, list[int | None]] = {}
    asset_types: dict[str, str] = {}
    for fund in funds:
        fund_ranks = [
            snapshots[(period, fund)][1] if (period, fund) in snapshots else None
            for period in selected_periods
        ]
        fund_changes: list[int | None] = []
        for index, rank in enumerate(fund_ranks):
            previous_rank = fund_ranks[index - 1] if index else None
            fund_changes.append(previous_rank - rank if rank is not None and previous_rank is not None else None)
        ranks[fund] = fund_ranks
        changes[fund] = fund_changes
        asset_types[fund] = next(
            snapshots[(period, fund)][2]
            for period in reversed(selected_periods)
            if (period, fund) in snapshots
        )

    return FundFlowHistory(
        weeks=[_week_label(period) for period in selected_periods],
        funds=funds,
        ranks=ranks,
        changes=changes,
        asset_types=asset_types,
    )


def _flow_color(change: int | None) -> tuple[int, int, int]:
    if change is None:
        return 31, 34, 45
    if change >= 3:
        return 16, 176, 110
    if change >= 1:
        return 38, 112, 86
    if change <= -3:
        return 200, 60, 60
    if change <= -1:
        return 150, 70, 70
    return 55, 60, 74


def render_fund_flow_map(
    history: FundFlowHistory,
    output_path: Path,
    title: str = "NISA資金フローマップ",
) -> Path:
    from PIL import Image, ImageDraw, ImageFont

    if not history.weeks:
        raise ValueError("Fund flow history is empty")

    left = 58
    label_width = 390
    row_height = 54
    table_top = 174
    week_count = len(history.weeks)
    width = max(1420, left * 2 + label_width + week_count * 96)
    height = table_top + row_height * (len(history.funds) + 1) + 100
    image = Image.new("RGB", (width, height), (18, 20, 27))
    draw = ImageDraw.Draw(image)

    regular = _font_path()
    bold = _font_path(bold=True)
    fonts = {
        "title": ImageFont.truetype(bold, 38),
        "subtitle": ImageFont.truetype(regular, 17),
        "header": ImageFont.truetype(bold, 18),
        "label": ImageFont.truetype(regular, 17),
        "asset": ImageFont.truetype(regular, 12),
        "rank": ImageFont.truetype(bold, 23),
        "delta": ImageFont.truetype(bold, 12),
        "small": ImageFont.truetype(regular, 14),
    }
    text = (238, 241, 247)
    muted = (157, 164, 181)
    panel = (28, 31, 42)

    draw.text((left, 36), title, font=fonts["title"], fill=text)
    draw.text(
        (left + 2, 88),
        f"直近{week_count}週  |  色＝前週からの順位変動（緑: 上昇 / 赤: 低下）  |  数字＝買付金額順位",
        font=fonts["subtitle"],
        fill=muted,
    )
    draw.text(
        (left + 2, 116),
        "楽天証券 NISA投資信託・週間買付金額ランキングを使用（買付金額そのものは非公開）",
        font=fonts["small"],
        fill=muted,
    )

    table_width = width - left * 2
    cell_width = (table_width - label_width) / week_count
    draw.text((left + 10, table_top + 15), "投信", font=fonts["header"], fill=muted)
    for index, week in enumerate(history.weeks):
        x0 = left + label_width + index * cell_width
        box = draw.textbbox((0, 0), week, font=fonts["header"])
        draw.text((x0 + (cell_width - (box[2] - box[0])) / 2, table_top + 15), week, font=fonts["header"], fill=text)

    for row_index, fund in enumerate(history.funds):
        y0 = table_top + row_height + row_index * row_height
        if row_index % 2 == 0:
            draw.rectangle((left, y0, left + label_width, y0 + row_height - 2), fill=panel)
        label = fund if len(fund) <= 28 else f"{fund[:27]}…"
        draw.text((left + 10, y0 + 7), label, font=fonts["label"], fill=text)
        draw.text((left + 10, y0 + 31), history.asset_types.get(fund, ""), font=fonts["asset"], fill=muted)

        for column_index, rank in enumerate(history.ranks[fund]):
            change = history.changes[fund][column_index]
            x0 = left + label_width + column_index * cell_width
            draw.rectangle(
                (x0 + 2, y0 + 2, x0 + cell_width - 2, y0 + row_height - 2),
                fill=_flow_color(change),
            )
            display = "-" if rank is None else str(rank)
            box = draw.textbbox((0, 0), display, font=fonts["rank"])
            draw.text(
                (x0 + (cell_width - (box[2] - box[0])) / 2, y0 + 7),
                display,
                font=fonts["rank"],
                fill=text,
            )
            if change:
                delta = f"{change:+d}"
                delta_box = draw.textbbox((0, 0), delta, font=fonts["delta"])
                draw.text(
                    (x0 + (cell_width - (delta_box[2] - delta_box[0])) / 2, y0 + 35),
                    delta,
                    font=fonts["delta"],
                    fill=text,
                )

    legend_y = table_top + row_height * (len(history.funds) + 1) + 28
    draw.line((left, legend_y - 14, width - left, legend_y - 14), fill=(59, 64, 78), width=1)
    legend = [(3, "3位以上↑"), (1, "1-2位↑"), (0, "変わらず"), (-1, "1-2位↓"), (-3, "3位以上↓")]
    x = left
    for change, label in legend:
        draw.rectangle((x, legend_y, x + 30, legend_y + 22), fill=_flow_color(change))
        draw.text((x + 38, legend_y + 2), label, font=fonts["small"], fill=muted)
        x += 38 + draw.textlength(label, font=fonts["small"]) + 30

    output_path.parent.mkdir(parents=True, exist_ok=True)
    image.save(output_path, "PNG", optimize=True)
    return output_path


def _snapshot_rows(period_label: str, ranks: list[FundRank]) -> list[list[str | int]]:
    fetched_on = datetime.now().strftime("%Y-%m-%d")
    return [
        [period_label, fetched_on, row.rank, row.name, row.manager, row.asset_type]
        for row in ranks
    ]


def save_history_to_gsheet(
    spreadsheet_id: str,
    period_label: str,
    ranks: list[FundRank],
) -> list[list[str]]:
    import gspread
    from google.oauth2.service_account import Credentials

    creds_path = os.environ.get("GOOGLE_APPLICATION_CREDENTIALS", "")
    if not creds_path or not Path(creds_path).exists():
        raise RuntimeError("GOOGLE_APPLICATION_CREDENTIALS is not configured")
    scopes = [
        "https://www.googleapis.com/auth/spreadsheets",
        "https://www.googleapis.com/auth/drive",
    ]
    credentials = Credentials.from_service_account_file(creds_path, scopes=scopes)
    sheet = gspread.authorize(credentials).open_by_key(spreadsheet_id)
    try:
        worksheet = sheet.worksheet(SHEET_NAME)
    except gspread.exceptions.WorksheetNotFound:
        worksheet = sheet.add_worksheet(title=SHEET_NAME, rows=5000, cols=len(HISTORY_HEADERS))
        worksheet.append_row(HISTORY_HEADERS)
    worksheet.append_rows(_snapshot_rows(period_label, ranks), value_input_option="USER_ENTERED")
    return worksheet.get_all_values()


def main() -> Path:
    parser = argparse.ArgumentParser(description="Post a weekly NISA fund-flow heatmap.")
    parser.add_argument("--weeks", type=int, default=10)
    parser.add_argument("--funds", type=int, default=15)
    parser.add_argument("--limit", type=int, default=20, help="Rakuten ranking rows to retain per week")
    parser.add_argument("--gsheet-id", default=os.environ.get("GSHEET_ID", ""))
    parser.add_argument("--post", action="store_true")
    args = parser.parse_args()

    if not args.gsheet_id:
        raise SystemExit("GSHEET_ID or --gsheet-id is required")
    html_text = fetch_rakuten_html("weekly")
    period_label, ranks = parse_ranking(html_text, args.limit)
    history_rows = save_history_to_gsheet(args.gsheet_id, period_label, ranks)
    history = build_fund_flow_history(history_rows, max_weeks=args.weeks, max_funds=args.funds)
    output = OUTPUT_DIR / f"{datetime.now():%Y-%m-%d}_fund_flow_map.png"
    render_fund_flow_map(history, output)
    print(f"[fund-flow] 保存: {output}")

    if args.post:
        webhook = os.environ.get(WEBHOOK_ENV, "")
        if not webhook:
            raise SystemExit(f"{WEBHOOK_ENV} is not set")
        send_discord_image(
            webhook,
            output,
            f"**📊 NISA資金フローマップ（直近{len(history.weeks)}週・楽天NISA買付順位）**",
        )
    return output


if __name__ == "__main__":
    main()
