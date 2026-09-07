/**
 * Vacuum Guardian - usage report endpoint (Cloudflare Worker + D1).
 *
 * Deploy this, put the resulting URL in `telemetry_url` (config.json), and
 * reports start arriving. Until that URL exists the app sends nothing, no
 * matter what the operator ticked.
 *
 *   wrangler d1 create vacuum-guardian
 *   wrangler d1 execute vacuum-guardian --file=schema.sql
 *   wrangler deploy
 *
 * schema.sql:
 *   CREATE TABLE reports (
 *     id            INTEGER PRIMARY KEY AUTOINCREMENT,
 *     received_at   TEXT NOT NULL,
 *     install_id    TEXT NOT NULL,
 *     app_version   TEXT,
 *     os_release    TEXT,
 *     os_build      TEXT,
 *     country       TEXT,
 *     language      TEXT,
 *     cycles        INTEGER,
 *     osai_minutes  REAL,
 *     uptime_minutes REAL,
 *     alarms        INTEGER,
 *     overrides     INTEGER,
 *     acknowledges  INTEGER,
 *     company       TEXT,
 *     name          TEXT,
 *     email         TEXT,
 *     phone         TEXT
 *   );
 *   CREATE INDEX reports_install ON reports (install_id);
 *
 * wrangler.toml needs the binding:
 *   [[d1_databases]]
 *   binding = "DB"
 *   database_name = "vacuum-guardian"
 *   database_id = "<from the create command>"
 */

const MAX_BODY = 8 * 1024; // a report is ~1 KB; anything larger is not ours

export default {
  async fetch(request, env) {
    if (request.method !== "POST") {
      return new Response("POST a usage report here", { status: 405 });
    }

    const raw = await request.text();
    if (raw.length > MAX_BODY) {
      return new Response("too large", { status: 413 });
    }

    let report;
    try {
      report = JSON.parse(raw);
    } catch {
      return new Response("invalid json", { status: 400 });
    }
    if (!report?.install_id) {
      return new Response("missing install_id", { status: 400 });
    }

    const system = report.system ?? {};
    const usage = report.usage ?? {};
    const operator = report.operator ?? {};

    await env.DB.prepare(
      `INSERT INTO reports (
         received_at, install_id, app_version, os_release, os_build, country,
         language, cycles, osai_minutes, uptime_minutes, alarms, overrides,
         acknowledges, company, name, email, phone
       ) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)`
    )
      .bind(
        new Date().toISOString(),
        String(report.install_id).slice(0, 64),
        report.app_version ?? null,
        system.os_release ?? null,
        system.os_build ?? null,
        system.country ?? null,
        system.language ?? null,
        usage.cycles ?? 0,
        usage.osai_minutes ?? 0,
        usage.uptime_minutes ?? 0,
        usage.alarms ?? 0,
        usage.overrides ?? 0,
        usage.acknowledges ?? 0,
        operator.company ?? null,
        operator.name ?? null,
        operator.email ?? null,
        operator.phone ?? null
      )
      .run();

    return new Response("ok");
  },
};
