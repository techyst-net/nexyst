# Zeshan ERP — Operations

> Shared infrastructure (Postgres, Redis, S3, SMTP, LLM …) is wired in
> already — see [../INFRA.md](../INFRA.md). This app runs at http://localhost:8020, http://localhost:9001.

## Generated configuration

Ready-to-copy config templates are in this directory:

- `site_config.example.json`
- `common_site_config.example.json`

ERPNext is configured by bench JSON files, not env vars, and the real ones live in your bench directory — so these are **examples with CHANGE_ME placeholders**, safe to commit. Copy them into `sites/<site>/site_config.json` and `sites/common_site_config.json`, then fill them in with `bench set-config`.

## Important: this app is not configured by environment variables

Unlike most products in this workspace, a Frappe application reads almost no
environment variables. This app's only one is `CI`, used by a single migration
patch. Configuration lives in **JSON config files** managed by bench:

| File | Scope |
|---|---|
| `sites/common_site_config.json` | shared by every site on the bench |
| `sites/<site>/site_config.json` | one specific site |

Set values with `bench set-config` rather than editing the files by hand:

```sh
bench set-config -g redis_cache redis://localhost:13000     # -g = global
bench --site zeshan.localhost set-config db_name zeshan_erp
```

Environment variables *do* apply if you deploy via the containerised route,
where an entrypoint translates them into these same keys. Those are listed at
the end.

## Ports

| Service | Port | Notes |
|---|---|---|
| Web (gunicorn/werkzeug) | `8000` | `bench start` default |
| Socket.io (realtime) | `9000` | separate Node process |
| Frontend asset watcher | `8080` | development only |
| MariaDB | `3306` | |
| Redis cache | `13000` | bench default |
| Redis queue | `11000` | bench default |
| Redis socketio | `12000` | bench default |

Redis must be **three separate instances**, not three databases on one instance.
Bench's `Procfile` starts three when developing; production requires three
configured services.

## Required configuration keys

Global (`common_site_config.json`):

| Key | Purpose |
|---|---|
| `db_host` | Database host |
| `db_port` | Database port |
| `redis_cache` | Cache instance URL |
| `redis_queue` | Background-job queue URL |
| `redis_socketio` | Realtime instance URL |
| `socketio_port` | Realtime port |

Per site (`site_config.json`):

| Key | Purpose |
|---|---|
| `db_name` | Site database name |
| `db_password` | Site database password |
| `encryption_key` | **Encrypts stored third-party credentials.** Generated on site creation. Losing or changing it makes every stored secret unrecoverable — back it up with the database. |
| `admin_password` | Initial Administrator password |
| `host_name` | Absolute site URL, used to build links in outbound email |

## Email

Outbound and inbound mail is configured **in the UI** (Email Account DocType),
not by config keys. The only related settings are:

| Key | Purpose |
|---|---|
| `mail_server`, `mail_port`, `use_tls`, `mail_login`, `mail_password` | Fallback outgoing SMTP if no Email Account is set up |
| `auto_email_id` | Default sender address |

## Production hardening

| Key | Recommended | Purpose |
|---|---|---|
| `developer_mode` | `0` | Must be `0`. When `1`, schema changes write back to app source files. |
| `maintenance_mode` | `0` | Set `1` during migrations. |
| `allow_tests` | `0` | |
| `server_script_enabled` | `0` unless required | Permits arbitrary server-side Python from the UI. |
| `disable_website_cache` | `0` | |
| `dns_multitenant` | `1` if serving several sites by hostname | |

## Integration credentials

These are entered through the UI and stored **encrypted in the database** using
`encryption_key`, not placed in config or environment:

- Payment gateways
- Google services (Maps, Calendar, Drive) — the app depends on `googlemaps`
- Bank feeds — the app depends on `plaid-python`
- Video/YouTube integration
- Taxes and shipping providers

## Containerised deployment variables

If you deploy with the standard Frappe container images, the entrypoint maps
these environment variables onto the config keys above:

| Variable | Maps to |
|---|---|
| `DB_HOST`, `DB_PORT` | `db_host`, `db_port` |
| `DB_ROOT_USER`, `DB_PASSWORD` | site creation credentials |
| `REDIS_CACHE`, `REDIS_QUEUE`, `REDIS_SOCKETIO` | the three Redis URLs |
| `SOCKETIO_PORT` | `socketio_port` |
| `FRAPPE_SITE_NAME_HEADER` | which site a request resolves to |
| `ADMIN_PASSWORD` | `admin_password` |
| `BENCH_SITE_NAME` / `SITE_NAME` | site created on first boot |
| `UPSTREAM_REAL_IP_ADDRESS` | reverse-proxy real-IP handling |

## Deployment requirements

- **MariaDB 10.6+** with `utf8mb4` and `barracuda` row format. Postgres support
  upstream is incomplete — use MariaDB.
- **Three Redis instances** (cache, queue, socketio).
- **wkhtmltopdf** (patched-Qt build) on the web and worker hosts. Without it,
  every PDF — invoices, quotations, statements — fails to render.
- **Background workers and the scheduler must run as separate processes.**
  Without them, scheduled work (repeat orders, stock reposting, subscriptions,
  email queue flushing) silently never runs:
  ```sh
  bench worker --queue short,default,long
  bench schedule
  ```
- Persistent volumes for `sites/` (uploaded files and private files live there).
- Run `bench --site <site> migrate` on every release before serving traffic.
- Back up the database **and** `encryption_key` together.
- Python `>=3.14`; Frappe framework `>=17.0.0-dev,<18`.
