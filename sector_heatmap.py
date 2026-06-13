from __future__ import annotations

import json
import urllib.request
import uuid
from collections import Counter, defaultdict
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path

import pandas as pd

# 小母数ノイズ抑制のための分母平滑化定数（割合 = ヒット ÷ (母数 + K)）
SMOOTH_K = 5


@dataclass(frozen=True)
class SectorHeatmap:
    dates: list[str]
    daily_totals: list[int]
    sectors: list[str]
    counts: dict[str, list[int]]
    daily_leaders: list[tuple[str, int]]
    # ハイブリッド用（母数を渡したときのみ埋まる。空なら従来の絶対数モード）
    denominators: dict[str, int] = field(default_factory=dict)
    ratios: dict[str, list[float]] = field(default_factory=dict)
    # 各業種が最新日から何営業日連続で点灯中か（テーマ持続性）
    streaks: dict[str, int] = field(default_factory=dict)


def load_jpx_sector_map(jpx_path: Path) -> dict[str, str]:
    frame = pd.read_excel(jpx_path)
    return {
        str(code).strip().zfill(4): str(sector).strip()
        for code, sector in zip(frame.iloc[:, 1], frame.iloc[:, 5])
        if str(sector).strip() not in {"", "-", "nan"}
    }


def load_jpx_sector_totals(jpx_path: Path, market_keyword: str = "プライム") -> dict[str, int]:
    """業種別の母数（プライム上場銘柄数）を返す。ハイブリッド表示の割合計算に使う。"""
    frame = pd.read_excel(jpx_path)
    frame.columns = [str(c).strip() for c in frame.columns]
    if market_keyword and "市場・商品区分" in frame.columns:
        frame = frame[frame["市場・商品区分"].astype(str).str.contains(market_keyword, na=False)]
    totals: Counter = Counter()
    for sector in frame.iloc[:, 5]:
        text = str(sector).strip()
        if text not in {"", "-", "nan"}:
            totals[text] += 1
    return dict(totals)


def _normalize_jp_code(value: object) -> str:
    """日本株コード: 末尾の小数表記を落として4桁ゼロ詰め（例 8306.0 → 8306）。"""
    return str(value).strip().split(".")[0].zfill(4)


def normalize_us_symbol(value: object) -> str:
    """米国ティッカー: 大文字化し、Wikipedia形式 BRK.B を yfinance形式 BRK-B に揃える。"""
    return str(value).strip().upper().replace(".", "-")


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
    sector_denominators: dict[str, int] | None = None,
    code_normalizer: Callable[[object], str] | None = None,
    date_header: str = "日付",
    code_header: str = "コード",
) -> SectorHeatmap:
    if not rows:
        return SectorHeatmap([], [], [], {}, [])

    normalize = code_normalizer or _normalize_jp_code
    headers = [str(value).strip() for value in rows[0]]
    try:
        date_index = headers.index(date_header)
        code_index = headers.index(code_header)
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
        code = normalize(row[code_index])
        if date and code in sector_map:
            codes_by_date[date].add(code)

    dates = sorted(observed_dates)[-max_days:]
    if not dates:
        return SectorHeatmap([], [], [], {}, [])

    daily_counters = [
        Counter(sector_map[code] for code in codes_by_date[date])
        for date in dates
    ]
    sector_sums: Counter = Counter()
    for counter in daily_counters:
        sector_sums.update(counter)

    hybrid = bool(sector_denominators)

    def _ratio(sector: str, count: int) -> float:
        denom = sector_denominators.get(sector, 0) if sector_denominators else 0
        return count / (denom + SMOOTH_K) * 100

    if hybrid:
        # 行の選択・並びは「期間合計の平滑化割合」降順（＝勢い順）
        ordered = sorted(
            sector_sums.items(),
            key=lambda item: (-_ratio(item[0], item[1]), item[0]),
        )
    else:
        # 従来：絶対数合計の降順
        ordered = sorted(
            sector_sums.items(),
            key=lambda item: (-item[1], item[0]),
        )
    sectors = [sector for sector, _ in ordered[:max_sectors]]

    counts = {
        sector: [counter.get(sector, 0) for counter in daily_counters]
        for sector in sectors
    }
    streaks: dict[str, int] = {}
    for sector in sectors:
        streak = 0
        for count in reversed(counts[sector]):
            if count < 1:
                break
            streak += 1
        streaks[sector] = streak

    if hybrid:
        ratios = {
            sector: [round(_ratio(sector, counter.get(sector, 0)), 2) for counter in daily_counters]
            for sector in sectors
        }
        denominators = {sector: int(sector_denominators.get(sector, 0)) for sector in sectors}
        # 日次リーダーは「平滑化割合」最大の業種（勢いベース）。表示用カウントは絶対数。
        leaders = [
            max(counter.items(), key=lambda item: (_ratio(item[0], item[1]), item[1], item[0]))
            if counter
            else ("候補なし", 0)
            for counter in daily_counters
        ]
    else:
        ratios = {}
        denominators = {}
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
        denominators=denominators,
        ratios=ratios,
        streaks=streaks,
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


def _heat_color_ratio(pct: float) -> tuple[int, int, int]:
    """割合(%)ベースの濃淡。母数で補正済みの『業種内シグナル比率』に使う。"""
    if pct >= 12:
        return 19, 173, 112
    if pct >= 6:
        return 45, 139, 103
    if pct >= 3:
        return 48, 98, 82
    if pct > 0:
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
    hybrid = bool(heatmap.ratios)
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
        "streak": ImageFont.truetype(bold, 13),
        "count": ImageFont.truetype(bold, 24),
        "small": ImageFont.truetype(regular, 14),
    }
    text = (238, 241, 247)
    muted = (157, 164, 181)
    accent = (92, 230, 158)
    panel = (28, 31, 42)

    draw.text((58, 36), title, font=fonts["title"], fill=text)
    period = f"{heatmap.dates[0].replace('-', '/')} - {heatmap.dates[-1][5:].replace('-', '/')}"
    subtitle = (
        f"{period}  |  直近{date_count}営業日  |  色＝業種内シグナル比率・数字＝銘柄数"
        if hybrid
        else f"{period}  |  直近{date_count}営業日  |  セル内はヒット銘柄数"
    )
    draw.text((60, 88), subtitle, font=fonts["subtitle"], fill=muted)

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
        streak = heatmap.streaks.get(sector, 0)
        if streak >= 2:
            streak_label = f"{streak}日連続"
            streak_box = draw.textbbox((0, 0), streak_label, font=fonts["streak"])
            draw.text(
                (left + label_width - (streak_box[2] - streak_box[0]) - 10, y0 + 15),
                streak_label,
                font=fonts["streak"],
                fill=accent,
            )

        for column_index, value in enumerate(heatmap.counts[sector]):
            x0 = left + label_width + column_index * cell_width
            cell_color = (
                _heat_color_ratio(heatmap.ratios[sector][column_index])
                if hybrid
                else _heat_color(value)
            )
            draw.rectangle(
                (x0 + 2, y0 + 2, x0 + cell_width - 2, y0 + row_height - 2),
                fill=cell_color,
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
    if hybrid:
        legend_entries = ((1.0, "<3%"), (4.0, "3-6%"), (8.0, "6-12%"), (13.0, "12%+"))
        legend_color = _heat_color_ratio
    else:
        legend_entries = ((1, "1"), (2, "2-3"), (4, "4-7"), (8, "8+"))
        legend_color = _heat_color
    for index, (value, label) in enumerate(legend_entries):
        x0 = left + 68 + index * 110
        draw.rectangle((x0, legend_y, x0 + 34, legend_y + 22), fill=legend_color(value))
        draw.text((x0 + 42, legend_y + 1), label, font=fonts["small"], fill=muted)

    output_path.parent.mkdir(parents=True, exist_ok=True)
    image.save(output_path, "PNG", optimize=True)
    return output_path


def send_discord_image(
    webhook_url: str,
    image_path: Path,
    content: str = "**業種シグナル・ヒートマップ（直近10営業日）**",
) -> None:
    """ヒートマップPNGをDiscordへmultipartで添付投稿する（V10/V18/US共通）。"""
    boundary = f"----Heatmap{uuid.uuid4().hex}"
    payload = json.dumps({"content": content}, ensure_ascii=False).encode("utf-8")
    image = image_path.read_bytes()

    parts = [
        f"--{boundary}\r\n".encode(),
        b'Content-Disposition: form-data; name="payload_json"\r\n',
        b"Content-Type: application/json; charset=utf-8\r\n\r\n",
        payload,
        b"\r\n",
        f"--{boundary}\r\n".encode(),
        (
            f'Content-Disposition: form-data; name="files[0]"; '
            f'filename="{image_path.name}"\r\n'
        ).encode(),
        b"Content-Type: image/png\r\n\r\n",
        image,
        b"\r\n",
        f"--{boundary}--\r\n".encode(),
    ]
    request = urllib.request.Request(
        webhook_url,
        data=b"".join(parts),
        headers={
            "Content-Type": f"multipart/form-data; boundary={boundary}",
            "User-Agent": "DiscordBot (https://github.com, 1.0)",
        },
    )
    urllib.request.urlopen(request, timeout=30)
    print(f"[heatmap] Discord画像送信完了: {image_path}")
