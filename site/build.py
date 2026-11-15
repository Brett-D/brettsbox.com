#!/usr/bin/env python3
"""Static site generator for brettsbox.com (Python 3 standard library only).

Content lives in site/content; the theme in site/themes/<theme> (set in site.json) supplies the
templates, partials and static files (CSS, JS, favicon). Running this script regenerates
everything in public/ except assets/ and 404.html, which are committed by hand:

    python site/build.py

To preview a theme without touching public/ (e.g. one copied back from archive/), build it into a scratch folder:

    python site/build.py --theme lab --out ../preview
"""
from __future__ import annotations

import argparse
import hashlib
import html
import json
import re
import shutil
import struct
import sys
from datetime import date, datetime, timezone
from pathlib import Path

SITE = Path(__file__).resolve().parent
ROOT = SITE.parent
PUBLIC = ROOT / "public"
CONTENT = SITE / "content"

CONFIG = json.loads((CONTENT / "site.json").read_text(encoding="utf-8"))
ORIGIN = CONFIG["origin"].rstrip("/")
THEME = SITE / "themes" / CONFIG["theme"]
# Everything else in public/ is generated and removed before each build.
KEEP = {"assets", "404.html"}
# Two designs were once on trial under /lab/ and /blueprint/; their old URLs redirect to the root.
LEGACY_PREFIXES = ("lab", "blueprint")


# --------------------------------------------------------------------------- helpers

def esc(text) -> str:
    return html.escape(str(text), quote=True)


def write(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "w", encoding="utf-8", newline="\n") as fh:
        fh.write(text)


def fill(template: str, values: dict, where: str) -> str:
    """Replace {{key}} placeholders; unknown keys are an error so typos surface."""

    def sub(match: re.Match) -> str:
        key = match.group(1)
        if key not in values:
            raise KeyError(f"{where}: no value for {{{{{key}}}}}")
        return str(values[key])

    return re.sub(r"\{\{([a-z_]+)\}\}", sub, template)


def parse_front_matter(path: Path) -> tuple[dict, str]:
    text = path.read_text(encoding="utf-8")
    if not text.startswith("---"):
        raise ValueError(f"{path}: missing front matter")
    _, head, body = text.split("---", 2)
    meta = {}
    for line in head.strip().splitlines():
        key, _, value = line.partition(":")
        value = value.strip()
        if len(value) >= 2 and value[0] == value[-1] == '"':
            value = value[1:-1]
        meta[key.strip()] = value
    return meta, body.strip() + "\n"


def image_size(path: Path) -> tuple[int, int]:
    data = path.read_bytes()[: 64 * 1024]
    if data[:8] == b"\x89PNG\r\n\x1a\n":
        return struct.unpack(">II", data[16:24])
    if data[:4] == b"RIFF" and data[8:12] == b"WEBP":
        chunk = data[12:16]
        if chunk == b"VP8X":
            return int.from_bytes(data[24:27], "little") + 1, int.from_bytes(data[27:30], "little") + 1
        if chunk == b"VP8L":
            b = data[21:25]
            w = 1 + (((b[1] & 0x3F) << 8) | b[0])
            h = 1 + (((b[3] & 0xF) << 10) | (b[2] << 2) | ((b[1] & 0xC0) >> 6))
            return w, h
        if chunk == b"VP8 ":
            w, h = struct.unpack("<HH", data[26:30])
            return w & 0x3FFF, h & 0x3FFF
    if data[:2] == b"\xff\xd8":
        i = 2
        while i < len(data):
            marker, length = data[i + 1], struct.unpack(">H", data[i + 2:i + 4])[0]
            if marker in (0xC0, 0xC1, 0xC2):
                h, w = struct.unpack(">HH", data[i + 5:i + 9])
                return w, h
            i += 2 + length
    raise ValueError(f"cannot read size of {path}")


def human_date(d: date) -> str:
    return f"{d.day} {d.strftime('%B %Y')}"


# --------------------------------------------------------------------------- content

def load_posts() -> list[dict]:
    posts = []
    for path in sorted((CONTENT / "posts").glob("*.html")):
        meta, body = parse_front_matter(path)
        meta["date"] = date.fromisoformat(meta["date"])
        meta["tags"] = [t.strip() for t in meta.get("tags", "").split(",") if t.strip()]
        meta["body"] = body
        words = len(re.sub(r"<[^>]+>|\{\{[^}]+\}\}", " ", body).split())
        meta["minutes"] = max(1, -(-words // 200))
        posts.append(meta)
    posts.sort(key=lambda p: p["date"])
    for i, post in enumerate(posts, 1):
        post["part"] = i
    return posts


def load_pages() -> dict[str, dict]:
    pages = {}
    for path in sorted((CONTENT / "pages").glob("*.html")):
        meta, body = parse_front_matter(path)
        meta["body"] = body
        pages[meta["slug"]] = meta
    return pages


# --------------------------------------------------------------------------- shortcodes

class Renderer:
    """Expands {{base}} and {{name:arg|arg}} shortcodes in content."""

    def __init__(self, posts: list[dict], partials: dict[str, str], feed: bool = False):
        self.base = ""
        self.posts = posts
        self.partials = partials
        self.feed = feed
        self.fig = 0

    def render(self, body: str) -> str:
        self.fig = 0
        body = body.replace("{{base}}", self.base)
        out = re.sub(r"\{\{([a-z]+):([^}]*)\}\}", self._shortcode, body)
        if self.feed:
            out = re.sub(r'(href|src|poster)="/', rf'\1="{ORIGIN}/', out)
        return out

    def _shortcode(self, match: re.Match) -> str:
        name, arg = match.group(1), match.group(2)
        handler = getattr(self, f"sc_{name}", None)
        if handler is None:
            raise KeyError(f"unknown shortcode {name}")
        return handler(*[a.strip() for a in arg.split("|")])

    def _figno(self) -> str:
        self.fig += 1
        return f'<span class="fig-no">Fig. {self.fig:02d}</span> '

    def sc_img(self, file: str, alt: str, caption: str = "", full: str = "", cls: str = "") -> str:
        w, h = image_size(PUBLIC / "assets" / "img" / file)
        cap = f"<figcaption>{self._figno()}{caption}</figcaption>" if caption else ""
        return (
            f'<figure class="figure {esc(cls)}" data-reveal>'
            f'<a class="figure__frame" href="/assets/img/{full or file}" title="Open full-size image">'
            f'<img src="/assets/img/{file}" alt="{esc(alt)}" width="{w}" height="{h}" loading="lazy" decoding="async"></a>'
            f"{cap}</figure>"
        )

    def sc_soon(self, caption: str, label: str = "Photo coming soon") -> str:
        if self.feed:
            return ""
        return (
            '<figure class="figure figure--soon" data-reveal>'
            f'<div class="soon" role="img" aria-label="Placeholder: {esc(label)}">'
            '<svg viewBox="0 0 48 48" aria-hidden="true" class="soon__icon"><path d="M6 15h9l3-5h12l3 5h9v24H6z" '
            'fill="none" stroke="currentColor" stroke-width="2.5" stroke-linejoin="round"/><circle cx="24" cy="26" r="7" '
            'fill="none" stroke="currentColor" stroke-width="2.5"/></svg>'
            f'<span class="soon__label">{esc(label)}</span></div>'
            f"<figcaption>{self._figno()}{caption}</figcaption></figure>"
        )

    def sc_video(self, key: str, caption: str = "") -> str:
        v = CONFIG["videos"][key]
        w, h = v["width"], v["height"]
        cap = f"<figcaption>{self._figno()}{caption or v['caption']}</figcaption>"
        if self.feed:
            return (
                f'<figure><a href="{v["mp4"]}"><img src="{v["poster"]}" alt="{esc(v["alt"])}" '
                f'width="{w}" height="{h}"></a>{cap}</figure>'
            )
        return (
            '<figure class="figure figure--video" data-reveal>'
            '<div class="video" data-video>'
            f'<video muted loop playsinline preload="metadata" controls width="{w}" height="{h}" '
            f'poster="{v["poster"]}" aria-label="{esc(v["alt"])}">'
            f'<source src="{v["webm"]}" type="video/webm">'
            f'<source src="{v["mp4"]}" type="video/mp4">'
            f'<a href="{v["mp4"]}">Download the demo video (MP4)</a></video>'
            '<button class="video__toggle" type="button" hidden>'
            '<span class="video__icon" aria-hidden="true"></span><span class="video__text">Play video</span></button>'
            f"</div>{cap}</figure>"
        )

    def sc_flow(self, key: str, caption: str = "") -> str:
        flow = CONFIG["flows"][key]
        items = "".join(
            f'<li class="flow__step"><span class="flow__n">{i:02d}</span>'
            f'<strong class="flow__title">{s["title"]}</strong>'
            f'<span class="flow__detail">{s["detail"]}</span></li>'
            for i, s in enumerate(flow["steps"], 1)
        )
        return (
            f'<figure class="flow flow--{esc(key)}" data-reveal><ol class="flow__steps">{items}</ol>'
            f"<figcaption>{self._figno()}{caption or flow['caption']}</figcaption></figure>"
        )

    def sc_model(self, key: str, poster: str, alt: str, caption: str = "") -> str:
        """Interactive WebGL model (theme static/{key}3d.js); the poster shows until it starts, and in feeds."""
        cap = f"<figcaption>{self._figno()}{caption}</figcaption>" if caption else ""
        path = PUBLIC / "assets" / "img" / poster
        img = ""
        if path.exists():
            w, h = image_size(path)
            img = f'<img class="model__poster" src="/assets/img/{poster}" alt="{esc(alt)}" width="{w}" height="{h}" loading="lazy" decoding="async">'
        if self.feed:
            return f"<figure>{img}{cap}</figure>"
        script = f"{key}3d.js"
        return (
            f'<figure class="figure figure--model" data-reveal><div class="model" data-model="{esc(key)}">{img}'
            f'<canvas class="model__canvas" tabindex="0" role="img" aria-label="{esc(alt)} Drag or use the arrow keys to turn it."></canvas></div>'
            f'{cap}<script src="/{script}?v={asset_version(script)}" defer></script></figure>'
        )

    def sc_posts(self, tag: str = "", limit: str = "") -> str:
        selected = [p for p in reversed(self.posts) if not tag or tag in p["tags"]]
        if limit:
            selected = selected[: int(limit)]
        if self.feed:
            return ""
        return post_list(selected, self.partials, self.base)


def post_list(posts: list[dict], partials: dict[str, str], base: str) -> str:
    items = [
        fill(
            partials["post_item"],
            {
                "href": f"{base}/blog/{p['slug']}/",
                "title": p["title"],
                "summary": p["summary"],
                "date_iso": p["date"].isoformat(),
                "date_human": human_date(p["date"]),
                "minutes": p["minutes"],
                "part": f"{p['part']:02d}",
                "tags": tag_list(p["tags"], partials),
            },
            "post_item",
        )
        for p in posts
    ]
    return fill(partials["post_list"], {"items": "\n".join(items)}, "post_list")


def tag_list(tags: list[str], partials: dict[str, str]) -> str:
    return "".join(fill(partials["tag"], {"tag": esc(t)}, "tag") for t in tags)


# --------------------------------------------------------------------------- page assembly

def load_theme() -> tuple[dict[str, str], dict[str, str]]:
    templates = {p.stem: p.read_text(encoding="utf-8") for p in (THEME / "templates").glob("*.html")}
    partials = {p.stem: p.read_text(encoding="utf-8").strip() for p in (THEME / "partials").glob("*.html")}
    return templates, partials


def nav_html(current: str, partials: dict[str, str]) -> str:
    return "\n".join(
        fill(
            partials["nav_item"],
            {
                "href": item["path"],
                "label": item["label"],
                "current": ' aria-current="page"' if current == item["key"] else "",
            },
            "nav_item",
        )
        for item in CONFIG["nav"]
    )


def og_tags(title: str, description: str, url: str, image: str, kind: str) -> str:
    tags = {
        "og:site_name": CONFIG["site_name"],
        "og:title": title,
        "og:description": description,
        "og:type": kind,
        "og:url": url,
        "og:image": image,
    }
    out = [f'<meta property="{k}" content="{esc(v)}">' for k, v in tags.items()]
    out.append('<meta name="twitter:card" content="summary_large_image">')
    return "\n".join(out)


def asset_version(name: str) -> str:
    """Short content hash for ?v= on CSS/JS URLs: the server caches them for a week."""
    return hashlib.sha256((THEME / "static" / name).read_bytes()).hexdigest()[:10]


def clean_public() -> None:
    for entry in PUBLIC.iterdir():
        if entry.name in KEEP:
            continue
        if entry.is_dir():
            shutil.rmtree(entry)
        else:
            entry.unlink()


def build_site(posts: list[dict], pages: dict[str, dict]) -> list[str]:
    templates, partials = load_theme()
    clean_public()
    shutil.copytree(THEME / "static", PUBLIC, dirs_exist_ok=True)
    renderer = Renderer(posts, partials)
    base = ""
    written: list[str] = []
    paths: list[str] = []
    og_default = f"{ORIGIN}/assets/img/og.png"
    versions = {"css_version": asset_version("style.css"), "js_version": asset_version("app.js")}

    def emit(path, nav_key, title, description, content, kind="website", image=og_default, body_class=""):
        full_title = title if title == CONFIG["site_name"] else f"{title} · {CONFIG['site_name']}"
        url = f"{ORIGIN}{path}"
        page = fill(
            templates["base"],
            {
                "title": esc(full_title),
                "description": esc(description),
                "canonical": url,
                "og": og_tags(full_title, description, url, image, kind),
                "base": base,
                "nav": nav_html(nav_key, partials),
                "content": content,
                "year": date.today().year,
                "body_class": body_class,
                "github": CONFIG["github"],
                **versions,
            },
            "base",
        )
        target = PUBLIC / path.strip("/") / "index.html"
        write(target, page)
        written.append(str(target.relative_to(PUBLIC)))
        paths.append(path)

    # Home
    project_cards = "\n".join(
        fill(
            partials["project_card"],
            {
                "href": f"{base}{proj['path']}",
                "title": proj["title"],
                "summary": proj["summary"],
                "status": proj["status"],
                "status_kind": proj["status_kind"],
                "accent": proj["accent"],
                "code": proj["code"],
                "tags": tag_list(proj["tags"], partials),
            },
            "project_card",
        )
        for proj in CONFIG["projects"]
    )
    home = CONFIG["home"]
    newest = posts[-1]
    home_html = fill(
        templates["home"],
        {
            "base": base,
            "intro": home["intro"],
            "tagline": home["tagline"],
            "featured_video": renderer.render("{{video:vslam|" + home["video_caption"] + "}}"),
            "featured_summary": home["featured_summary"],
            "status_pills": "".join(
                fill(partials["pill"], {"label": s["label"], "kind": s["kind"]}, "pill") for s in home["status"]
            ),
            "latest_posts": post_list(list(reversed(posts))[:3], partials, base),
            "project_cards": project_cards,
            "newest_title": newest["title"],
            "newest_href": f"{base}/blog/{newest['slug']}/",
            "newest_date": human_date(newest["date"]),
            "post_count": len(posts),
            "now_items": "".join(f"<li>{n}</li>" for n in home["now"]),
        },
        "home",
    )
    emit("/", "home", CONFIG["site_name"], CONFIG["description"], home_html, body_class="page-home")

    # Content pages
    for slug, page in pages.items():
        content = fill(
            templates["page"],
            {
                "title": page["title"],
                "eyebrow": page["eyebrow"],
                "lede": page["lede"],
                "body": renderer.render(page["body"]),
                "slug": slug,
                "scene": page.get("scene", ""),
                "base": base,
            },
            "page",
        )
        image = f"{ORIGIN}{page['image']}" if page.get("image") else og_default
        emit(f"/{slug}/", page.get("nav", slug), page["title"], page["description"], content,
             image=image, body_class=f"page-{slug}")

    # Blog index
    blog_html = fill(
        templates["blog"],
        {"post_list": post_list(list(reversed(posts)), partials, base), "base": base, "post_count": len(posts)},
        "blog",
    )
    emit("/blog/", "blog", "Build log", CONFIG["blog_description"], blog_html, body_class="page-blog")

    # Posts
    for i, post in enumerate(posts):
        def link(p, direction):
            if not p:
                return ""
            return fill(partials["post_nav"], {"href": f"{base}/blog/{p['slug']}/", "title": p["title"],
                                                "direction": direction, "part": f"{p['part']:02d}"}, "post_nav")

        content = fill(
            templates["post"],
            {
                "title": post["title"],
                "summary": post["summary"],
                "date_iso": post["date"].isoformat(),
                "date_human": human_date(post["date"]),
                "minutes": post["minutes"],
                "part": f"{post['part']:02d}",
                "total": f"{len(posts):02d}",
                "tags": tag_list(post["tags"], partials),
                "body": renderer.render(post["body"]),
                "prev": link(posts[i - 1] if i > 0 else None, "Previous"),
                "next": link(posts[i + 1] if i + 1 < len(posts) else None, "Next"),
                "scene": post.get("scene", ""),
                "base": base,
            },
            "post",
        )
        image = f"{ORIGIN}{post['image']}" if post.get("image") else og_default
        emit(f"/blog/{post['slug']}/", "blog", post["title"], post["summary"], content, kind="article",
             image=image, body_class="page-post")

    feed = atom_feed(posts, partials)
    write(PUBLIC / "feed.xml", feed)
    written.append("feed.xml")
    written += legacy_redirects(paths, feed)
    return written


REDIRECT = """<!doctype html>
<html lang="en"><head><meta charset="utf-8"><title>Moved · {site}</title>
<meta name="robots" content="noindex">
<link rel="canonical" href="{origin}{path}">
<meta http-equiv="refresh" content="0; url={path}">
<script>location.replace("{path}" + location.hash);</script>
</head><body><p>This page has moved to <a href="{path}">{origin}{path}</a>.</p></body></html>
"""


def legacy_redirects(paths: list[str], feed: str) -> list[str]:
    """Old /lab/... and /blueprint/... pages forward to the same page at the root; feeds are copied
    so existing subscriptions keep working."""
    written = []
    for prefix in LEGACY_PREFIXES:
        for path in paths:
            target = PUBLIC / prefix / path.strip("/") / "index.html"
            write(target, REDIRECT.format(site=esc(CONFIG["site_name"]), origin=ORIGIN, path=path))
            written.append(str(target.relative_to(PUBLIC)))
        write(PUBLIC / prefix / "feed.xml", feed)
        written.append(f"{prefix}/feed.xml")
    return written


def atom_feed(posts: list[dict], partials: dict[str, str]) -> str:
    renderer = Renderer(posts, partials, feed=True)
    base = ORIGIN
    entries = []
    for post in reversed(posts):
        url = f"{base}/blog/{post['slug']}/"
        stamp = datetime.combine(post["date"], datetime.min.time(), timezone.utc).isoformat()
        entries.append(
            "<entry>"
            f"<title>{esc(post['title'])}</title>"
            f'<link href="{url}"/>'
            f"<id>{url}</id>"
            f"<published>{stamp}</published><updated>{stamp}</updated>"
            f"<summary>{esc(post['summary'])}</summary>"
            f'<content type="html">{esc(renderer.render(post["body"]))}</content>'
            "</entry>\n"
        )
    updated = datetime.combine(max(p["date"] for p in posts), datetime.min.time(), timezone.utc).isoformat()
    return (
        '<?xml version="1.0" encoding="utf-8"?>\n'
        '<feed xmlns="http://www.w3.org/2005/Atom">\n'
        f"<title>{esc(CONFIG['site_name'])} build log</title>"
        f"<subtitle>{esc(CONFIG['blog_description'])}</subtitle>"
        f'<link href="{base}/feed.xml" rel="self"/>'
        f'<link href="{base}/"/>'
        f"<id>{base}/</id><updated>{updated}</updated>"
        f"<author><name>{esc(CONFIG['author'])}</name></author>\n"
        + "".join(entries)
        + "</feed>\n"
    )


def main(argv: list[str]) -> int:
    global THEME, PUBLIC
    parser = argparse.ArgumentParser(description="Build brettsbox.com into public/.")
    parser.add_argument("--theme", help="build with this theme from site/themes instead of the one in site.json")
    parser.add_argument("--out", help="build into this scratch folder instead of public/ (for previews); "
                                      "it is cleared except for assets/ and 404.html, which are copied from public/")
    args = parser.parse_args(argv)
    theme = args.theme or CONFIG["theme"]
    THEME = SITE / "themes" / theme
    if not THEME.is_dir():
        parser.error(f"no theme folder {THEME}")
    if args.out:
        out = Path(args.out).resolve()
        if out == PUBLIC or out in ROOT.parents or out == ROOT:
            parser.error(f"refusing to use {out} as a scratch folder")
        out.mkdir(parents=True, exist_ok=True)
        shutil.copytree(PUBLIC / "assets", out / "assets", dirs_exist_ok=True)
        shutil.copy2(PUBLIC / "404.html", out / "404.html")
        PUBLIC = out
    written = build_site(load_posts(), load_pages())
    print(f"Built {len(written)} files with the {theme} theme into {PUBLIC} "
          f"(including redirects from /{'/, /'.join(LEGACY_PREFIXES)}/).")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
