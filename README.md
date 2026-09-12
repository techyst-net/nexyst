# Nexyst

A full business-operations application: accounting, stock, buying, selling,
manufacturing, projects, assets, quality and support.

This is a **Frappe application**, not a standalone service. It installs into a
Frappe bench alongside the framework, which supplies the web server, the desk
UI, authentication, the ORM, the background worker and the REST/RPC API.

## Architecture

| Layer | Provided by |
|---|---|
| Desk UI, auth, ORM, workers, API | Frappe framework (separate install) |
| Business modules and DocTypes | this app (`erpnext/`) |
| Banking SPA | `banking/` — React + Vite, built into `/assets/erpnext/banking/` |
| Database | MariaDB 10.6+ (Postgres is only partially supported upstream) |
| Cache / queue / realtime | Redis — three separate instances |

## Local setup

Requires an existing Frappe bench. Install `bench` first, then:

```sh
bench init zeshan-bench --frappe-branch develop
cd zeshan-bench

bench get-app erpnext /path/to/03-erpnext
bench new-site zeshan.localhost
bench --site zeshan.localhost install-app erpnext
bench start
```

The desk UI is then at `http://zeshan.localhost:8000/app`.

Build the banking SPA when working on it:

```sh
yarn install     # runs banking/ install via postinstall
yarn build       # emits into /assets/erpnext/banking/
```

See [OPERATIONS.md](./OPERATIONS.md) for configuration keys, ports and
deployment requirements.

## Branding

Applied through the app's supported extension points rather than by patching the
framework:

- `erpnext/hooks.py` — app title, publisher, colour, logo URL, favicon, email
  brand image, transactional mail footer
- `erpnext/setup/install.py` — the `app_name` written to System Settings on
  install (this is what the desk UI displays), and the seeded help-menu links
- `erpnext/startup/__init__.py` — `product_name`
- `erpnext/public/scss/zeshan-theme.scss` — redefines the framework's CSS custom
  properties. This app's bundle loads after the framework stylesheet, so the
  palette applies to the whole desk without forking the framework.
- `erpnext/public/images/` — asset **contents** replaced, filenames kept so
  every existing reference still resolves

### Limitation

The desk shell is rendered by the Frappe framework, which is a separate
repository and is not part of this directory. The theme override above retints
it through the framework's own custom properties, which covers the palette,
radii and typeface. Anything the framework hard-codes outside those properties —
and the framework's own login-page wordmark — can only be changed by also
customising the framework install. Set the site's own logo and title through
**Website Settings** and **Navbar Settings** in the UI, which the framework
reads at runtime.

## Provenance and licence

GPLv3. See [UPSTREAM.md](./UPSTREAM.md), [license.txt](./license.txt) and
[attributions.md](./attributions.md). The licence text and copyright notices
must be retained, and source must be offered to anyone you distribute this
application to.
