from __future__ import annotations

from collections import Counter, defaultdict
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path

import pandas as pd


@dataclass(frozen=True)
class SectorHeatmap:
    dates: list[str]
    daily_totals: list[int]
    sectors: list[str]
    counts: dict[str, list[int]]
    daily_leaders: list[tuple[str, int]]


def load_jpx_sector_map(jpx_path: Path) -> dict[str, str]:
    frame = pd.read_excel(jpx_path)
    return {
        str(code).strip().zfill(4): str(sector).strip()
        for code, sector in zip(frame.iloc[:, 1], frame.iloc[:, 5])
        if str(sector).strip() not in {"", "-", "nan"}
    }


def _normalize_date(value: object) -> str:
    text = str(value).strip()
    for pattern in ("%Y-%m-%d", "%Y/%m/%d", "%Y-%m-%d %H:%M:%S"):
        try:
            return datetime.strptime(text, pattern).strftime("%Y-%m-%d")
        except ValueError:
            continue
    return ""


def aggregate_sector_history(
    rows: list[list[str]],
    sector_map: dict[str, str],
    max_days: int = 10,
    max_sectors: int = 15,
) -> SectorHeatmap:
    if not rows:
        return SectorHeatmap([], [], [], {}, [])

    headers = [str(value).strip() for value in rows[0]]
    try:
        date_index = headers.index("日付")
        code_index = headers.index("コード")
    except ValueError:
        return SectorHeatmap([], [], [], {}, [])

    codes_by_date: dict[str, set[str]] = defaultdict(set)
    observed_dates: set[str] = set()
    for row in rows[1:]:
        if len(row) <= max(date_index, code_index):
            continue
        date = _normalize_date(row[date_index])
        if date:
            observed_dates.add(date)
        code = str(row[code_index]).strip().split(".")[0].zfill(4)
        if date and code in sector_map:
            codes_by_date[date].add(code)

    dates = sorted(observed_dates)[-max_days:]
    if not dates:
        return SectorHeatmap([], [], [], {}, [])

    daily_counters = [
        Counter(sector_map[code] for code in codes_by_date[date])
        for date in dates
    ]
    sector_totals = Counter()
    for counter in daily_counters:
        sector_totals.update(counter)

    sectors = [
        sector
        for sector, _ in sorted(
            sector_totals.items(),
            key=lambda item: (-item[1], item[0]),
        )[:max_sectors]
    ]
    counts = {
        sector: [counter.get(sector, 0) for counter in daily_counters]
        for sector in sectors
    }
    leaders = [
        max(counter.items(), key=lambda item: (item[1], item[0]))
        if counter
        else ("候補なし", 0)
        for counter in daily_counters
    ]

    return SectorHeatmap(
        dates=dates,
        daily_totals=[sum(counter.values()) for counter in daily_counters],
        sectors=sectors,
        counts=counts,
        daily_leaders=leaders,
    )


def _font_path(bold: bool = False) -> str:
    if bold:
        candidates = [
            r"C:\Windows\Fonts\BIZ-UDGothicB.ttc",
            "/usr/share/fonts/opentype/noto/NotoSansCJK-Bold.ttc",
            # fonts-noto-cjk-extra が無い環境では Regular(CJK) にフォールバック。
            # DejaVu には日本語グリフが無く豆腐化するため、必ずCJKを優先する。
            "/usr/share/fonts/opentype/noto/NotoSansCJK-Regular.ttc",
            "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf",
        ]
    else:
        candidates = [
            r"C:\Windows\Fonts\BIZ-UDGothicR.ttc",
            "/usr/share/fonts/opentype/noto/NotoSansCJK-Regular.ttc",
            "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",
        ]
    for candidate in candidates:
        if Path(candidate).exists():
            return candidate
    raise FileNotFoundError("No usable TrueType font was found")


def _heat_color(value: int) -> tuple[int, int, int]:
    if value >= 8:
        return 19, 173, 112
    if value >= 4:
        return 45, 139, 103
    if value >= 2:
        return 48, 98, 82
    if value == 1:
        return 42, 65, 61
    return 31, 34, 45


def render_sector_heatmap(
    heatmap: SectorHeatmap,
    output_path: Path,
    title: str = "V18 業種シグナル・ヒートマップ",
) -> Path:
    from PIL import Image, ImageDraw, ImageFont

    if not heatmap.dates:
        raise ValueError("Heatmap history is empty")

    date_count = len(heatmap.dates)
    width = max(1400, 310 + date_count * 130)
    height = 310 + len(heatmap.sectors) * 48 + 90
    image = Image.new("RGB", (width, height), (18, 20, 27))
    draw = ImageDraw.Draw(image)

    regular = _font_path()
    bold = _font_path(bold=True)
    fonts = {
        "title": ImageFont.truetype(bold, 38),
        "subtitle": ImageFont.truetype(regular, 17),
        "header": ImageFont.truetype(bold, 19),
        "card": ImageFont.truetype(bold, 16),
        "label": ImageFont.truetype(regular, 18),
        "count": ImageFont.truetype(bold, 24),
        "small": ImageFont.truetype(regular, 14),
    }
    text = (238, 241, 247)
    muted = (157, 164, 181)
    accent = (92, 230, 158)
    panel = (28, 31, 42)

    draw.text((58, 36), title, font=fonts["title"], fill=text)
    period = f"{heatmap.dates[0].replace('-', '/')} - {heatmap.dates[-1][5:].replace('-', '/')}"
    draw.text(
        (60, 88),
        f"{period}  |  直近{date_count}営業日  |  セル内はヒット銘柄数",
        font=fonts["subtitle"],
        fill=muted,
    )

    left = 58
    label_width = 250
    table_width = width - left * 2
    cell_width = (table_width - label_width) / date_count

    card_top = 126
    card_height = 86
    for index, date in enumerate(heatmap.dates):
        x0 = left + index * (table_width / date_count)
        x1 = left + (index + 1) * (table_width / date_count) - 8
        draw.rounded_rectangle((x0, card_top, x1, card_top + card_height), 5, fill=panel)
        leader, count = heatmap.daily_leaders[index]
        leader_label = leader if len(leader) <= 6 else f"{leader[:6]}…"
        draw.text((x0 + 14, card_top + 10), date[5:].replace("-", "/"), font=fonts["header"], fill=muted)
        draw.text((x0 + 14, card_top + 40), f"{leader_label} {count}", font=fonts["card"], fill=accent)
        total_text = f"全{heatmap.daily_totals[index]}銘柄"
        total_box = draw.textbbox((0, 0), total_text, font=fonts["small"])
        draw.text((x1 - (total_box[2] - total_box[0]) - 12, card_top + 57), total_text, font=fonts["small"], fill=muted)

    table_top = 252
    row_height = 48
    draw.text((left + 10, table_top + 10), "業種", font=fonts["header"], fill=muted)
    for index, date in enumerate(heatmap.dates):
        x0 = left + label_width + index * cell_width
        label = date[5:].replace("-", "/")
        box = draw.textbbox((0, 0), label, font=fonts["header"])
        draw.text((x0 + (cell_width - (box[2] - box[0])) / 2, table_top + 10), label, font=fonts["header"], fill=text)

    for row_index, sector in enumerate(heatmap.sectors):
        y0 = table_top + row_height + row_index * row_height
        if row_index % 2 == 0:
            draw.rectangle((left, y0, left + label_width, y0 + row_height - 2), fill=panel)
        draw.text((left + 10, y0 + 12), sector, font=fonts["label"], fill=text)

        for column_index, value in enumerate(heatmap.counts[sector]):
            x0 = left + label_width + column_index * cell_width
            draw.rectangle(
                (x0 + 2, y0 + 2, x0 + cell_width - 2, y0 + row_height - 2),
                fill=_heat_color(value),
            )
            display = "-" if value == 0 else str(value)
            box = draw.textbbox((0, 0), display, font=fonts["count"])
            draw.text(
                (
                    x0 + (cell_width - (box[2] - box[0])) / 2,
                    y0 + (row_height - (box[3] - box[1])) / 2 - 2,
                ),
                display,
                font=fonts["count"],
                fill=text,
            )

    legend_y = table_top + row_height + len(heatmap.sectors) * row_height + 28
    draw.line((left, legend_y - 14, width - left, legend_y - 14), fill=(59, 64, 78), width=1)
    draw.text((left, legend_y), "濃さ:", font=fonts["small"], fill=muted)
    for index, (value, label) in enumerate(((1, "1"), (2, "2-3"), (4, "4-7"), (8, "8+"))):
        x0 = left + 68 + index * 110
        draw.rectangle((x0, legend_y, x0 + 34, legend_y + 22), fill=_heat_color(value))
        draw.text((x0 + 42, legend_y + 1), label, font=fonts["small"], fill=muted)

    output_path.parent.mkdir(parents=True, exist_ok=True)
    image.save(output_path, "PNG", optimize=True)
    return output_path
