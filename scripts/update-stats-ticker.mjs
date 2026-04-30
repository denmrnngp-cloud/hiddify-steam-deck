#!/usr/bin/env node

import { existsSync, readFileSync, writeFileSync } from "node:fs";

const owner = process.env.GITHUB_REPOSITORY_OWNER || "denmrnngp-cloud";
const repo = (process.env.GITHUB_REPOSITORY || `${owner}/hiddify-steam-deck-vpn`).split("/")[1];
const historyPath = "assets/stats-history.json";
const tickerPath = "assets/stats-ticker.svg";
const token = process.env.GITHUB_TOKEN || "";
const headers = {
  Accept: "application/vnd.github+json",
  "X-GitHub-Api-Version": "2022-11-28",
  ...(token ? { Authorization: `Bearer ${token}` } : {}),
};

async function github(path) {
  const response = await fetch(`https://api.github.com/repos/${owner}/${repo}${path}`, { headers });
  if (!response.ok) {
    throw new Error(`${path}: ${response.status} ${response.statusText}`);
  }
  return response.json();
}

async function safeGithub(path, fallback) {
  try {
    return { ok: true, value: await github(path) };
  } catch (error) {
    console.warn(`warning: ${error.message}`);
    return { ok: false, value: fallback };
  }
}

async function safeGithubPages(path) {
  const items = [];
  for (let page = 1; page <= 10; page += 1) {
    const separator = path.includes("?") ? "&" : "?";
    const result = await safeGithub(`${path}${separator}page=${page}`, []);
    if (!result.ok || !Array.isArray(result.value)) return { ok: false, value: items };
    items.push(...result.value);
    if (result.value.length < 100) break;
  }
  return { ok: true, value: items };
}

function n(value) {
  return new Intl.NumberFormat("en-US").format(Number(value || 0));
}

function xml(value) {
  return String(value)
    .replaceAll("&", "&amp;")
    .replaceAll("<", "&lt;")
    .replaceAll(">", "&gt;")
    .replaceAll('"', "&quot;");
}

function readJson(path, fallback) {
  if (!existsSync(path)) return fallback;
  try {
    return JSON.parse(readFileSync(path, "utf8"));
  } catch (error) {
    console.warn(`warning: ${path}: ${error.message}`);
    return fallback;
  }
}

function latestPoint(points) {
  return points
    .filter((point) => point.timestamp)
    .toSorted((a, b) => new Date(b.timestamp) - new Date(a.timestamp))[0];
}

function findBaseline(points, targetTime) {
  return points
    .filter((point) => point.timestamp && new Date(point.timestamp).getTime() <= targetTime)
    .toSorted((a, b) => new Date(b.timestamp) - new Date(a.timestamp))[0];
}

const now = new Date();
const weekMs = 7 * 24 * 60 * 60 * 1000;
const historyMs = 45 * 24 * 60 * 60 * 1000;
const weekAgo = new Date(now.getTime() - weekMs);
const history = readJson(historyPath, { points: [] });
const historyPoints = Array.isArray(history.points) ? history.points : [];
const previous = latestPoint(historyPoints) || {};

const releasesResult = await safeGithubPages("/releases?per_page=100");
const releases = releasesResult.value;
let totalDownloads = releasesResult.ok ? 0 : previous.totalDownloads || 0;
let weeklyDownloads = 0;
for (const release of releases) {
  for (const asset of release.assets || []) {
    const downloadCount = asset.download_count || 0;
    totalDownloads += downloadCount;
    const publishedAt = release.published_at ? new Date(release.published_at) : null;
    if (publishedAt && publishedAt >= weekAgo) {
      weeklyDownloads += downloadCount;
    }
  }
}

const viewsResult = await safeGithub("/traffic/views", {
  count: previous.views14d || 0,
  uniques: previous.viewUniques14d || 0,
});
const clonesResult = await safeGithub("/traffic/clones", {
  count: previous.clones14d || 0,
  uniques: previous.cloneUniques14d || 0,
});
const repoInfoResult = await safeGithub("", { stargazers_count: previous.stars || 0 });
const views = viewsResult.value;
const clones = clonesResult.value;
const repoInfo = repoInfoResult.value;

const syntheticBaseline = {
  timestamp: weekAgo.toISOString(),
  totalDownloads: Math.max(0, totalDownloads - weeklyDownloads),
  synthetic: true,
};
const withBootstrap = historyPoints.length > 0 ? historyPoints : [syntheticBaseline];
const currentPoint = {
  timestamp: now.toISOString(),
  totalDownloads,
  stars: repoInfo.stargazers_count || 0,
  views14d: views.count || 0,
  viewUniques14d: views.uniques || 0,
  clones14d: clones.count || 0,
  cloneUniques14d: clones.uniques || 0,
};
const nextPoints = [...withBootstrap, currentPoint]
  .filter((point) => point.timestamp && new Date(point.timestamp).getTime() >= now.getTime() - historyMs)
  .toSorted((a, b) => new Date(a.timestamp) - new Date(b.timestamp));
const baseline = findBaseline(nextPoints, weekAgo.getTime());
if (baseline) {
  weeklyDownloads = Math.max(0, totalDownloads - (baseline.totalDownloads || 0));
}

const updated = now.toISOString().slice(0, 16).replace("T", " UTC ");
const parts = [
  `7-day downloads: ${n(weeklyDownloads)}`,
  `14-day visits: ${n(views.count)} (${n(views.uniques)} unique)`,
  `14-day clones: ${n(clones.count)} (${n(clones.uniques)} unique)`,
  `stars: ${n(repoInfo.stargazers_count)}`,
  "Скачал? Поставь звезду",
  "Downloaded? Star the repo",
  "下载后请给项目点星",
  `updated: ${updated}`,
];

const text = parts.join("   •   ");
const repeated = `${text}   •   ${text}`;

const svg = `<svg xmlns="http://www.w3.org/2000/svg" width="1280" height="56" viewBox="0 0 1280 56" role="img" aria-label="${xml(text)}">
  <defs>
    <linearGradient id="bg" x1="0" y1="0" x2="1280" y2="0" gradientUnits="userSpaceOnUse">
      <stop offset="0" stop-color="#07111f"/>
      <stop offset="0.5" stop-color="#0f1f33"/>
      <stop offset="1" stop-color="#07111f"/>
    </linearGradient>
  </defs>
  <rect width="1280" height="56" rx="14" fill="url(#bg)"/>
  <rect x="1" y="1" width="1278" height="54" rx="13" fill="none" stroke="#35f58a" stroke-opacity="0.28"/>
  <g font-family="ui-monospace, SFMono-Regular, Menlo, Consolas, monospace" font-size="18" font-weight="700" fill="#35f58a">
    <text y="35" xml:space="preserve">
      <tspan>${xml(repeated)}</tspan>
      <animate attributeName="x" from="0" to="-640" dur="22s" repeatCount="indefinite"/>
    </text>
  </g>
</svg>
`;

writeFileSync(historyPath, `${JSON.stringify({ points: nextPoints }, null, 2)}\n`);
writeFileSync(tickerPath, svg);
console.log(`updated ${tickerPath}: ${text}`);
