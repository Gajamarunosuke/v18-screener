"""
kitra_screener.py — V18結果にKITRAフィルターをかけてDiscordに投稿

V18スクリーナーがHITした銘柄を1つずつ TradingView の symbol TSE:xxxx で
チャート切り替えし、KITRAシグナルを読む。通過した銘柄をDiscordに投稿する。

手動実行用（TradingViewブラウザが開いている状態で実行）
"""

import os
import json
import re
import subprocess
import time
import urllib.request
from datetime import datetime
from pathlib import Path

import gspread
import pandas as pd
from google.oauth2.service_account import Credentials

# ── 設定 ──────────────────────────────────────────────────────────────────────
SCRIPT_DIR     = Path(__file__).resolve().parent
BASE_DIR       = SCRIPT_DIR.parent
SECRET_ENV     = Path(r"D:\60 Obsidian\10_operations\secrets\.env")
OUTPUT_DIR     = BASE_DIR / "output"
JPX_CACHE      = BASE_DIR / "data" / "storage" / "jpx_listing.xls"  # v18_screenerが取得・更新
TV_MCP_DIR     = os.environ.get("TRADINGVIEW_MCP_DIR", r"D:\60 Obsidian\50_workspace\tools\tradingview-mcp")
SPREADSHEET_ID = os.environ.get("KITRA_SPREADSHEET_ID") or os.environ.get("GSHEET_ID", "")
CREDS_PATH     = os.environ.get(
    "GOOGLE_APPLICATION_CREDENTIALS",
    r"D:\60 Obsidian\10_operations\secrets\gen-lang-client-0065958770-f3c9915ed06e.json",
)

ENC = {"encoding": "utf-8", "errors": "replace"}


def load_env_file(path: Path) -> None:
    """Load a simple KEY=VALUE env file without printing secret values."""
    if not path.exists():
        return
    for line in path.read_text(encoding="utf-8", errors="replace").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        key = key.strip()
        value = value.strip().strip('"').strip("'")
        if key and key not in os.environ:
            os.environ[key] = value


load_env_file(BASE_DIR / ".env")
load_env_file(SECRET_ENV)

SPREADSHEET_ID = os.environ.get("KITRA_SPREADSHEET_ID") or os.environ.get("GSHEET_ID", SPREADSHEET_ID)
DISCORD_WEBHOOKS = []
for webhook in [
    os.environ.get("DISCORD_WEBHOOK_KITRA", ""),
    os.environ.get("DISCORD_WEBHOOK_kitra", ""),
    os.environ.get("DISCORD_WEBHOOK_KITRA_WORKSPACE", ""),
    os.environ.get("DISCORD_WEBHOOK_workspace-jp", ""),
]:
    webhook = webhook.strip()
    if webhook and webhook not in DISCORD_WEBHOOKS:
        DISCORD_WEBHOOKS.append(webhook)


# ── JPX銘柄名マップ（コード→銘柄名）─────────────────────────────────────────────

def get_name_map() -> dict[str, str]:
    """v18_screenerが取得済みのJPXリストからコード→銘柄名の辞書を作る。"""
    if not JPX_CACHE.exists():
        print(f"[警告] JPXリスト未取得: {JPX_CACHE}（銘柄名は空欄になります）")
        return {}
    df = pd.read_excel(JPX_CACHE, header=0)
    df.columns = [str(c).strip() for c in df.columns]
    name_col = df.columns[2]  # 銘柄名
    return dict(zip(df["コード"].astype(str).str.zfill(4), df[name_col].astype(str)))


# ── V18結果をSpreadsheetから取得 ──────────────────────────────────────────────

def get_v18_results_from_latest_report(today: str | None = None) -> list[dict]:
    today = today or datetime.now().strftime("%Y-%m-%d")
    report = OUTPUT_DIR / f"{today}_v18_screener.md"
    if not report.exists():
        reports = sorted(OUTPUT_DIR.glob("*_v18_screener.md"), reverse=True)
        latest = f" Latest local report: {reports[0].name}." if reports else ""
        if reports and os.environ.get("KITRA_ALLOW_STALE_LOCAL_REPORT", "").strip() == "1":
            report = reports[0]
            print(f"    [警告] 今日のローカルV18結果がないため古いレポートを使用: {report.name}")
        else:
            raise SystemExit(
                "KITRA_SPREADSHEET_ID/GSHEET_ID is not configured, "
                f"and today's local V18 report does not exist: {report.name}."
                f"{latest} Run v18_screener.py first or configure KITRA_SPREADSHEET_ID."
            )

    rows = []
    for line in report.read_text(encoding="utf-8", errors="replace").splitlines():
        if not line.strip().startswith("| [["):
            continue
        cells = [c.strip() for c in line.strip().strip("|").split("|")]
        if len(cells) < 8:
            continue
        code_match = re.search(r"\[\[(\d{4})\]\]", cells[0])
        if not code_match:
            continue
        rows.append({
            "コード": code_match.group(1),
            "終値": cells[1],
            "MA距離(%)": cells[5],
            "近接": cells[6],
            "出来高(20均)": cells[7],
        })
    print(f"    Spreadsheet ID未設定のためローカルV18結果を使用: {report.name}")
    return rows

def get_v18_results() -> list[dict]:
    if not SPREADSHEET_ID:
        return get_v18_results_from_latest_report()
    scopes = [
        "https://www.googleapis.com/auth/spreadsheets",
        "https://www.googleapis.com/auth/drive",
    ]
    creds = Credentials.from_service_account_file(CREDS_PATH, scopes=scopes)
    gc = gspread.authorize(creds)
    sh = gc.open_by_key(SPREADSHEET_ID)
    ws = sh.worksheet("最新")  # V18スクリーナーの最新出力
    all_values = ws.get_all_values()
    if not all_values:
        return []
    # 先頭のバナー行（"V18スクリーナー … 実行"）をスキップし、
    # "コード" を含む行を本当の見出しとして検出する
    header_idx = next((i for i, row in enumerate(all_values) if "コード" in row), None)
    if header_idx is None:
        return []
    headers = all_values[header_idx]
    results = []
    for row in all_values[header_idx + 1:]:
        d = {}
        for i, h in enumerate(headers):
            if h:
                d[h] = row[i] if i < len(row) else ""
        if str(d.get("コード", "")).strip():
            results.append(d)
    return results


# ── TradingView MCP ────────────────────────────────────────────────────────────

def tv_run(cmd: list[str]) -> dict | None:
    r = subprocess.run(cmd, cwd=TV_MCP_DIR, capture_output=True, text=True, timeout=30, **ENC)
    try:
        return json.loads(r.stdout)
    except Exception:
        return None


def get_kitra_signal(code: str) -> bool:
    tv_run(["node", "src/cli/index.js", "symbol", f"TSE:{code}"])
    time.sleep(3)
    for _ in range(8):
        d = tv_run(["node", "src/cli/index.js", "values"])
        if d and d.get("study_count", 0) >= 2:
            break
        time.sleep(2)
    for s in (d or {}).get("studies", []):
        v = s.get("values", {})
        val = v.get("KITRA_IN") or v.get("▲ KITRA IN")
        if val is not None:
            try:
                return float(val) >= 1.0
            except Exception:
                return False
    return False


# ── Discord投稿 ───────────────────────────────────────────────────────────────

def send_discord(webhook: str, results: list[dict], today: str, total: int):
    header = f"**KITRAフィルター通過 {today} — V18({total}銘柄) → KITRA通過 {len(results)}銘柄**"
    if not results:
        content = f"{header}\n本日の候補なし"
    else:
        rows = [f"{'コード':<6} {'銘柄名'}", "-" * 30]
        for r in results:
            rows.append(f"{r.get('コード',''):<6} {r.get('銘柄名','')}")
        content = "\n".join([header, "```", *rows, "```"])

    payload = json.dumps({"content": content}).encode("utf-8")
    req = urllib.request.Request(
        webhook, data=payload,
        headers={"Content-Type": "application/json",
                 "User-Agent": "DiscordBot (https://github.com, 1.0)"},
    )
    urllib.request.urlopen(req, timeout=10)


# ── Spreadsheet書き込み ────────────────────────────────────────────────────────

def save_to_gsheet(results: list[dict], today: str, run_time: str):
    if not SPREADSHEET_ID:
        print("[Spreadsheet] KITRA_SPREADSHEET_ID/GSHEET_ID未設定のため保存をスキップ")
        return

    scopes = [
        "https://www.googleapis.com/auth/spreadsheets",
        "https://www.googleapis.com/auth/drive",
    ]
    creds = Credentials.from_service_account_file(CREDS_PATH, scopes=scopes)
    gc = gspread.authorize(creds)
    sh = gc.open_by_key(SPREADSHEET_ID)

    # 最新シート
    try:
        ws = sh.worksheet("最新(KITRA)")
        ws.clear()
    except gspread.exceptions.WorksheetNotFound:
        ws = sh.add_worksheet(title="最新(KITRA)", rows=200, cols=6)

    header = [["コード", "銘柄名", "終値", "MA距離(%)", "近接", "出来高(20均)"]]
    if results:
        data = [[r.get("コード",""), r.get("銘柄名",""), r.get("終値",""), r.get("MA距離(%)",""),
                 r.get("近接",""), r.get("出来高(20均)","")] for r in results]
    else:
        data = [["本日の候補なし"]]
    ws.update(header + data, value_input_option="USER_ENTERED")

    # 履歴シート
    try:
        hist = sh.worksheet("KITRA_履歴")
    except gspread.exceptions.WorksheetNotFound:
        hist = sh.add_worksheet(title="KITRA_履歴", rows=5000, cols=8)
        hist.append_row(["日付", "時刻", "コード", "銘柄名", "終値", "MA距離(%)", "近接", "出来高(20均)"])

    hist_rows = [[today, run_time, r.get("コード",""), r.get("銘柄名",""), r.get("終値",""),
                  r.get("MA距離(%)",""), r.get("近接",""), r.get("出来高(20均)","")]
                 for r in results] if results else [[today, run_time, "本日の候補なし"]]
    hist.append_rows(hist_rows, value_input_option="USER_ENTERED")
    print("[Spreadsheet] 書き込み完了: 最新(KITRA) / KITRA_履歴")


# ── メイン ───────────────────────────────────────────────────────────────────

if __name__ == "__main__":
    today    = datetime.now().strftime("%Y-%m-%d")
    run_time = datetime.now().strftime("%H:%M")

    print(f"\n{'='*55}")
    print(f"KITRAスクリーナー {today} {run_time}")
    print(f"{'='*55}")

    # V18結果取得
    print("\n[1] SpreadsheetからV18結果を取得中...")
    v18_rows = get_v18_results()
    print(f"    V18: {len(v18_rows)}銘柄")

    # 銘柄名マップ（JPXリスト）
    name_map = get_name_map()

    # KITRAフィルター
    print("\n[2] KITRAフィルター実行中...")
    kitra_pass = []
    total = len(v18_rows)
    for i, row in enumerate(v18_rows, 1):
        code = str(row.get("コード", "")).strip()
        name = name_map.get(code, "")
        row["銘柄名"] = name
        print(f"  [{i:2d}/{total}] {code} {name[:10]}...", end=" ", flush=True)
        passed = get_kitra_signal(code)
        if passed:
            kitra_pass.append(row)
            print("PASS")
        else:
            print("fail")

    print(f"\n[3] 結果: {len(kitra_pass)}/{total} がKITRA通過")

    # Discord投稿
    if DISCORD_WEBHOOKS:
        for idx, webhook in enumerate(DISCORD_WEBHOOKS, 1):
            send_discord(webhook, kitra_pass, today, total)
            print(f"[4] Discord投稿完了 ({idx}/{len(DISCORD_WEBHOOKS)})")
    else:
        print("[4] DISCORD_WEBHOOK_KITRA未設定のためスキップ")

    # Spreadsheet保存
    save_to_gsheet(kitra_pass, today, run_time)

    print(f"\n完了。")
