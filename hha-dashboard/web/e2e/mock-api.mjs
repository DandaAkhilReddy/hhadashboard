// Tiny HTTP mock backend for Playwright E2E.
//
// Purpose: respond to every endpoint the pages-under-test fetch so the E2E
// suite never touches the real FastAPI / Postgres stack. Keeps the tests
// hermetic, fast, and CI-friendly.
//
// Coverage:
//   - GET /api/v1/operations/summary    (Overview tile + /operations)
//   - GET /api/v1/operations/sites-today
//   - GET /api/v1/operations/sites/:id
//   - GET /api/v1/finance/today
//   - GET /api/v1/finance/ar-aging
//   - GET /api/v1/clinical/summary
//   - GET /api/v1/people/summary
//   - GET /api/v1/alerts
//
// Anything else returns 404 so a missing mock surfaces loudly instead of
// silently looking like a real backend miss.
//
// Port comes from MOCK_API_PORT env var (default 8123).

import http from "node:http";

const PORT = Number(process.env.MOCK_API_PORT ?? 8123);

const SITES = [
  {
    id: 1,
    name: "Westside Regional",
    state: "FL",
    medical_director: "Dr. Aneja",
    md_status: "ACTIVE",
    liaison: "Crystal",
    census_today: 142,
    census_3mo_avg: 156,
    mtd_avg: 148,
    variance_pct: -9.0,
    open_shifts: 3,
    contract_end: "2027-12-31",
    annual_subsidy_usd: 250000,
  },
  {
    id: 2,
    name: "Woodmont Hospital",
    state: "FL",
    medical_director: "Dr. Reddy",
    md_status: "ACTIVE",
    liaison: "Crystal",
    census_today: 88,
    census_3mo_avg: 95,
    mtd_avg: 91,
    variance_pct: -7.4,
    open_shifts: 1,
    contract_end: "2027-06-30",
    annual_subsidy_usd: 180000,
  },
];

const ROUTES = new Map([
  [
    "GET /api/v1/operations/summary",
    {
      total_fl_census: 230,
      total_tx_census: 0,
      total_fl_3mo_avg: 251,
      census_variance_vs_avg: -8.4,
      sites_below_avg: 2,
      open_shifts_total: 4,
      fl_site_count: 2,
      tx_site_count: 0,
    },
  ],
  ["GET /api/v1/operations/sites-today", SITES],
  [
    "GET /api/v1/finance/today",
    {
      fl_daily_actual: 42000,
      fl_daily_target: 50000,
      fl_daily_delta: -8000,
      fl_source_system: "VENTRA_FL_ATHENA",
      tx_daily_actual: 0,
      tx_daily_target: 0,
      tx_daily_delta: 0,
      tx_source_system: "HHA_TX_MANUAL",
      fl_mtd_actual: 1100000,
      fl_mtd_target: 1500000,
      fl_mtd_pct: 73.3,
      ventra_fee_mtd: 33000,
    },
  ],
  [
    "GET /api/v1/finance/ar-aging",
    {
      fl_total_usd: 800000,
      fl_buckets: {
        bucket_0_30: 400000,
        bucket_31_60: 200000,
        bucket_61_90: 90000,
        bucket_91_120: 50000,
        bucket_over_120: 60000,
      },
      fl_over_120_pct: 7.5,
      fl_source_system: "VENTRA_FL_ATHENA",
      tx_total_usd: 0,
      tx_buckets: {
        bucket_0_30: 0,
        bucket_31_60: 0,
        bucket_61_90: 0,
        bucket_91_120: 0,
        bucket_over_120: 0,
      },
      tx_over_120_pct: 0,
      tx_source_system: "HHA_TX_MANUAL",
    },
  ],
  [
    "GET /api/v1/clinical/summary",
    {
      hp_24h_pct: 92.5,
      hp_24h_target: 90,
      dc_48h_pct: 88.0,
      dc_48h_target: 90,
      los_fl_days: 4.6,
      los_tx_days: 0,
      los_woodmont_watch_days: 5.8,
      los_woodmont_trend_days: 0.4,
      credentials_expiring_30d: 1,
      credentials_expiring_60d: 2,
      credentials_expiring_90d: 4,
    },
  ],
  [
    "GET /api/v1/people/summary",
    {
      headcount_w2: 25,
      headcount_1099: 8,
      headcount_total: 33,
      open_positions_total: 4,
      turnover_90d_pct: 6.0,
      below_fmv_count: 2,
    },
  ],
  ["GET /api/v1/alerts", []],
]);

function siteDetail(siteId) {
  const site = SITES.find((s) => s.id === siteId);
  if (!site) return null;
  return {
    ...site,
    entered_today: false,
    recent_entries: [],
  };
}

const server = http.createServer((req, res) => {
  // CORS so the browser-side fetch from /operations/[id] modal works.
  res.setHeader("Access-Control-Allow-Origin", "*");
  res.setHeader("Access-Control-Allow-Headers", "Authorization,Content-Type");
  res.setHeader("Access-Control-Allow-Methods", "GET,POST,OPTIONS");
  if (req.method === "OPTIONS") {
    res.writeHead(204);
    res.end();
    return;
  }

  const url = req.url ?? "/";
  const key = `${req.method} ${url.split("?")[0]}`;

  // Static map?
  if (ROUTES.has(key)) {
    res.writeHead(200, { "Content-Type": "application/json" });
    res.end(JSON.stringify(ROUTES.get(key)));
    return;
  }

  // Dynamic: GET /api/v1/operations/sites/:id
  const m = url.match(/^\/api\/v1\/operations\/sites\/(\d+)$/);
  if (req.method === "GET" && m) {
    const detail = siteDetail(Number(m[1]));
    if (!detail) {
      res.writeHead(404, { "Content-Type": "application/json" });
      res.end(JSON.stringify({ error: "site_not_found" }));
      return;
    }
    res.writeHead(200, { "Content-Type": "application/json" });
    res.end(JSON.stringify(detail));
    return;
  }

  res.writeHead(404, { "Content-Type": "application/json" });
  res.end(JSON.stringify({ error: "no_mock", path: url, method: req.method }));
});

server.listen(PORT, () => {
  console.log(`mock-api listening on http://localhost:${PORT}`);
});
