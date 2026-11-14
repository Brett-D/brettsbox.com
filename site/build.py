#!/usr/bin/env python3
"""Static site generator for brettsbox.com (Python 3 standard library only).

Content lives in site/content (shared by every design variant); each variant in
site/themes/<name> supplies its own templates, partials and static files (CSS,
JS, favicon). Running this script regenerates public/<variant>/ for every
variant plus the root chooser page:

    python site/build.py
"""
from __future__ import annotations

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
THEMES = SITE / "themes"

CONFIG = json.loads((CONTENT / "site.json").read_text(encoding="utf-8"))
ORIGIN = CONFIG["origin"].rstrip("/")
VARIANTS = CONFIG["variants"]


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
    """Expands {{base}} and {{name:arg|arg}} shortcodes in shared content for one variant."""

    def __init__(self, variant: str, posts: list[dict], partials: dict[str, str], feed: bool = False):
        self.variant = variant
        self.base = f"/{variant}"
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

def load_theme(variant: str) -> tuple[dict[str, str], dict[str, str]]:
    folder = THEMES / variant
    templates = {p.stem: p.read_text(encoding="utf-8") for p in (folder / "templates").glob("*.html")}
    partials = {p.stem: p.read_text(encoding="utf-8").strip() for p in (folder / "partials").glob("*.html")}
    return templates, partials


def nav_html(variant: str, current: str, partials: dict[str, str]) -> str:
    return "\n".join(
        fill(
            partials["nav_item"],
            {
                "href": f"/{variant}{item['path']}",
                "label": item["label"],
                "cmd": item["cmd"],
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


def build_variant(variant: str, posts: list[dict], pages: dict[str, dict]) -> list[str]:
    vconf = VARIANTS[variant]
    other = next(v for v in VARIANTS if v != variant)
    templates, partials = load_theme(variant)
    out_dir = PUBLIC / variant
    if out_dir.exists():
        shutil.rmtree(out_dir)
    shutil.copytree(THEMES / variant / "static", out_dir)
    renderer = Renderer(variant, posts, partials)
    base = f"/{variant}"
    written: list[str] = []
    og_default = f"{ORIGIN}/assets/img/og-{variant}.png"

    def emit(path, nav_key, title, description, content, kind="website", image=og_default,
             body_class="", sheet=""):
        full_title = title if title == CONFIG["site_name"] else f"{title} · {CONFIG['site_name']}"
        url = f"{ORIGIN}{base}{path}"
        page = fill(
            templates["base"],
            {
                "title": esc(full_title),
                "description": esc(description),
                "canonical": url,
                "og": og_tags(full_title, description, url, image, kind),
                "base": base,
                "nav": nav_html(variant, nav_key, partials),
                "content": content,
                "switch_url": f"/{other}{path}",
                "other_name": VARIANTS[other]["name"],
                "variant_name": vconf["name"],
                "year": date.today().year,
                "body_class": body_class,
                "sheet": sheet or nav_key.upper(),
                "github": CONFIG["github"],
            },
            f"{variant}/base",
        )
        target = out_dir / path.strip("/") / "index.html" if path != "/" else out_dir / "index.html"
        write(target, page)
        written.append(str(target.relative_to(PUBLIC)))

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
        f"{variant}/home",
    )
    emit("/", "home", CONFIG["site_name"], CONFIG["description"], home_html, body_class="page-home", sheet="INDEX")

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
                "base": base,
            },
            f"{variant}/page",
        )
        image = f"{ORIGIN}{page['image']}" if page.get("image") else og_default
        emit(f"/{slug}/", page.get("nav", slug), page["title"], page["description"], content,
             image=image, body_class=f"page-{slug}", sheet=page.get("sheet", ""))

    # Blog index
    blog_html = fill(
        templates["blog"],
        {"post_list": post_list(list(reversed(posts)), partials, base), "base": base, "post_count": len(posts)},
        f"{variant}/blog",
    )
    emit("/blog/", "blog", "Build log", CONFIG["blog_description"], blog_html, body_class="page-blog", sheet="LOG")

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
                "base": base,
            },
            f"{variant}/post",
        )
        image = f"{ORIGIN}{post['image']}" if post.get("image") else og_default
        emit(f"/blog/{post['slug']}/", "blog", post["title"], post["summary"], content, kind="article",
             image=image, body_class="page-post", sheet=f"LOG-{post['part']:02d}")

    write(out_dir / "feed.xml", atom_feed(variant, posts, partials))
    written.append(f"{variant}/feed.xml")
    return written


def atom_feed(variant: str, posts: list[dict], partials: dict[str, str]) -> str:
    renderer = Renderer(variant, posts, partials, feed=True)
    base = f"{ORIGIN}/{variant}"
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


def build_root() -> None:
    for name in ("index.html", "favicon.svg"):
        shutil.copy2(SITE / "root" / name, PUBLIC / name)


def main() -> int:
    posts = load_posts()
    pages = load_pages()
    written: list[str] = []
    for variant in VARIANTS:
        written += build_variant(variant, posts, pages)
    build_root()
    print(f"Built {len(written)} files for {', '.join(VARIANTS)} + root chooser.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
