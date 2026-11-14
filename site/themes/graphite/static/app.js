// Brett's Box "Graphite": live point-cloud heroes and small enhancements. The site works without this file.
(() => {
  'use strict';
  const reduce = matchMedia('(prefers-reduced-motion: reduce)').matches;
  const finePointer = matchMedia('(pointer: fine)').matches;
  const INK = '214, 228, 244', SIG = '159, 216, 255';
  const rnd = Math.random, TAU = Math.PI * 2;
  const gauss = () => (rnd() + rnd() + rnd() - 1.5) / 1.5;
  const ease = (t) => (t < 0.5 ? 4 * t * t * t : 1 - Math.pow(-2 * t + 2, 3) / 2);
  const clamp = (v, a, b) => Math.max(a, Math.min(b, v));
  const N = innerWidth < 800 || (navigator.hardwareConcurrency || 8) < 4 ? 5200 : 9000;

  /* ------------------------------------------------------------------ scenes
     Each scene is N points [x, y, z, tag, phase] (tag 0 = plain, 1 = signal, 2 = pulsing signal),
     a camera, labels anchored to 3D positions and two lines of readout text. */
  const W2 = (mx, my) => [(mx - 300) / 115, (my - 230) / 115];
  const at = (mx, my, y) => { const [x, z] = W2(mx, my); return [x, y, z]; };
  const ROUTE = 'M84 250 C 74 241, 79 223, 88 214 C 97 205, 122 207, 138 198 C 154 189, 174 175, 186 162 C 198 149, 203 130, 212 120 C 221 110, 231 102, 240 102 C 249 102, 260 110, 264 122 C 268 134, 255 156, 262 176 C 269 196, 288 232, 306 242 C 324 252, 353 244, 368 234 C 383 224, 390 203, 394 184 C 398 165, 389 133, 392 118 C 395 103, 406 93, 414 92 C 422 91, 435 101, 440 114 C 445 127, 448 149, 443 168 C 438 187, 416 211, 408 228 C 400 245, 400 253, 398 268 C 396 283, 403 304, 398 316 C 393 328, 383 336, 370 340 C 357 344, 334 344, 322 340 C 310 336, 303 325, 298 316 C 293 307, 300 292, 292 284 C 284 276, 274 270, 250 268 C 226 266, 178 273, 150 270 C 122 267, 94 259, 84 250 Z';
  const n = (f) => Math.round(N * f);

  function boxPoints(P, x0, x1, y0, y1, z0, z1, count, tag = 0, edgeShare = 0.6) {
    for (let k = 0; k < count; k++) {
      const p = [x0 + rnd() * (x1 - x0), y0 + rnd() * (y1 - y0), z0 + rnd() * (z1 - z0)];
      if (rnd() < edgeShare) {                        // on one of the 12 edges
        const axis = rnd() * 3 | 0, a = rnd() < 0.5, b = rnd() < 0.5;
        if (axis !== 0) p[0] = a ? x0 : x1;
        if (axis !== 1) p[1] = (axis === 0 ? a : b) ? y0 : y1;
        if (axis !== 2) p[2] = b ? z0 : z1;
      } else {                                        // on one of the 6 faces
        const f = rnd() * 6 | 0;
        if (f === 0) p[0] = x0; if (f === 1) p[0] = x1; if (f === 2) p[1] = y0;
        if (f === 3) p[1] = y1; if (f === 4) p[2] = z0; if (f === 5) p[2] = z1;
      }
      P.push([p[0], p[1], p[2], tag, 0]);
    }
  }
  function fillFloor(P, r, squash = 1) {
    while (P.length < N) { const a = rnd() * TAU, d = Math.sqrt(rnd()) * r; P.push([Math.cos(a) * d, 0, Math.sin(a) * d * squash, 0, 0]); }
  }

  function house() {
    const P = [];
    const walls = [[40,60,300,60],[360,60,560,60],[560,60,560,250],[560,250,430,250],[430,250,430,400],[430,400,200,400],[200,400,200,300],[200,300,40,300],[40,300,40,60],[300,60,300,140],[300,175,300,200],[300,200,360,200],[360,200,360,60],[200,300,270,300],[320,300,370,300],[560,160,470,160]];
    const lens = walls.map((w) => Math.hypot(w[2] - w[0], w[3] - w[1])), total = lens.reduce((a, b) => a + b);
    const floor = [[40,60],[300,60],[300,200],[360,200],[360,60],[560,60],[560,250],[430,250],[430,400],[200,400],[200,300],[40,300]];
    const inside = (x, y) => { let c = false; for (let i = 0, j = floor.length - 1; i < floor.length; j = i++) { const [xi, yi] = floor[i], [xj, yj] = floor[j]; if ((yi > y) !== (yj > y) && x < (xj - xi) * (y - yi) / (yj - yi) + xi) c = !c; } return c; };
    for (let k = 0; k < n(0.58); k++) {
      let r = rnd() * total, i = 0; while (r > lens[i]) r -= lens[i++];
      const w = walls[i], t = r / lens[i], [x, z] = W2(w[0] + (w[2] - w[0]) * t, w[1] + (w[3] - w[1]) * t);
      P.push([x + gauss() * 0.01, Math.round(rnd() * 16) / 16 * 0.8, z + gauss() * 0.01, 0, 0]);
    }
    while (P.length < n(0.745)) { const mx = 40 + rnd() * 520, my = 60 + rnd() * 340; if (!inside(mx, my)) continue; const [x, z] = W2(mx, my); P.push([x, 0, z, 0, 0]); }
    for (const [bx, by, bw, bd, bh] of [[96, 120, 54, 34, 0.42], [470, 94, 40, 40, 0.5], [212, 360, 70, 22, 0.38]]) {
      const [x0, z0] = W2(bx, by), [x1, z1] = W2(bx + bw, by + bd);
      boxPoints(P, x0, x1, 0, bh, z0, z1, n(0.037), 0, 0.5);
    }
    const svg = document.createElementNS('http://www.w3.org/2000/svg', 'svg'), path = document.createElementNS('http://www.w3.org/2000/svg', 'path');
    svg.setAttribute('style', 'position:absolute;width:0;height:0'); path.setAttribute('d', ROUTE); svg.appendChild(path); document.body.appendChild(svg);
    const L = path.getTotalLength(), samples = [];
    for (let i = 0; i <= 600; i++) { const pt = path.getPointAtLength(L * i / 600); samples.push([pt.x, pt.y, i / 600]); }
    svg.remove();
    while (P.length < N) { const s = samples[rnd() * samples.length | 0], [x, z] = W2(s[0], s[1]); P.push([x + gauss() * 0.012, 0.02 + rnd() * 0.02, z + gauss() * 0.012, 2, s[2] * TAU]); }
    return {
      name: 'House · scan', stack: 'ROS 2 Jazzy · visual SLAM', pulse: 0.9, P,
      cam: { c: [0.3, 0.25, 0], d: 5.9, ph: 0.66, f: 1.05, spin: 1 },
      notes: [[at(560, 160, 0.8), 'Walls · scanned'], [at(250, 268, 0.03), 'Route · loop 01', 'dr'], [at(490, 114, 0.5), 'Obstacle', 'ul'], [at(84, 250, 0.03), 'Loop closure ✓', 'ul']],
    };
  }

  function robot() {
    const P = [], R = 1.25, H = 0.36;
    for (let k = 0; k < n(0.29); k++) { const a = rnd() * TAU; P.push([Math.cos(a) * R, Math.round(rnd() * 9) / 9 * H, Math.sin(a) * R, 0, 0]); }
    for (let k = 0; k < n(0.19); k++) { const a = rnd() * TAU, r = Math.round(Math.sqrt(rnd()) * 14) / 14 * R; P.push([Math.cos(a) * r, H, Math.sin(a) * r, 0, 0]); }
    boxPoints(P, -0.75, 0.75, H, H + 0.08, -0.55, 0.55, n(0.1));
    boxPoints(P, 0.25, 0.85, H + 0.08, H + 0.56, -0.5, 0.5, n(0.167), 1);
    boxPoints(P, -0.7, 0.05, H + 0.08, H + 0.42, -0.45, 0.45, n(0.144));
    while (P.length < N) { const a = rnd() * TAU, r = R + 0.1 + rnd() * 0.9; P.push([Math.cos(a) * r, 0, Math.sin(a) * r, 0, 0]); }
    return {
      name: 'Roomba 550 · model', stack: 'Jetson Orin Nano · ROS 2', P,
      cam: { c: [0, 0.55, 0], d: 4.3, ph: 0.36, f: 1.0, spin: 2.3 },
      notes: [[[0.55, 0.88, 0], 'Stereo vision camera'], [[-0.32, 0.76, 0], 'Jetson Orin Nano', 'ul'], [[0, 0.2, 1.25], 'Roomba 550 · 2007', 'dr']],
    };
  }

  function horse() {
    const c = document.createElement('canvas'); c.width = 460; c.height = 420; const g = c.getContext('2d');
    g.scale(2, 2); g.translate(10, 22); g.fillStyle = g.strokeStyle = '#fff'; g.lineCap = g.lineJoin = 'round';
    g.fill(new Path2D('M124 100 L129 131 L127 154 L132 166 L122 168 L118 157 L117 134 L111 104 Z M86 104 L90 122 L83 138 L84 156 L89 166 L78 168 L75 157 L72 140 L67 118 Z M47 62 C 34 66, 26 88, 26 112 C 26 122, 30 130, 35 135 C 37 120, 39 96, 51 74 Z M46 60 C 60 52, 95 56, 122 52 C 132 50, 140 40, 150 28 C 156 20, 160 14, 164 10 L 166 1 L 171 9 C 178 12, 186 22, 192 34 L 199 47 C 200 53, 195 57, 189 55 C 182 53, 176 50, 170 50 C 163 52, 158 58, 155 66 C 152 74, 151 82, 150 90 C 149 96, 146 100, 144 104 L 147 132 L 146 154 L 151 166 L 141 168 L 137 157 L 136 134 L 131 108 C 115 112, 90 112, 74 106 L 78 122 L 70 138 L 70 156 L 75 166 L 64 168 L 61 157 L 58 140 L 52 122 C 46 110, 40 84, 46 60 Z'));
    g.lineWidth = 9; g.stroke(new Path2D('M103 47 L119 64 L113 88'));
    g.lineWidth = 14; g.stroke(new Path2D('M102 46 L105 22'));
    g.lineWidth = 6.5; g.stroke(new Path2D('M106 25 L117 37 L129 40'));
    g.beginPath(); g.arc(107, 9, 7.5, 0, TAU); g.fill();
    const d = g.getImageData(0, 0, c.width, c.height).data, P = [];
    while (P.length < n(0.73)) {
      const px = rnd() * c.width | 0, py = rnd() * c.height | 0;
      if (d[(py * c.width + px) * 4 + 3] < 128) continue;
      const lx = px / 2 - 10, ly = py / 2 - 22, leg = ly > 106, rider = lx > 96 && lx < 132 && ly < 52;
      const z = leg ? (rnd() < 0.5 ? 0.14 : -0.14) + gauss() * 0.03 : gauss() * (rider ? 0.1 : 0.26);
      P.push([(lx - 112) / 62, (168 - ly) / 62, z, rider ? 1 : 0, 0]);
    }
    fillFloor(P, 3.2, 0.7);
    return {
      name: 'Horse + rider · track', stack: 'Machine vision · no tags', lock: 'Target lock · horse 1', P,
      cam: { c: [0, 1.5, 0], d: 5.8, ph: 0.08, f: 1.0, spin: 0, sway: true },
      notes: [[[-0.08, 2.62, 0], 'Rider ✓']],
    };
  }

  function network() {
    const P = [], nodes = [[20, 1.9, 0.7, 'Firewall', 'dr'], [110, 1.95, 0.35, 'Photos', 'ul'], [200, 1.9, 0.85, 'Files', 'ul'], [290, 1.95, 0.5, 'Home automation', 'ur']];
    boxPoints(P, -0.45, 0.45, 0, 0.55, -0.35, 0.35, n(0.15), 0, 0.7);
    for (let k = 0; k < n(0.02); k++) P.push([-0.3 + rnd() * 0.25, 0.4 + Math.round(rnd() * 3) * 0.04, 0.351, 1, 0]);
    const notes = [[[0, 0.62, 0], 'Proxmox host']];
    for (const [deg, r, h, label, dir] of nodes) {
      const a = deg * Math.PI / 180, cx = Math.cos(a) * r, cz = Math.sin(a) * r;
      for (let k = 0; k < n(0.065); k++) {                    // a small sphere per service
        const u = rnd() * 2 - 1, t = rnd() * TAU, s = Math.sqrt(1 - u * u), rr = 0.2;
        P.push([cx + s * Math.cos(t) * rr, h + u * rr, cz + s * Math.sin(t) * rr, 0, 0]);
      }
      for (let k = 0; k < n(0.05); k++) {                     // the link from the host, with pulses
        const t = rnd(); P.push([cx * t + gauss() * 0.006, 0.28 + (h - 0.28) * t, cz * t + gauss() * 0.006, 2, t * TAU * 2]);
      }
      notes.push([[cx, h + 0.24, cz], label, dir]);
    }
    for (let k = 0; k < n(0.08); k++) { const a = rnd() * TAU; P.push([Math.cos(a) * 2.6, 0, Math.sin(a) * 2.6, 0, 0]); }
    fillFloor(P, 2.6);
    return { name: 'Homelab · network', stack: 'Proxmox · self-hosted', pulse: 2.6, P, cam: { c: [0, 1.0, 0], d: 6.2, ph: 0.4, f: 1.0, spin: 1.2 }, notes };
  }

  function printer() {
    const P = [];
    boxPoints(P, -1.0, 1.0, 0, 0.12, -0.8, 0.8, n(0.09));                 // base
    boxPoints(P, -0.98, -0.88, 0.12, 2.1, -0.05, 0.05, n(0.06));           // uprights
    boxPoints(P, 0.88, 0.98, 0.12, 2.1, -0.05, 0.05, n(0.06));
    boxPoints(P, -0.98, 0.98, 2.1, 2.2, -0.05, 0.05, n(0.04));             // top bar
    boxPoints(P, -0.9, 0.9, 1.05, 1.13, -0.06, 0.06, n(0.06));             // X gantry
    boxPoints(P, -0.12, 0.12, 0.96, 1.2, -0.13, 0.11, n(0.035), 1);         // hotend
    boxPoints(P, -0.7, 0.7, 0.28, 0.31, -0.7, 0.7, n(0.14), 0, 0.3);       // bed
    for (let k = 0; k < n(0.2); k++) {                                      // the part being printed
      const a = rnd() * TAU, y = 0.31 + Math.round(rnd() * 24) / 24 * 0.6, r = 0.36 - (y - 0.31) * 0.18;
      P.push([Math.cos(a) * r, y, Math.sin(a) * r, 2, (y - 0.31) / 0.6 * TAU]);
    }
    fillFloor(P, 2.4, 0.8);
    return {
      name: '3D printer · print', stack: 'Klipper · Ender 3 V2', pulse: 1.4, P,
      cam: { c: [0, 1.05, 0], d: 5.6, ph: 0.26, f: 1.0, spin: 1.5 },
      notes: [[[0.98, 2.15, 0], 'Ender 3 V2 · Klipper'], [[0, 1.0, 0.11], 'Hotend', 'ul'], [[0.7, 0.3, 0.7], 'Bed · 229 × 208 mm', 'dr']],
    };
  }

  const BUILDERS = { house, robot, horse, network, printer }, cache = {};
  const scene = (name) => cache[name] || (cache[name] = (BUILDERS[name] || house)());

  /* ------------------------------------------------------------------ projection + drawing */
  function makeProjector(cam, W, H, cx, cy) {
    const cyw = Math.cos(cam.th), syw = Math.sin(cam.th), cp = Math.cos(cam.ph), sp = Math.sin(cam.ph), base = Math.min(H, W * 0.82) * cam.f;
    return (q) => {
      const x = q[0] - cam.c[0], y = q[1] - cam.c[1], z = q[2] - cam.c[2];
      const x1 = x * cyw - z * syw, z1 = x * syw + z * cyw, y2 = y * cp - z1 * sp, zz = y * sp + z1 * cp + cam.d;
      if (zz < 0.6) return null;
      const f = base / zz; return [cx + x1 * f, cy - y2 * f, zz];
    };
  }
  const buckets = Array.from({ length: 10 }, () => []), sigB = [[], [], []];
  function drawPoints(ctx, pts, proj, t, pulseSpeed, dpr, collect) {
    buckets.forEach((b) => (b.length = 0)); sigB.forEach((b) => (b.length = 0));
    for (let i = 0; i < pts.length; i++) {
      const q = pts[i], P = proj(q); if (!P) continue;
      const size = Math.min(3.2, Math.max(0.9, 6.5 / P[2])) * dpr;
      if (collect) collect(q, P);
      if (q[3] === 0) { buckets[clamp((7.5 - P[2]) * 1.6 | 0, 0, 9)].push(P[0], P[1], size); continue; }
      let lvl = 1, s = size * 1.25;
      if (q[3] === 2) { const b = Math.pow(0.5 + 0.5 * Math.cos(q[4] - t * pulseSpeed), 10); lvl = b > 0.6 ? 2 : b > 0.15 ? 1 : 0; s = size * (1.1 + b * 0.9); }
      sigB[lvl].push(P[0], P[1], s);
    }
    buckets.forEach((b, l) => { ctx.fillStyle = `rgba(${INK}, ${0.09 + l * 0.085})`; for (let j = 0; j < b.length; j += 3) ctx.fillRect(b[j], b[j + 1], b[j + 2], b[j + 2]); });
    sigB.forEach((b, l) => { ctx.fillStyle = `rgba(${SIG}, ${[0.38, 0.75, 1][l]})`; for (let j = 0; j < b.length; j += 3) ctx.fillRect(b[j], b[j + 1], b[j + 2], b[j + 2]); });
  }

  // Static thumbnails of a scene, for the hero cards and the scene strip.
  function drawThumb(cv) {
    const s = scene(cv.dataset.thumb), dpr = Math.min(2, devicePixelRatio || 1), w = cv.clientWidth, h = cv.clientHeight;
    if (!w || !h) return;
    cv.width = w * dpr; cv.height = h * dpr;
    const ctx = cv.getContext('2d'); ctx.globalCompositeOperation = 'lighter';
    const cam = { ...s.cam, th: s.cam.sway ? 0.12 : 0.6, d: s.cam.d * 0.92 };
    drawPoints(ctx, s.P, makeProjector(cam, w * dpr, h * dpr, w * dpr / 2, h * dpr * 0.56), 0.5, s.pulse || 1, dpr * 0.45);
  }

  /* ------------------------------------------------------------------ hero engine */
  function Hero(el) {
    const names = (el.dataset.scenes || '').split(',').map((s) => s.trim()).filter(Boolean);
    const scenes = (names.length ? names : ['house']).map(scene);
    const cv = el.querySelector('.hero__cloud'), hv = el.querySelector('.hero__hud'), ctx = cv.getContext('2d'), hud = hv.getContext('2d');
    const readL = el.querySelector('.readout--l'), readR = el.querySelector('.readout--r');
    const items = [...el.querySelectorAll('.strip__item')], ctaBtn = el.querySelector('[data-cta]'), ctaArrow = el.querySelector('[data-cta-arrow]');
    const isHome = el.classList.contains('hero--home');
    let W = 0, H = 0, dpr = 1, slide = 0, tStart = -10, visible = true, running = false, fps = 60, last = 0, frameNo = 0, timer = 0;
    const cur = scenes[0].P.map((p) => p.slice()), from = cur.map((p) => p.slice());
    const swirl = cur.map(() => [gauss(), gauss() * 0.6, gauss()]), delay = cur.map(() => rnd() * 0.45);
    let cam = { ...scenes[0].cam, th: scenes[0].cam.sway ? 0.12 : 0.6 }, camFrom = { ...cam };

    function resize() {
      dpr = Math.min(2, devicePixelRatio || 1); W = el.clientWidth * dpr; H = el.clientHeight * dpr;
      cv.width = hv.width = W; cv.height = hv.height = H;
      if (!running) draw(performance.now());
    }
    function go(i, user, intro) {
      if (i === slide && !user) return;
      for (let k = 0; k < cur.length; k++) {
        if (intro) { from[k][0] = gauss() * 4; from[k][1] = 1 + gauss() * 2; from[k][2] = gauss() * 4; }
        else { from[k][0] = cur[k][0]; from[k][1] = cur[k][1]; from[k][2] = cur[k][2]; }
      }
      camFrom = { ...cam }; slide = i; tStart = reduce ? -10 : performance.now() / 1000;
      items.forEach((it, k) => {
        it.classList.toggle('is-on', k === i);
        const bar = it.querySelector('.strip__bar'); bar.style.animation = 'none'; void bar.offsetWidth; bar.style.animation = '';
      });
      if (items[i] && ctaBtn) { ctaBtn.href = ctaArrow.href = items[i].getAttribute('href'); ctaBtn.textContent = items[i].dataset.ctaLabel; }
      if (reduce) { for (let k = 0; k < cur.length; k++) { const b = scenes[i].P[k]; cur[k][0] = b[0]; cur[k][1] = b[1]; cur[k][2] = b[2]; cur[k][3] = b[3]; cur[k][4] = b[4]; } cam = { ...scenes[i].cam, th: scenes[i].cam.sway ? 0.12 : 0.6 }; draw(performance.now()); }
      if (isHome && !reduce) { clearInterval(timer); timer = setInterval(() => visible && go((slide + 1) % scenes.length), 7000); }
    }
    items.forEach((it, i) => it.addEventListener('click', (e) => { e.preventDefault(); go(i, true); }));

    function draw(now) {
      const t = now / 1000, S = scenes[slide], C = S.cam, k = clamp((t - tStart) / 2.4, 0, 1), ek = ease(k);
      if (!reduce) {
        for (const key of ['d', 'ph', 'f']) cam[key] = camFrom[key] + (C[key] - camFrom[key]) * ek;
        cam.c = [0, 1, 2].map((j) => camFrom.c[j] + (C.c[j] - camFrom.c[j]) * ek);
        cam.th = C.sway ? cam.th + (0.12 + 0.2 * Math.sin(t * 0.18) - cam.th) * 0.05 : cam.th + 0.0028 * C.spin;
        if (k < 1) for (let i = 0; i < cur.length; i++) {
          const p = clamp(k * 1.45 - delay[i], 0, 1), e = ease(p), s = Math.sin(p * Math.PI) * 0.9, a = from[i], b = S.P[i], w = swirl[i], q = cur[i];
          q[0] = a[0] + (b[0] - a[0]) * e + w[0] * s; q[1] = a[1] + (b[1] - a[1]) * e + w[1] * s; q[2] = a[2] + (b[2] - a[2]) * e + w[2] * s; q[3] = b[3]; q[4] = b[4];
        }
        else if (cur[0][0] !== S.P[0][0]) for (let i = 0; i < cur.length; i++) { const b = S.P[i], q = cur[i]; q[0] = b[0]; q[1] = b[1]; q[2] = b[2]; q[3] = b[3]; q[4] = b[4]; }
      }
      const narrow = W / dpr < 900, cx = W * (narrow ? 0.5 : isHome ? 0.6 : 0.72), cy = H * (narrow ? 0.34 : isHome ? 0.46 : 0.44);
      const proj = makeProjector(isHome || narrow ? cam : { ...cam, d: cam.d * 1.26 }, W, H, cx, cy);
      if (reduce) ctx.clearRect(0, 0, W, H);
      else { ctx.globalCompositeOperation = 'destination-out'; ctx.fillStyle = 'rgba(0,0,0,0.5)'; ctx.fillRect(0, 0, W, H); }
      ctx.globalCompositeOperation = 'lighter';
      const box = [1e9, 1e9, -1e9, -1e9];
      drawPoints(ctx, cur, proj, t, S.pulse || 1, dpr, S.lock && k === 1 ? (q, P) => { if (q[1] > 0.02) { box[0] = Math.min(box[0], P[0]); box[1] = Math.min(box[1], P[1]); box[2] = Math.max(box[2], P[0]); box[3] = Math.max(box[3], P[1]); } } : null);

      // overlay: floor grid, labels and the tracking box
      hud.clearRect(0, 0, W, H);
      hud.lineWidth = dpr; hud.strokeStyle = `rgba(${INK}, 0.06)`; hud.beginPath();
      for (let g = -3; g <= 3; g += 0.5) for (const [a, b] of [[[g, 0, -3], [g, 0, 3]], [[-3, 0, g], [3, 0, g]]]) { const A = proj(a), B = proj(b); if (A && B) { hud.moveTo(A[0], A[1]); hud.lineTo(B[0], B[1]); } }
      hud.stroke();
      const na = clamp((k - 0.75) / 0.25, 0, 1);
      hud.font = `500 ${10.5 * dpr}px "JetBrains Mono", monospace`; hud.textBaseline = 'middle'; hud.globalAlpha = na;
      for (const [pos, text, dir = 'ur'] of S.notes) {
        const P = proj(pos); if (!P) continue;
        const label = text.toUpperCase(), w = hud.measureText(label).width, sx = dir[1] === 'l' ? -1 : 1, sy = dir[0] === 'd' ? 1 : -1;
        const lx = P[0] + sx * 46 * dpr, ly = P[1] + sy * 34 * dpr, end = lx + sx * (w + 16 * dpr);
        hud.strokeStyle = `rgba(${SIG}, 0.8)`; hud.fillStyle = `rgb(${SIG})`;
        hud.beginPath(); hud.arc(P[0], P[1], 3 * dpr, 0, TAU); hud.fill();
        hud.beginPath(); hud.moveTo(P[0], P[1]); hud.lineTo(lx, ly); hud.lineTo(end, ly); hud.stroke();
        hud.fillStyle = `rgba(${INK}, 0.95)`; hud.fillText(label, sx > 0 ? lx + 8 * dpr : end + 8 * dpr, ly - 9 * dpr);
      }
      if (S.lock && box[2] > box[0]) {
        const pad = 14 * dpr, x0 = box[0] - pad, y0 = box[1] - pad, x1 = box[2] + pad, y1 = box[3] + pad, L = 26 * dpr, label = S.lock.toUpperCase();
        hud.strokeStyle = `rgba(${SIG}, 0.95)`; hud.lineWidth = 2 * dpr; hud.beginPath();
        for (const [x, y, dx, dy] of [[x0, y0, 1, 1], [x1, y0, -1, 1], [x0, y1, 1, -1], [x1, y1, -1, -1]]) { hud.moveTo(x, y + dy * L); hud.lineTo(x, y); hud.lineTo(x + dx * L, y); }
        hud.stroke(); hud.lineWidth = dpr;
        const w = hud.measureText(label).width + 16 * dpr;
        hud.fillStyle = `rgb(${SIG})`; hud.fillRect(x0, y0 - 26 * dpr, w, 20 * dpr);
        hud.fillStyle = '#06080b'; hud.fillText(label, x0 + 8 * dpr, y0 - 16 * dpr);
      }
      hud.globalAlpha = 1;

      if (frameNo++ % 6 === 0 && readL) {
        const deg = ((cam.th * 180 / Math.PI) % 360 + 360) % 360;
        readL.innerHTML = `Scene <b>${String(slide + 1).padStart(2, '0')}/${String(scenes.length).padStart(2, '0')}</b>  ${S.name}\nPoints <b>${N.toLocaleString('en')}</b>  Render <b>${reduce ? 'still' : Math.round(fps) + ' fps'}</b>`;
        readR.innerHTML = `Orbit <b>${deg.toFixed(1).padStart(5, '0')}°</b>  Elev <b>${(cam.ph * 57.3).toFixed(1)}°</b>\n<span class="sig">●</span> ${S.stack}`;
      }
    }
    function loop(now) {
      if (!running) return;
      fps = fps * 0.9 + (1000 / Math.max(1, now - last)) * 0.1; last = now;
      draw(now); requestAnimationFrame(loop);
    }
    function setRunning(on) {
      if (reduce || on === running) return;
      running = on; if (on) { last = performance.now(); requestAnimationFrame(loop); }
    }
    new IntersectionObserver(([e]) => { visible = e.isIntersecting; setRunning(visible && !document.hidden); }).observe(el);
    document.addEventListener('visibilitychange', () => setRunning(visible && !document.hidden));
    addEventListener('resize', resize);
    resize();
    if (reduce) draw(performance.now());
    else go(0, true, true);
  }

  /* ------------------------------------------------------------------ page behaviour */
  const header = document.querySelector('.site-header'), toggle = document.querySelector('.nav-toggle'), bar = document.querySelector('.progress');
  if (header && toggle) {
    header.querySelectorAll('.site-nav li').forEach((li, i) => li.style.setProperty('--i', i));
    const setOpen = (open) => { header.classList.toggle('is-open', open); toggle.setAttribute('aria-expanded', String(open)); document.body.style.overflow = open ? 'hidden' : ''; };
    toggle.addEventListener('click', () => setOpen(!header.classList.contains('is-open')));
    header.querySelectorAll('.site-nav a').forEach((a) => a.addEventListener('click', () => setOpen(false)));
    document.addEventListener('keydown', (e) => { if (e.key === 'Escape' && header.classList.contains('is-open')) { setOpen(false); toggle.focus(); } });
  }
  const onScroll = () => {
    if (header) header.classList.toggle('is-scrolled', scrollY > 30);
    if (bar) { const max = document.documentElement.scrollHeight - innerHeight; bar.style.setProperty('--p', max > 0 ? (scrollY / max).toFixed(4) : 0); }
  };
  addEventListener('scroll', onScroll, { passive: true }); onScroll();

  // Point-cloud heroes and thumbnails.
  document.querySelectorAll('.hero').forEach((el) => Hero(el));
  const thumbs = () => document.querySelectorAll('canvas[data-thumb]').forEach(drawThumb);
  thumbs(); addEventListener('resize', thumbs);

  // Crosshair cursor over the heroes, with screen coordinates.
  if (finePointer) {
    const x = document.createElement('div'); x.className = 'xhair'; x.innerHTML = '<i></i><span></span>'; document.body.appendChild(x);
    const label = x.querySelector('span');
    document.querySelectorAll('.hero').forEach((h) => {
      h.classList.add('has-xhair');
      h.addEventListener('pointermove', (e) => {
        x.style.transform = `translate(${e.clientX}px, ${e.clientY}px)`;
        label.textContent = `X ${String(e.clientX).padStart(4, '0')}  Y ${String(e.clientY).padStart(4, '0')}`;
        x.classList.add('is-on'); x.classList.toggle('is-link', !!e.target.closest('a, button'));
      });
      h.addEventListener('pointerleave', () => x.classList.remove('is-on'));
    });
  }

  // Reveal content as it scrolls into view, with a small stagger inside grids.
  document.querySelectorAll('.prose .figure, .prose .flow, .prose .callout, .prose .table-wrap, .prose .lessons > li, .prose .status-board > li, .prose .spec-grid > div, .prose .service, .prose .zone, .prose .repo-card, .post-nav__link, .prose h2')
    .forEach((el) => { el.setAttribute('data-reveal', ''); const i = [...el.parentElement.children].indexOf(el); if (el.parentElement.matches('.spec-grid, .service-grid, .zone-grid, .repo-grid, .status-board, .lessons')) el.style.setProperty('--d', `${Math.min(i, 6) * 70}ms`); });
  document.querySelectorAll('.project-grid > *, .stats__list > li').forEach((el, i) => el.style.setProperty('--d', `${(i % 4) * 90}ms`));
  const reveals = document.querySelectorAll('[data-reveal]');
  const countUp = (el) => {
    const target = parseInt(el.dataset.count, 10), t0 = performance.now();
    const step = (now) => { const p = Math.min(1, (now - t0) / 1300); el.textContent = String(Math.round(target * (1 - Math.pow(1 - p, 3)))); if (p < 1) requestAnimationFrame(step); };
    requestAnimationFrame(step);
  };
  if (reduce || !('IntersectionObserver' in window)) reveals.forEach((el) => el.classList.add('is-in'));
  else {
    const io = new IntersectionObserver((entries) => entries.forEach((e) => {
      if (!e.isIntersecting) return;
      e.target.classList.add('is-in'); io.unobserve(e.target);
      e.target.querySelectorAll('[data-count]').forEach(countUp);
    }), { rootMargin: '0px 0px -8% 0px', threshold: 0.06 });
    reveals.forEach((el) => io.observe(el));
  }

  // The home statement lights up word by word as you scroll through it.
  document.querySelectorAll('[data-words]').forEach((el) => {
    const words = el.textContent.trim().split(/\s+/);
    el.innerHTML = words.map((w) => `<span class="w">${w.replace(/&/g, '&amp;').replace(/</g, '&lt;')}</span>`).join(' ');
    const spans = el.querySelectorAll('.w');
    if (reduce) { spans.forEach((s) => s.classList.add('on')); return; }
    const update = () => {
      const r = el.getBoundingClientRect(), p = clamp((innerHeight * 0.85 - r.top) / (r.height + innerHeight * 0.3), 0, 1), on = Math.round(p * spans.length);
      spans.forEach((s, i) => s.classList.toggle('on', i < on));
    };
    addEventListener('scroll', update, { passive: true }); update();
  });

  // Demo videos: autoplay muted while on screen, unless reduced motion is requested.
  document.querySelectorAll('[data-video]').forEach((box) => {
    const video = box.querySelector('video'), button = box.querySelector('.video__toggle'), text = button.querySelector('.video__text');
    let userPaused = false;
    video.muted = true; video.controls = false; button.hidden = false;
    const sync = () => { const playing = !video.paused; box.classList.toggle('is-playing', playing); text.textContent = playing ? 'Pause video' : 'Play video'; };
    button.addEventListener('click', () => { if (video.paused) { userPaused = false; video.play().catch(() => {}); } else { userPaused = true; video.pause(); } });
    video.addEventListener('play', sync); video.addEventListener('pause', sync);
    if (!reduce && 'IntersectionObserver' in window) {
      new IntersectionObserver((entries) => entries.forEach((e) => {
        if (e.isIntersecting) { if (!userPaused) video.play().catch(() => {}); } else if (!video.paused) video.pause();
      }), { threshold: 0.3 }).observe(video);
    }
    sync();
  });
})();
