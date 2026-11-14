# brettsbox.com

Source of [brettsbox.com](https://brettsbox.com): hand-built static HTML, CSS and JavaScript.

- `public/` is served as-is by nginx in a Proxmox container (CT 140 `web`), published through a Cloudflare Tunnel.
- The container pulls this repository every few minutes (`deploy/brettsbox-pull.timer`), so pushing to `main` publishes the site.