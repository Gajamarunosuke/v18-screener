# KITRAの使い方

ここに日本株KITRAと米国株KITRAの入口を集約しています。

クリックするもの:

```text
run_kitra_jp.bat    日本株KITRA
run_kitra_us.bat    米国株KITRA
```

どちらも、事前にTradingViewを開いて、チャートに `MaaSwing-KITRA` を表示しておきます。

日本株KITRAの流れ:

1. 日本株V18の最新結果をGoogle Spreadsheetから読む
2. `run_kitra_jp.bat` をクリックする
3. `scripts/kitra_jp_check.py` がTradingViewで1銘柄ずつ確認する
4. KITRA通過だけをDiscordへ投稿し、Spreadsheetへ保存する

米国株KITRAの流れ:

1. `v18_screener_us.py` がUS V18候補を作る
2. `run_kitra_us.bat` をクリックする
3. `scripts/kitra_us_check.mjs` がTradingViewで1銘柄ずつ確認する
4. KITRA通過だけを `workspace-us` に投稿する

出力先:

```text
us_watch_output/
```

手動で米国株の銘柄を指定する場合:

```powershell
node scripts\kitra_us_check.mjs --symbols ROST,AVGO --post-workspace
```

関連フォルダー:

```text
D:\60 Obsidian\50_workspace\projects\v18-screener\  日本株/米国株 V18・KITRAの入口
D:\60 Obsidian\50_workspace\tools\tradingview-mcp\   KNN Pine本体 / MCP
```

今後クリックする入口は、このフォルダーの `run_kitra_jp.bat` / `run_kitra_us.bat` に寄せます。
