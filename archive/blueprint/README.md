# Archived: the Blueprint design

From the site's launch until 14 November 2026, brettsbox.com was published in two designs with identical
content, so one could be picked: **Lab** (`/lab/`) and **Blueprint** (`/blueprint/`, retro terminal meets
engineering drawing), with a "Pick a design" chooser at `/`. Lab was chosen; it is now the whole site at `/`,
and old `/lab/...` and `/blueprint/...` URLs redirect to the same page at the root.

This folder keeps Blueprint for reference. Nothing here is built or served.

| Path | What it is |
|---|---|
| `theme/` | The Blueprint theme as it was: templates, partials, `style.css`, `app.js`, favicon |
| `chooser-index.html` | The old "Pick a design" page |
| `og-blueprint.png`, `preview-blueprint.webp` | Its social-sharing card and chooser preview |

The theme expects the two-design build script (`/lab/` and `/blueprint/` prefixes, `sheet` and `cmd` fields).
The complete two-design site, sources and build script included, is tagged `blueprint-design` in git:

```bash
git checkout blueprint-design      # or: git worktree add ../brettsbox-blueprint blueprint-design
python site/build.py
```
