# Upstream source

| Field | Value |
|---|---|
| Upstream project | ERPNext |
| Source | https://github.com/frappe/erpnext |
| Branch adapted | `develop` (17.x) |
| Licence | GNU GPL v3 |
| Runtime dependency | Frappe framework (separate GPLv3 project, installed via bench) |
| Retained notices | `license.txt`, `attributions.md`, per-file GPL headers |

## Licence obligations

GPLv3 permits rebranding and redistribution, and requires that:

- the licence text and all copyright notices are retained — `license.txt`,
  `attributions.md` and the per-file headers are therefore left intact;
- **complete corresponding source is offered to anyone you distribute the
  application to**, including your modifications. Deploying it as a hosted
  service for your own users does not by itself trigger this (GPLv3 is not
  AGPL), but shipping the application to a customer does.

## Trademarks

The upstream name and logo are trademarks of their owner, and their trademark
policy requires that a modified distribution not carry them. Removing them, as
done here, is what that policy asks for — it is a requirement, not merely
permitted. Do not reintroduce the upstream name or logo into this product.

## Identifiers deliberately left unchanged

| Identifier | Why |
|---|---|
| `app_name = "erpnext"` | The Frappe module name. Every `/assets/erpnext/...` asset path, bench command and installed-app record resolves through it. |
| `erpnext/` package directory | Matches `app_name`; renaming breaks every import. |
| Asset *filenames* (`erpnext-logo.svg`, `erpnext-favicon.svg`) | Referenced from hooks, bundles, print formats and web templates. The **file contents** were replaced with the Zeshan mark, so nothing upstream is displayed. |
| Workspace/DocType `name` keys | Primary keys in the database. Only the shown `label` values were changed. |

## Pulling upstream fixes

```sh
git remote add upstream https://github.com/frappe/erpnext.git
git fetch upstream --depth=50
```

Branding changes are concentrated in `erpnext/hooks.py`, `erpnext/startup/__init__.py`,
`erpnext/setup/install.py`, `erpnext/public/images/`, `erpnext/public/scss/zeshan-theme.scss`
and a small number of JSON label fields.
