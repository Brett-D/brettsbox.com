# Archived: the Lab design

**Lab** (dark lab notebook: bold Space Grotesk type, cyan-violet-pink gradients, an animated SVG robot map on
the home page) was brettsbox.com's design from the site's launch until 14 November 2026: first on trial at `/lab/`
next to Blueprint, then as the whole site at `/`. It was replaced by the current **Graphite** design.

This folder keeps it for reference. Nothing here is built or served.

| Path | What it is |
|---|---|
| `theme/` | The Lab theme as it was: templates, partials, `style.css`, `app.js`, favicon |
| `fonts/` | Space Grotesk (SIL Open Font License), which only Lab used |

The theme still fits the current build script. To preview it, copy it back and build it into a scratch folder
(Space Grotesk has to be back in `public/assets/fonts/` too):

```bash
cp -r archive/lab/theme site/themes/lab
cp archive/lab/fonts/* public/assets/fonts/
python site/build.py --theme lab --out ../preview
```

The last version of the site that used Lab, sources and generated output included, is tagged `lab-design` in git.
