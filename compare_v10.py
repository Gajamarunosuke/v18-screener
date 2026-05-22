"""
compare_v10.py — Python V10スクリーナー結果 vs TradingView V10チェッカー 照合
結果をGoogle Spreadsheetの「TV照合(V10)」シートに書き込む
"""

import subprocess
import json
import time
import os
from datetime import datetime

import gspread
from google.oauth2.service_account import Credentials

# ── 設定 ──────────────────────────────────────────────────────────────────────
TV_MCP_DIR     = r"D:\60 Obsidian\50_workspace\tools\tradingview-mcp"
SPREADSHEET_ID = "1XUGNkIo6TbInJQOHf6obZzUhJkJ3MyzvkUDCTqAll_U"
CREDS_PATH     = os.environ.get(
    "GOOGLE_APPLICATION_CREDENTIALS",
    r"D:\60 Obsidian\10_operations\secrets\gen-lang-client-0065958770-f3c9915ed06e.json",
)

PYTHON_HITS = [
    "6742","4385","8058","5393","6586","6141","6651","9934","8015","6463",
    "4369","6962","3915","2585","6473","6817","4344","2121","9401","8151",
    "9678","4634","7717","4765","6104","5563","6929","4901","4021","6532",
    "6958","7868","4578","8233","2802","8511","9048","2432","7846","4825",
    "8173","7966","6807","6823","4043","7976","3099","7613","7276","6971",
    "4975","6594","9301","6617","6875","4186","3984","8308","4187","3104",
    "8387","4373","8086","6999","9831","8544","6845","1963","9336","6768",
    "5970","6779","5632","4933","4548","3105","6481","6376","4776","3741",
    "6254","6963","7733","9519","8558","5232","6134","6925","7995","6480",
]

# ── TV MCP ────────────────────────────────────────────────────────────────────

ENC = {"encoding": "utf-8", "errors": "replace"}


def tv_symbol(code: str) -> bool:
    r = subprocess.run(
        ["node", "src/cli/index.js", "symbol", f"TSE:{code}"],
        cwd=TV_MCP_DIR, capture_output=True, text=True, timeout=30, **ENC,
    )
    return r.returncode == 0


def tv_quote() -> dict | None:
    r = subprocess.run(
        ["node", "src/cli/index.js", "quote"],
        cwd=TV_MCP_DIR, capture_output=True, text=True, timeout=15, **ENC,
    )
    if r.returncode != 0:
        return None
    try:
        return json.loads(r.stdout)
    except Exception:
        return None


def tv_values() -> dict | None:
    r = subprocess.run(
        ["node", "src/cli/index.js", "values"],
        cwd=TV_MCP_DIR, capture_output=True, text=True, timeout=15, **ENC,
    )
    if r.returncode != 0:
        return None
    try:
        return json.loads(r.stdout)
    except Exception:
        return None


def get_v10_signal(code: str) -> dict:
    """TSE:CODEに切り替え → チャート確認 → V10_SIGNAL取得"""
    if not tv_symbol(code):
        return {"error": "symbol_fail"}

    for _ in range(10):
        time.sleep(2)
        q = tv_quote()
        if q and code in q.get("symbol", ""):
            break
    else:
        return {"error": "symbol_not_loaded"}

    for _ in range(10):
        time.sleep(3)
        data = tv_values()
        if data and data.get("study_count", 0) > 0:
            break
    else:
        return {"error": "values_empty"}

    result = {"v10_signal": None, "daily_ok": None, "weekly_up": None}
    for study in data.get("studies", []):
        if study["name"] == "V10チェッカー":
            v = study["values"]
            result["v10_signal"] = int(float(v.get("V10_SIGNAL", 0)))
            result["daily_ok"]   = int(float(v.get("DAILY_OK",   0)))
            result["weekly_up"]  = int(float(v.get("WEEKLY_UP",  0)))
            break
    return result


# ── 照合ロジック ──────────────────────────────────────────────────────────────

def run_compare() -> list[dict]:
    total = len(PYTHON_HITS)
    results = []

    for i, code in enumerate(PYTHON_HITS, 1):
        print(f"  [{i:2d}/{total}] {code} ...", end=" ", flush=True)
        sig = get_v10_signal(code)

        if "error" in sig:
            verdict = "エラー"
            print(f"[ERR] {sig['error']}")
        elif sig["v10_signal"] == 1:
            verdict = "一致(IN)"
            print("[OK] IN発火")
        elif sig["daily_ok"] == 1:
            verdict = "条件OK/保有中"
            print("[OK] 条件OK・INなし（保有中？）")
        else:
            verdict = "不一致"
            print("[NG] 条件NG")

        results.append({
            "code":       code,
            "verdict":    verdict,
            "v10_signal": sig.get("v10_signal"),
            "daily_ok":   sig.get("daily_ok"),
            "weekly_up":  sig.get("weekly_up"),
        })

    return results


# ── 集計 ──────────────────────────────────────────────────────────────────────

def summarize(results: list[dict]) -> dict:
    counts = {"一致(IN)": 0, "条件OK/保有中": 0, "不一致": 0, "エラー": 0}
    by_verdict = {k: [] for k in counts}
    for r in results:
        v = r["verdict"]
        counts[v] = counts.get(v, 0) + 1
        by_verdict[v].append(r["code"])
    return {"counts": counts, "by_verdict": by_verdict}


# ── Spreadsheet書き込み ────────────────────────────────────────────────────────

def save_to_gsheet(results: list[dict], summary: dict):
    scopes = [
        "https://www.googleapis.com/auth/spreadsheets",
        "https://www.googleapis.com/auth/drive",
    ]
    creds = Credentials.from_service_account_file(CREDS_PATH, scopes=scopes)
    gc    = gspread.authorize(creds)
    sh    = gc.open_by_key(SPREADSHEET_ID)

    today    = datetime.now().strftime("%Y-%m-%d")
    run_time = datetime.now().strftime("%H:%M")

    try:
        ws = sh.worksheet("TV照合(V10)")
        ws.clear()
    except gspread.exceptions.WorksheetNotFound:
        ws = sh.add_worksheet(title="TV照合(V10)", rows=200, cols=8)

    rows = [[f"V10 Python vs TV 照合結果  {today} {run_time}"]]
    rows.append([])
    rows.append(["【サマリー】"])
    rows.append(["判定", "件数", "銘柄コード一覧"])
    for verdict, count in summary["counts"].items():
        rows.append([verdict, count, ", ".join(summary["by_verdict"][verdict])])

    total = len(results)
    match = summary["counts"]["一致(IN)"] + summary["counts"]["条件OK/保有中"]
    rows.append(["一致率（IN+条件OK）", f"{match}/{total}", f"{match/total*100:.1f}%"])
    rows.append([])
    rows.append(["【明細】"])
    rows.append(["コード", "判定", "V10_SIGNAL", "DAILY_OK", "WEEKLY_UP"])
    for r in results:
        rows.append([r["code"], r["verdict"], r["v10_signal"], r["daily_ok"], r["weekly_up"]])

    ws.update(rows, value_input_option="USER_ENTERED")
    print(f"\n[照合] Spreadsheet書き込み完了: TV照合(V10)シート")


# ── メイン ───────────────────────────────────────────────────────────────────

if __name__ == "__main__":
    print(f"\n{'='*55}")
    print(f"V10 Python vs TradingView 照合")
    print(f"対象: {len(PYTHON_HITS)}銘柄")
    print(f"{'='*55}\n")

    results = run_compare()
    summary = summarize(results)

    print(f"\n{'='*55}")
    for verdict, count in summary["counts"].items():
        codes = ", ".join(summary["by_verdict"][verdict])
        print(f"{verdict}: {count}銘柄", end="")
        print(f" -> {codes}" if codes else "")

    total = len(results)
    match = summary["counts"]["一致(IN)"] + summary["counts"]["条件OK/保有中"]
    print(f"\n一致率（IN+条件OK）: {match}/{total} = {match/total*100:.1f}%")

    save_to_gsheet(results, summary)
    print(f"\n完了。スプレッドシートの「TV照合(V10)」シートを確認してください。")
