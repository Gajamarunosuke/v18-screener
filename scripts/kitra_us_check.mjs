#!/usr/bin/env node
/**
 * US V18 candidates -> TradingView KITRA confirmation.
 *
 * Requirements:
 * - TradingView Desktop/Chrome is running with CDP on localhost:9222.
 * - A TradingView chart tab has MaaSwing-KITRA loaded.
 *
 * Examples:
 *   node kitra_us_check.mjs --symbols ROST,AVGO --post-workspace
 *   node kitra_us_check.mjs --post
 */

import { createRequire } from 'node:module';
import { existsSync, mkdirSync, readFileSync, readdirSync, writeFileSync } from 'node:fs';
import { dirname, join, resolve } from 'node:path';
import { fileURLToPath } from 'node:url';

const __dirname = dirname(fileURLToPath(import.meta.url));
const PROJECT_DIR = resolve(__dirname, '..');
const DEFAULT_SECRET_ENV = 'D:\\60 Obsidian\\10_operations\\secrets\\.env';
const DEFAULT_MCP_DIR = 'D:\\60 Obsidian\\50_workspace\\tools\\tradingview-mcp';
const OUTPUT_DIR = process.env.US_WATCH_OUTPUT_DIR || join(PROJECT_DIR, 'us_watch_output');
const KITRA_CHART_URL = /shhiLFRE/;

function parseArgs(argv) {
  const args = {
    symbols: '',
    input: '',
    universe: 'nasdaq100',
    prefix: 'NASDAQ',
    cdpHost: 'localhost',
    cdpPort: 9222,
    waitMs: 5000,
    mcpDir: process.env.TRADINGVIEW_MCP_DIR || DEFAULT_MCP_DIR,
    postWorkspace: false,
    post: false,
  };
  for (let i = 2; i < argv.length; i += 1) {
    const arg = argv[i];
    if (arg === '--symbols') args.symbols = argv[++i] || '';
    else if (arg === '--input') args.input = argv[++i] || '';
    else if (arg === '--universe') args.universe = argv[++i] || args.universe;
    else if (arg === '--prefix') args.prefix = argv[++i] || '';
    else if (arg === '--cdp-host') args.cdpHost = argv[++i] || args.cdpHost;
    else if (arg === '--cdp-port') args.cdpPort = Number(argv[++i] || args.cdpPort);
    else if (arg === '--wait-ms') args.waitMs = Number(argv[++i] || args.waitMs);
    else if (arg === '--mcp-dir') args.mcpDir = argv[++i] || args.mcpDir;
    else if (arg === '--post-workspace') args.postWorkspace = true;
    else if (arg === '--post') args.post = true;
    else if (arg === '--help' || arg === '-h') {
      printHelp();
      process.exit(0);
    }
  }
  return args;
}

function printHelp() {
  console.log(`US KITRA checker

Usage:
  node scripts\\kitra_us_check.mjs [--symbols ROST,AVGO] [--input report.md] [--post-workspace|--post]

Options:
  --symbols        Comma-separated symbols. When omitted, reads the latest US V18 report.
  --input          Markdown report file from v18_screener_us.py.
  --prefix         TradingView exchange prefix. Default: NASDAQ. Use empty string for raw symbols.
  --wait-ms        Wait after symbol change. Default: 5000.
  --post-workspace Post KITRA results to workspace-us.
  --post           Post KITRA results to workspace-us and #81maa-us-watch.
`);
}

function loadEnvFile(path) {
  if (!path || !existsSync(path)) return;
  for (const line of readFileSync(path, 'utf8').split(/\r?\n/)) {
    const trimmed = line.trim();
    if (!trimmed || trimmed.startsWith('#') || !trimmed.includes('=')) continue;
    const idx = trimmed.indexOf('=');
    const key = trimmed.slice(0, idx).trim();
    let value = trimmed.slice(idx + 1).trim();
    if ((value.startsWith('"') && value.endsWith('"')) || (value.startsWith("'") && value.endsWith("'"))) {
      value = value.slice(1, -1);
    }
    if (key && process.env[key] === undefined) process.env[key] = value;
  }
}

function loadCdp(args) {
  const candidates = [
    () => createRequire(import.meta.url)('chrome-remote-interface'),
    () => createRequire(join(resolve(args.mcpDir), 'package.json'))('chrome-remote-interface'),
  ];
  for (const get of candidates) {
    try {
      return get();
    } catch {
      // Try the next resolver.
    }
  }
  throw new Error('chrome-remote-interface not found. Run from tradingview-mcp or pass --mcp-dir.');
}

function latestReport(universe) {
  if (!existsSync(OUTPUT_DIR)) return '';
  const suffix = `_v18_us_${universe}.md`;
  const files = readdirSync(OUTPUT_DIR)
    .filter((name) => name.endsWith(suffix))
    .sort()
    .reverse();
  return files.length ? join(OUTPUT_DIR, files[0]) : '';
}

function parseCandidatesFromReport(path) {
  const rows = [];
  const text = readFileSync(path, 'utf8');
  let headers = [];
  for (const line of text.split(/\r?\n/)) {
    const trimmed = line.trim();
    if (!trimmed.startsWith('|') || trimmed.includes('---')) continue;
    const cols = trimmed.split('|').slice(1, -1).map((col) => col.trim());
    if (cols.length < 2) continue;
    if (/^symbol$/i.test(cols[0])) {
      headers = cols.map((col) => col.toLowerCase());
      continue;
    }
    const symbol = cols[0].toUpperCase();
    if (!/^[A-Z][A-Z0-9.-]*$/.test(symbol)) continue;
    const closeIdx = headers.indexOf('close');
    const nearIdx = headers.indexOf('near');
    rows.push({
      symbol,
      name: cols[1] || symbol,
      close: closeIdx >= 0 ? cols[closeIdx] : '',
      near: nearIdx >= 0 ? cols[nearIdx] : '',
    });
  }
  return rows;
}

function parseCandidates(args) {
  if (args.symbols) {
    return args.symbols
      .split(',')
      .map((symbol) => symbol.trim().toUpperCase())
      .filter(Boolean)
      .map((symbol) => ({ symbol, name: symbol }));
  }
  const input = args.input || latestReport(args.universe);
  if (!input) throw new Error('No US V18 report found. Run v18_screener_us.py first or pass --symbols.');
  const rows = parseCandidatesFromReport(input);
  if (!rows.length) throw new Error(`No candidates found in ${input}`);
  console.log(`Loaded candidates from ${input}`);
  return rows;
}

function tvSymbol(symbol, prefix) {
  const clean = symbol.replace('-', '.');
  if (!prefix || clean.includes(':')) return clean;
  return `${prefix}:${clean}`;
}

function sleep(ms) {
  return new Promise((resolveSleep) => setTimeout(resolveSleep, ms));
}

async function ev(client, expression) {
  const res = await client.Runtime.evaluate({ expression, returnByValue: true, awaitPromise: true });
  if (res.exceptionDetails) {
    throw new Error(res.exceptionDetails.exception?.description || res.exceptionDetails.text || 'JS error');
  }
  return res.result?.value;
}

async function findKitra(client) {
  return ev(client, `
    (function() {
      var api = window.TradingViewApi && window.TradingViewApi._activeChartWidgetWV &&
        window.TradingViewApi._activeChartWidgetWV.value();
      if (!api || !api._chartWidget) return -1;
      var sources = api._chartWidget.model().model().dataSources();
      for (var i = 0; i < sources.length; i++) {
        var s = sources[i];
        if (!s.metaInfo) continue;
        try {
          if ((s.metaInfo().description || '').indexOf('KITRA') !== -1) return i;
        } catch(e) {}
      }
      return -1;
    })()
  `);
}

async function setSymbol(client, symbol, waitMs) {
  await ev(client, `
    (function() {
      return new Promise(function(resolveSymbol) {
        window.TradingViewApi._activeChartWidgetWV.value().setSymbol(${JSON.stringify(symbol)}, {});
        setTimeout(resolveSymbol, 500);
      });
    })()
  `);
  await sleep(waitMs);
}

async function getMetrics(client) {
  return ev(client, `
    (function() {
      try {
        var api = window.TradingViewApi._activeChartWidgetWV.value();
        var chart = api._chartWidget;
        var sources = chart.model().model().dataSources();
        for (var i = 0; i < sources.length; i++) {
          var s = sources[i];
          if (!s.metaInfo) continue;
          try {
            if ((s.metaInfo().description || '').indexOf('KITRA') === -1) continue;
          } catch(e) { continue; }
          if (s.reportData) {
            var rd = typeof s.reportData === 'function' ? s.reportData() : s.reportData;
            if (rd && typeof rd.value === 'function') rd = rd.value();
            if (rd && rd.performance && rd.performance.all) {
              var all = rd.performance.all;
              var perf = rd.performance;
              return {
                mode: 'strategy',
                totalTrades: all.totalTrades || 0,
                winningTrades: all.numberOfWiningTrades || 0,
                percentProfitable: all.percentProfitable || 0,
                netProfitPercent: all.netProfitPercent || 0,
                profitFactor: all.profitFactor || 0,
                avgTradePercent: all.avgTradePercent || 0,
                maxDrawdownPercent: perf.maxStrategyDrawDownPercent || 0
              };
            }
          }

          var studies = api.getAllStudies();
          for (var j = 0; j < studies.length; j++) {
            if ((studies[j].name || '').indexOf('KITRA') === -1) continue;
            var study = api.getStudyById(studies[j].id);
            var src = study && (study._study || study);
            var data = src && (src._lastBarValues || src._data);
            if (!data || !data._items || !data._end) break;
            var row = data._items[data._end - 1];
            var values = row && row.value ? Array.prototype.slice.call(row.value) : [];
            return {
              mode: 'indicator',
              barTime: values[0] || null,
              ma5: values[1] || null,
              ma20: values[2] || null,
              ma60: values[3] || null,
              weeklyBbUpper: values[4] || null,
              weeklyBbTrigger: values[5] || null,
              fitExcluded: values[6] ? 1 : 0,
              kitraShape: values[7] ? 1 : 0,
              outSignal: values[8] ? 1 : 0,
              kitraIn: values[10] ? 1 : 0,
              alertIn: values[11] ? 1 : 0,
              alertOut: values[12] ? 1 : 0
            };
          }
          return { error: 'KITRA data missing' };
        }
        return { error: 'KITRA not found' };
      } catch(e) {
        return { error: e.message };
      }
    })()
  `);
}

function pct(value) {
  return Number((Number(value || 0) * 100).toFixed(2));
}

function csvEscape(value) {
  const text = String(value ?? '');
  if (/[",\r\n]/.test(text)) return `"${text.replace(/"/g, '""')}"`;
  return text;
}

function saveResults(results, universe) {
  mkdirSync(OUTPUT_DIR, { recursive: true });
  const stamp = new Date(Date.now() + 9 * 60 * 60 * 1000).toISOString().slice(0, 10);
  const base = join(OUTPUT_DIR, `${stamp}_kitra_us_${universe}`);
  writeFileSync(`${base}.json`, JSON.stringify(results, null, 2), 'utf8');
  const header = [
    'symbol', 'name', 'tradingview_symbol', 'mode', 'passed', 'kitraIn', 'fitExcluded', 'outSignal',
    'ma5', 'ma20', 'ma60', 'totalTrades', 'winningTrades',
    'percentProfitable', 'netProfitPercent', 'profitFactor', 'avgTradePercent',
    'maxDrawdownPercent', 'notes',
  ];
  const rows = results.map((r) => header.map((key) => csvEscape(r[key] ?? '')).join(','));
  writeFileSync(`${base}.csv`, [header.join(','), ...rows].join('\n'), 'utf8');
  console.log(`Saved: ${base}.json`);
  console.log(`Saved: ${base}.csv`);
}

function buildDiscordMessage(results, universe) {
  const now = new Date(Date.now() + 9 * 60 * 60 * 1000);
  const stamp = now.toISOString().slice(0, 16).replace('T', ' ');
  const passed = results.filter((r) => r.passed);
  if (!results.length) return `**US KITRA ${universe} ${stamp} JST**\n確認対象なし`;
  const isIndicator = results.some((r) => r.mode === 'indicator');
  if (isIndicator) {
    if (!passed.length) {
      return `**US KITRA ${universe} ${stamp} JST — V18(${results.length}銘柄) → KITRA通過 0銘柄**\n本日の候補なし`;
    }
    const rows = [
      `${'Symbol'.padEnd(8)} ${'Name'.padEnd(18)} ${'Close'.padStart(8)} ${'Near'.padEnd(4)}`,
      '-'.repeat(44),
    ];
    for (const r of passed.slice(0, 25)) {
      const name = String(r.name || r.symbol).slice(0, 18);
      rows.push(
        `${String(r.symbol).padEnd(8)} ${name.padEnd(18)} ` +
        `${String(r.close ?? '-').padStart(8)} ${String(r.near ?? '-').padEnd(4)}`
      );
    }
    const more = passed.length > 25 ? `\n...and ${passed.length - 25} more` : '';
    return [
      `**US KITRA ${universe} ${stamp} JST — V18(${results.length}銘柄) → KITRA通過 ${passed.length}銘柄**`,
      '```',
      ...rows,
      '```',
      more,
    ].join('\n');
  }
  const rows = [
    `${'Symbol'.padEnd(8)} ${'Name'.padEnd(18)} ${'Trades'.padStart(6)} ${'Win%'.padStart(6)} ${'PF'.padStart(5)} ${'Net%'.padStart(7)} ${'DD%'.padStart(6)}`,
    '-'.repeat(64),
  ];
  for (const r of results.slice(0, 20)) {
    const name = String(r.name || r.symbol).slice(0, 18);
    rows.push(
      `${String(r.symbol).padEnd(8)} ${name.padEnd(18)} ` +
      `${String(r.totalTrades ?? '-').padStart(6)} ${String(r.percentProfitable ?? '-').padStart(6)} ` +
      `${String(r.profitFactor ?? '-').padStart(5)} ${String(r.netProfitPercent ?? '-').padStart(7)} ` +
      `${String(r.maxDrawdownPercent ?? '-').padStart(6)}`
    );
  }
  const more = results.length > 20 ? `\n...and ${results.length - 20} more` : '';
  return [
    `**US KITRA ${universe} ${stamp} JST** — **${results.length}銘柄**確認`,
    '```',
    ...rows,
    '```',
    more,
  ].join('\n');
}

async function postJson(url, payload, headers = {}) {
  const response = await fetch(url, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json', 'User-Agent': 'MaaSwing-US-KITRA', ...headers },
    body: JSON.stringify(payload),
  });
  if (!response.ok) throw new Error(`${response.status} ${await response.text()}`);
}

async function findDiscordChannelId(token, guildId, channelName) {
  const response = await fetch(`https://discord.com/api/v10/guilds/${guildId}/channels`, {
    headers: { Authorization: `Bot ${token}`, 'User-Agent': 'MaaSwing-US-KITRA' },
  });
  if (!response.ok) throw new Error(`${response.status} ${await response.text()}`);
  const channels = await response.json();
  const channel = channels.find((item) => {
    const name = String(item.name || '');
    return name === channelName || name.startsWith(channelName);
  });
  return channel ? String(channel.id || '') : '';
}

async function postToTarget(content, config) {
  const webhookEnvs = Array.isArray(config.webhookEnv) ? config.webhookEnv : [config.webhookEnv];
  const webhook = webhookEnvs.map((name) => process.env[name] || '').find(Boolean) || '';
  if (webhook) {
    await postJson(webhook, { content });
    console.log(`Posted: ${config.label} via webhook`);
    return;
  }
  const token = process.env.DISCORD_BOT_TOKEN || '';
  const guildId = process.env.DISCORD_GUILD_ID || '';
  let channelId = process.env[config.channelEnv] || '';
  if (token && !channelId && guildId) {
    channelId = await findDiscordChannelId(token, guildId, config.channelName);
  }
  if (!token || !channelId) throw new Error(`${config.label} target is not configured`);
  await postJson(
    `https://discord.com/api/v10/channels/${channelId}/messages`,
    { content },
    { Authorization: `Bot ${token}` },
  );
  console.log(`Posted: ${config.label} via bot token`);
}

async function postResults(results, universe, targets) {
  const content = buildDiscordMessage(results, universe);
  const configs = {
    workspace: {
      label: 'workspace-us',
      webhookEnv: [
        'DISCORD_WEBHOOK_WORKSPACE_US',
        'DISCORD_WEBHOOK_workspace-us',
        'DISCORD_WEBHOOK_KITRA_WORKSPACE',
      ],
      channelEnv: 'US_WORKSPACE_CHANNEL_ID',
      channelName: 'workspace-us',
    },
    uswatch: {
      label: '81maa-us-watch',
      webhookEnv: ['DISCORD_WEBHOOK_US_WATCH', 'DISCORD_WEBHOOK_81maa-us-watch', 'DISCORD_WEBHOOK_KITRA'],
      channelEnv: 'US_WATCH_POST_CHANNEL_ID',
      channelName: '81maa-us-watch',
    },
  };
  for (const target of targets) {
    await postToTarget(content, configs[target]);
  }
}

async function main() {
  const args = parseArgs(process.argv);
  loadEnvFile(join(PROJECT_DIR, '.env'));
  loadEnvFile(DEFAULT_SECRET_ENV);

  const CDP = loadCdp(args);
  const candidates = parseCandidates(args);
  console.log(`US KITRA candidates: ${candidates.length}`);

  const listResp = await fetch(`http://${args.cdpHost}:${args.cdpPort}/json/list`);
  if (!listResp.ok) throw new Error(`CDP list failed: ${listResp.status}`);
  const targets = await listResp.json();
  const target = targets.find((item) => item.type === 'page' && KITRA_CHART_URL.test(item.url))
    || targets.find((item) => item.type === 'page' && /tradingview\.com\/chart/i.test(item.url));
  if (!target) throw new Error(`TradingView chart page not found on ${args.cdpHost}:${args.cdpPort}`);

  const client = await CDP({ host: args.cdpHost, port: args.cdpPort, target: target.id });
  await client.Runtime.enable();
  try {
    const kitraIdx = await findKitra(client);
    if (kitraIdx < 0) throw new Error('KITRA not found. Load MaaSwing-KITRA on the chart.');
    console.log(`KITRA found at source index ${kitraIdx}`);

    const results = [];
    for (let i = 0; i < candidates.length; i += 1) {
      const item = candidates[i];
      const tradingviewSymbol = tvSymbol(item.symbol, args.prefix);
      process.stdout.write(`[${String(i + 1).padStart(2, '0')}/${candidates.length}] ${tradingviewSymbol} ... `);
      try {
        await setSymbol(client, tradingviewSymbol, args.waitMs);
        let metrics = await getMetrics(client);
        if (metrics.error || (metrics.mode === 'strategy' && metrics.totalTrades === 0)) {
          await sleep(2500);
          metrics = await getMetrics(client);
        }
        if (metrics.error) {
          console.log(`ERROR: ${metrics.error}`);
          results.push({ symbol: item.symbol, name: item.name, tradingview_symbol: tradingviewSymbol, notes: metrics.error });
          continue;
        }
        let row;
        if (metrics.mode === 'indicator') {
          row = {
            symbol: item.symbol,
            name: item.name,
            tradingview_symbol: tradingviewSymbol,
            mode: metrics.mode,
            passed: Boolean(metrics.kitraIn),
            kitraIn: metrics.kitraIn,
            fitExcluded: metrics.fitExcluded,
            outSignal: metrics.outSignal,
            close: item.close || '',
            near: item.near || '',
            ma5: Number(Number(metrics.ma5 || 0).toFixed(2)),
            ma20: Number(Number(metrics.ma20 || 0).toFixed(2)),
            ma60: Number(Number(metrics.ma60 || 0).toFixed(2)),
            notes: '',
          };
          results.push(row);
          console.log(`KITRA=${row.kitraIn ? 'IN' : '-'} FIT=${row.fitExcluded ? 'NG' : '-'} OUT=${row.outSignal ? 'OUT' : '-'}`);
          continue;
        }
        row = {
          symbol: item.symbol,
          name: item.name,
          tradingview_symbol: tradingviewSymbol,
          mode: metrics.mode || 'strategy',
          passed: Boolean(metrics.totalTrades),
          close: item.close || '',
          near: item.near || '',
          totalTrades: metrics.totalTrades,
          winningTrades: metrics.winningTrades,
          percentProfitable: pct(metrics.percentProfitable),
          netProfitPercent: pct(metrics.netProfitPercent),
          profitFactor: Number(Number(metrics.profitFactor || 0).toFixed(3)),
          avgTradePercent: pct(metrics.avgTradePercent),
          maxDrawdownPercent: pct(metrics.maxDrawdownPercent),
          notes: '',
        };
        results.push(row);
        console.log(`trades=${row.totalTrades} win%=${row.percentProfitable} PF=${row.profitFactor} net%=${row.netProfitPercent}`);
      } catch (error) {
        console.log(`ERROR: ${error.message}`);
        results.push({ symbol: item.symbol, name: item.name, tradingview_symbol: tradingviewSymbol, notes: error.message });
      }
    }

    saveResults(results, args.universe);
    if (args.post || args.postWorkspace) {
      await postResults(results, args.universe, args.post ? ['workspace', 'uswatch'] : ['workspace']);
    }
  } finally {
    await client.close();
  }
}

main().catch((error) => {
  console.error(`Fatal: ${error.message}`);
  process.exit(1);
});
