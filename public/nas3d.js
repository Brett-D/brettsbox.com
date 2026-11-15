/* Brett's Box: interactive 3D model of the homelab NAS. Plain WebGL, no libraries.
   Units are millimetres in NAS_Box.py's axes: x = width (left to right seen from the front),
   y = depth (0 = front), z = height (0 = case floor). */
(() => {
  'use strict';
  const root = document.querySelector('[data-model="nas"]');
  if (!root) return;
  const canvas = root.querySelector('canvas');
  const reduce = matchMedia('(prefers-reduced-motion: reduce)').matches;

  /* ---------- vectors and matrices ---------- */
  const add = (a, b) => [a[0] + b[0], a[1] + b[1], a[2] + b[2]];
  const sub = (a, b) => [a[0] - b[0], a[1] - b[1], a[2] - b[2]];
  const mul = (a, s) => [a[0] * s, a[1] * s, a[2] * s];
  const dot = (a, b) => a[0] * b[0] + a[1] * b[1] + a[2] * b[2];
  const cross = (a, b) => [a[1] * b[2] - a[2] * b[1], a[2] * b[0] - a[0] * b[2], a[0] * b[1] - a[1] * b[0]];
  const len = (a) => Math.hypot(a[0], a[1], a[2]);
  const unit = (a) => { const l = len(a) || 1; return [a[0] / l, a[1] / l, a[2] / l]; };
  const lerp = (a, b, t) => a + (b - a) * t;
  const ease = (t) => (t < 0.5 ? 4 * t * t * t : 1 - Math.pow(-2 * t + 2, 3) / 2);

  function mat4mul(a, b) {
    const o = new Float32Array(16);
    for (let c = 0; c < 4; c++) for (let r = 0; r < 4; r++) {
      o[c * 4 + r] = a[r] * b[c * 4] + a[4 + r] * b[c * 4 + 1] + a[8 + r] * b[c * 4 + 2] + a[12 + r] * b[c * 4 + 3];
    }
    return o;
  }
  function perspective(fovy, aspect, near, far) {
    const f = 1 / Math.tan(fovy / 2), nf = 1 / (near - far);
    return new Float32Array([f / aspect, 0, 0, 0, 0, f, 0, 0, 0, 0, (far + near) * nf, -1, 0, 0, 2 * far * near * nf, 0]);
  }
  function lookAt(eye, target, up) {
    const z = unit(sub(eye, target)), x = unit(cross(up, z)), y = cross(z, x);
    return new Float32Array([x[0], y[0], z[0], 0, x[1], y[1], z[1], 0, x[2], y[2], z[2], 0,
      -dot(x, eye), -dot(y, eye), -dot(z, eye), 1]);
  }
  const translate = (t) => new Float32Array([1, 0, 0, 0, 0, 1, 0, 0, 0, 0, 1, 0, t[0], t[1], t[2], 1]);
  function spinAbout(c, a, t, axis) { // rotate about the y or z axis through c, then translate by t
    const co = Math.cos(a), si = Math.sin(a);
    const r = axis === 'z'
      ? new Float32Array([co, si, 0, 0, -si, co, 0, 0, 0, 0, 1, 0, 0, 0, 0, 1])
      : new Float32Array([co, 0, -si, 0, 0, 1, 0, 0, si, 0, co, 0, 0, 0, 0, 1]);
    return mat4mul(translate(add(c, t)), mat4mul(r, translate(mul(c, -1))));
  }

  /* ---------- geometry ---------- */
  class Geo {
    constructor() { this.t = []; this.n = []; this.l = []; }
    tri(a, b, c, na, nb = na, nc = na) { this.t.push(...a, ...b, ...c); this.n.push(...na, ...nb, ...nc); }
    quad(a, b, c, d, n) { this.tri(a, b, c, n); this.tri(a, c, d, n); }
    seg(a, b) { this.l.push(...a, ...b); }
    loop(pts) { pts.forEach((p, i) => this.seg(p, pts[(i + 1) % pts.length])); }
    box(x0, y0, z0, x1, y1, z1, edges = true) {
      const p = (i) => [i & 1 ? x1 : x0, i & 2 ? y1 : y0, i & 4 ? z1 : z0];
      this.quad(p(0), p(2), p(6), p(4), [-1, 0, 0]); this.quad(p(1), p(3), p(7), p(5), [1, 0, 0]);
      this.quad(p(0), p(1), p(5), p(4), [0, -1, 0]); this.quad(p(2), p(3), p(7), p(6), [0, 1, 0]);
      this.quad(p(0), p(1), p(3), p(2), [0, 0, -1]); this.quad(p(4), p(5), p(7), p(6), [0, 0, 1]);
      if (edges) [[0, 1], [2, 3], [4, 5], [6, 7], [0, 2], [1, 3], [4, 6], [5, 7], [0, 4], [1, 5], [2, 6], [3, 7]]
        .forEach(([a, b]) => this.seg(p(a), p(b)));
      return this;
    }
    // Cylinder around an axis ('x', 'y' or 'z') through c, from a0 to a1 along that axis.
    cyl(c, axis, r, a0, a1, seg = 28, caps = true, edges = true) {
      const P = (th, a, rr = r) => {
        const u = rr * Math.cos(th), v = rr * Math.sin(th);
        return axis === 'x' ? [a, c[1] + u, c[2] + v] : axis === 'y' ? [c[0] + u, a, c[2] + v] : [c[0] + u, c[1] + v, a];
      };
      const N = (th) => { const u = Math.cos(th), v = Math.sin(th); return axis === 'x' ? [0, u, v] : axis === 'y' ? [u, 0, v] : [u, v, 0]; };
      const ax = axis === 'x' ? [1, 0, 0] : axis === 'y' ? [0, 1, 0] : [0, 0, 1];
      for (let i = 0; i < seg; i++) {
        const t0 = (i / seg) * Math.PI * 2, t1 = ((i + 1) / seg) * Math.PI * 2;
        this.tri(P(t0, a0), P(t1, a0), P(t1, a1), N(t0), N(t1), N(t1));
        this.tri(P(t0, a0), P(t1, a1), P(t0, a1), N(t0), N(t1), N(t0));
        if (caps) {
          this.tri(P(0, a0, 0), P(t0, a0), P(t1, a0), mul(ax, -1));
          this.tri(P(0, a1, 0), P(t0, a1), P(t1, a1), ax);
        }
        if (edges) { this.seg(P(t0, a0), P(t1, a0)); this.seg(P(t0, a1), P(t1, a1)); }
      }
      return this;
    }
    circle(c, axis, r, at, seg = 32) {
      const pts = [];
      for (let i = 0; i < seg; i++) {
        const th = (i / seg) * Math.PI * 2, u = r * Math.cos(th), v = r * Math.sin(th);
        pts.push(axis === 'x' ? [at, c[1] + u, c[2] + v] : axis === 'y' ? [c[0] + u, at, c[2] + v] : [c[0] + u, c[1] + v, at]);
      }
      this.loop(pts);
      return this;
    }
    // Round tube along a path; normals point outwards.
    tube(path, r, sides = 8) {
      const pts = path.filter((p, i) => i === 0 || len(sub(p, path[i - 1])) > 0.05);
      if (pts.length < 2) return this;
      let nPrev = null;
      const rings = pts.map((p, i) => {
        const t = unit(i === 0 ? sub(pts[1], pts[0]) : i === pts.length - 1 ? sub(p, pts[i - 1]) : sub(pts[i + 1], pts[i - 1]));
        let n = nPrev ? sub(nPrev, mul(t, dot(nPrev, t))) : cross(t, Math.abs(t[2]) < 0.9 ? [0, 0, 1] : [1, 0, 0]);
        n = len(n) < 1e-6 ? unit(cross(t, [1, 0, 0])) : unit(n);
        nPrev = n;
        const b = cross(t, n);
        return Array.from({ length: sides }, (_, k) => {
          const a = (k / sides) * Math.PI * 2, d = add(mul(n, Math.cos(a)), mul(b, Math.sin(a)));
          return [add(p, mul(d, r)), d];
        });
      });
      for (let i = 0; i < rings.length - 1; i++) for (let k = 0; k < sides; k++) {
        const a = rings[i][k], b = rings[i][(k + 1) % sides], c = rings[i + 1][(k + 1) % sides], d = rings[i + 1][k];
        this.tri(a[0], b[0], c[0], a[1], b[1], c[1]);
        this.tri(a[0], c[0], d[0], a[1], c[1], d[1]);
      }
      return this;
    }
    // Hex vent outlines, same layout as NAS_Box.py's hex_cutters; frame maps (u, v) to a point.
    hexes(frame, ur, vr, af, rib) {
      const pv = af + rib, pu = (pv * Math.sqrt(3)) / 2, r = af / Math.sqrt(3);
      for (let u = ur[0] + r, col = 0; u + r <= ur[1] + 1e-6; u += pu, col++) {
        for (let v = vr[0] + af / 2 + (col % 2 ? pv / 2 : 0); v + af / 2 <= vr[1] + 1e-6; v += pv) {
          this.loop([0, 60, 120, 180, 240, 300].map((d) => frame(u + r * Math.cos((d * Math.PI) / 180), v + r * Math.sin((d * Math.PI) / 180))));
        }
      }
      return this;
    }
  }

  // Straight runs joined by rounded bends (quadratic), like a routed cable.
  function route(P, bend = 14, steps = 7) {
    const out = [P[0]];
    for (let i = 1; i < P.length - 1; i++) {
      const a = P[i - 1], b = P[i], c = P[i + 1];
      const r = Math.min(bend, len(sub(a, b)) / 2, len(sub(c, b)) / 2);
      const p0 = add(b, mul(unit(sub(a, b)), r)), p2 = add(b, mul(unit(sub(c, b)), r));
      for (let s = 0; s <= steps; s++) {
        const t = s / steps;
        out.push(add(add(mul(p0, (1 - t) * (1 - t)), mul(b, 2 * t * (1 - t))), mul(p2, t * t)));
      }
    }
    out.push(P[P.length - 1]);
    return out;
  }

  /* ---------- the parts ---------- */
  const CAGE_TOP = 129, TINY_Z = 164, H = 202, D = 260, SLEEVE = 215;
  const RIITOP_PORTS = [118, 107, 96, 85]; // y of adapter ports 1-4 (approximate)
  const ENTS = [
    ['tiny', 'Compute', 'Lenovo ThinkCentre Tiny', 'The server itself: an M920q with six cores and 32 GB of RAM, running Proxmox VE. It has its own power adapter.', '#8b95a3'],
    ['nvme', 'Storage', '512 GB NVMe SSD', "Proxmox's system drive, also on ZFS, in one of the two M.2 slots on the ThinkCentre's underside.", '#6f7f74'],
    ['riitop', 'Storage', 'M.2-to-SATA adapter', 'RIITOP, in the other M.2 slot. Its ASMedia ASM1166 chip turns two PCIe 3.0 lanes into six SATA ports; four are in use.', '#e0483e'],
    ['nic', 'Network', 'Intel X710 10 GbE card', 'On the PCIe riser inside the ThinkCentre: 10 gigabit Ethernet, ten times its built-in port. Its ports come out of the back through a yellow bracket.', '#e8c547'],
    ['usb', 'Cooling', 'USB fan speed regulator', 'Plugged into a USB port on the back. Its knob sets how fast a fan spins.', '#3f8de0'],
    ['sata', 'Data', 'SATA data cables', 'Four cables from the adapter, through the 35 mm gap under the ThinkCentre and down to the back of the drive cage.', '#9fd8ff'],
    ['cage', 'Storage', 'Rosewill drive cage', 'RSV-SATA-Cage-34: four hot-swap trays with activity lights, a 120 mm fan, and a backplane with four SATA and two Molex inputs. A failed drive slides out of the front.', '#5b6470'],
    ['drives', 'Storage', 'Four hard drives', 'Two Seagate Exos 7E8 6 TB, 7200 rpm enterprise drives built to run 24/7, and two Seagate Barracuda 2 TB. Set up as two ZFS mirrors: about 8 TB usable.', '#b9c0c8'],
    ['fan', 'Cooling', '120 mm cage fan', "Pulls air past the drives and out through the rear grille. It runs off the cage's backplane.", '#6b7480'],
    ['psu', 'Power', 'ESGAMING 300 W power supply', "A small Flex-ATX (1U) supply, fully modular. It stands on end on the case floor behind the drive cage, beside the cage's fan, with its own small fan on top. Only the Molex cable is fitted, so it powers the drive cage and nothing else.", '#7c8692'],
    ['molex', 'Power', 'Molex power cable', "12 V (yellow) for the drive motors, 5 V (red) for their electronics and two grounds, daisy-chained to both of the cage's Molex inputs.", '#ffcf8a'],
    ['switch', 'Power', 'Power switch', "Two wires from the supply's 24-pin socket. Closing the switch connects PS_ON to ground, which turns the supply on.", '#7ddc8a'],
    ['cords', 'Cables', 'Power and network cables', "Mains for the power supply, the ThinkCentre's own power cord and three network cables.", '#525b66'],
    ['case', 'Printed', 'Printed case', 'Sleeve and rear cap, 187 × 208 × 263 mm, drawn from the same script as the printed parts. Hex vents on every side.', '#b4bdc7'],
  ].map(([id, kind, name, desc, dot], i) => ({ id, kind, name, desc, dot, n: i + 1 }));
  const ENT = Object.fromEntries(ENTS.map((e) => [e.id, e]));

  const hex = (h, a = 1) => [parseInt(h.slice(1, 3), 16) / 255, parseInt(h.slice(3, 5), 16) / 255, parseInt(h.slice(5, 7), 16) / 255, a];
  const meshes = [];
  // opts: color, alpha, edge (rgba), group, shell, lit, emit, spin {c, speed}, nopick
  function part(ent, geo, opts) { meshes.push({ ent, geo, ...opts }); }

  // Explode offsets per group (mm at full explode).
  const GROUPS = { s: [0, 0, 0], t: [0, 0, 110], ti: [0, 0, 52], p: [0, 58, 0], c: [0, 108, 0],
    d0: [0, -58, 0], d1: [0, -74, 0], d2: [0, -90, 0], d3: [0, -106, 0] };

  // Printed case: translucent panels with the vent pattern drawn as outlines.
  {
    const s = new Geo(), c = new Geo(), sv = new Geo(), cv = new Geo();
    s.box(-3, 0, -3, 0, SLEEVE, 205).box(181, 0, -3, 184, SLEEVE, 205).box(0, 0, -3, 181, SLEEVE, 0)
      .box(0, 0, H, 6, SLEEVE, 205).box(175, 0, H, 181, SLEEVE, 205)
      .box(150, 0, 0, 181, 3, CAGE_TOP).box(0, 0, CAGE_TOP, 181, 3, TINY_Z)
      .box(0, 0, TINY_Z - 4, 8, 211, TINY_Z).box(173, 0, TINY_Z - 4, 181, 211, TINY_Z)
      .box(150.5, 0, 0, 153.5, 211, 8);
    c.box(-3, SLEEVE, -3, 0, D, 205).box(181, SLEEVE, -3, 184, D, 205).box(0, SLEEVE, -3, 181, D, 0)
      .box(0, SLEEVE, H, 6, D, 205).box(175, SLEEVE, H, 181, D, 205)
      .box(-3, D, -3, 184, D + 3, 166).box(-3, D, 166, 16, D + 3, 205).box(165, D, 166, 184, D + 3, 205);
    sv.hexes((u, v) => [u, -0.15, v], [154, 178], [6, 123], 6, 2.2).hexes((u, v) => [u, -0.15, v], [6, 175], [132, 161], 6, 2.2);
    for (const x of [-3.15, 184.15]) {
      sv.hexes((u, v) => [x, u, v], [20, 195], [12, 155], 7, 2.2).hexes((u, v) => [x, u, v], [20, 195], [169, 197], 7, 2.2);
    }
    sv.hexes((u, v) => [v, u, -3.15], [20, 195], [20, 144.5], 7, 2.2);
    cv.hexes((u, v) => [u, D + 3.15, v], [6, 143], [6, 158], 8, 2).circle([167.25, 0, 100], 'y', 5.75, D + 3.15, 24);
    const glass = { color: hex('#b4bdc7', 0.07), edge: hex('#c9d3dd', 0.34), lit: 0.6, nopick: true, isCase: true };
    const vents = { color: [0, 0, 0, 0], edge: hex('#9fb0c2', 0.2), linesOnly: true, nopick: true, isCase: true };
    part('case', s, { ...glass, group: 's' });
    part('case', c, { ...glass, group: 'c' });
    part('case', sv, { ...vents, group: 's' });
    part('case', cv, { ...vents, group: 'c' });
  }

  // Drive cage: steel shell, four trays (each slides out with its drive), backplane and fan.
  const TRAY_Z = [0, 1, 2, 3].map((k) => 4 + (3 - k) * 29.875); // k = 0 is the top tray
  {
    part('cage', new Geo().box(0, 4, 0, 149, 183, 127.5), { color: hex('#1a1f26', 0.5), edge: hex('#8a96a6', 0.55), group: 's', shell: true });
    const frame = new Geo().box(0, 0, 0, 149, 4, 4).box(0, 0, 123.5, 149, 4, 127.5).box(0, 0, 4, 4, 4, 123.5).box(124, 0, 4, 149, 4, 123.5);
    part('cage', frame, { color: hex('#121519'), edge: hex('#59626e', 0.8), group: 's' });
    const leds = new Geo();
    TRAY_Z.forEach((z0) => leds.box(133, -0.8, z0 + 12.5, 139, 0.2, z0 + 15.5, false));
    part('cage', leds, { color: hex('#6aa8ff'), emit: [0.25, 0.42, 0.95], lit: 0, group: 's' });
    const board = new Geo().box(124, 181, 4, 149, 183.5, 124);
    part('cage', board, { color: hex('#1f4f8f'), edge: hex('#4d7fc2', 0.6), group: 's' });
    const molexIn = new Geo().box(131.5, 183.5, 99, 139.5, 194, 120).box(131.5, 183.5, 54, 139.5, 194, 75).box(132, 183.5, 15, 138, 190, 20);
    part('cage', molexIn, { color: hex('#ddd8cc'), edge: hex('#9a958a', 0.7), group: 's' });
    const sataIn = new Geo();
    for (const z of [80, 34]) for (const x of [128, 138]) sataIn.box(x, 183.5, z, x + 6, 193, z + 11);
    part('cage', sataIn, { color: hex('#3d7fe0'), edge: hex('#7fb0f0', 0.6), group: 's' });

    TRAY_Z.forEach((z0, k) => {
      const tray = new Geo().box(4, -1.5, z0, 124, 4, z0 + 28.6);
      for (let x = 14; x <= 84; x += 3.6) { tray.seg([x, -1.6, z0 + 6], [x, -1.6, z0 + 12]); tray.seg([x, -1.6, z0 + 16.5], [x, -1.6, z0 + 22.5]); }
      part('cage', tray, { color: hex('#0d0f12'), edge: hex('#4a525d', 0.85), group: `d${k}` });
      part('cage', new Geo().box(96, -3.2, z0 + 5, 112, -1.5, z0 + 23.6), { color: hex('#22272e'), edge: hex('#5d6672', 0.8), group: `d${k}` });
      const drive = new Geo().box(14, 6, z0 + 1.3, 115.6, 153, z0 + 27.4);
      drive.loop([[24, 30, z0 + 27.5], [105, 30, z0 + 27.5], [105, 110, z0 + 27.5], [24, 110, z0 + 27.5]]);
      part('drives', drive, { color: hex(k < 2 ? '#aab2bb' : '#8d959f'), edge: hex('#dfe5eb', 0.55), group: `d${k}` });
    });

    // Fan on the back of the cage, its blades spinning about the y axis.
    const fc = [63, 197.5, 63.75];
    const fan = new Geo().cyl(fc, 'y', 58, 185.5, 209.5, 40, false).cyl(fc, 'y', 20, 186, 206, 24);
    for (const [x, z] of [[3, 3.75], [111, 3.75], [3, 111.75], [111, 111.75]]) fan.box(x, 185, z, x + 12, 210, z + 12);
    fan.loop([[3, 210, 3.75], [123, 210, 3.75], [123, 210, 123.75], [3, 210, 123.75]]);
    part('fan', fan, { color: hex('#14171b'), edge: hex('#5b6470', 0.75), group: 's' });
    part('fan', blades(fc, 21, 56, 7, 191, 204), { color: hex('#1b1f24'), edge: hex('#6b7480', 0.35), group: 's', spin: { c: fc, speed: 5.2 } });
  }

  // Fan blades between a0 and a1 along the y axis (c = [x, -, z]) or the z axis (c = [x, y, -]).
  function blades(c, r0, r1, count, a0, a1, axis = 'y') {
    const P = (r, th, a) => (axis === 'z' ? [c[0] + r * Math.cos(th), c[1] + r * Math.sin(th), a] : [c[0] + r * Math.cos(th), a, c[2] + r * Math.sin(th)]);
    const g = new Geo();
    for (let i = 0; i < count; i++) {
      const a = (i / count) * Math.PI * 2;
      const strip = [0, 1, 2, 3].map((j) => {
        const r = lerp(r0, r1, j / 3), sweep = 0.12 * j;
        return [P(r, a + sweep, a0), P(r, a + sweep + 0.62, a1)];
      });
      for (let j = 0; j < 3; j++) {
        const [a0, a1] = strip[j], [b0, b1] = strip[j + 1];
        const n = unit(cross(sub(a1, a0), sub(b0, a0)));
        g.quad(a0, a1, b1, b0, n);
      }
      g.seg(strip[3][0], strip[3][1]);
    }
    return g;
  }

  // ThinkCentre Tiny and what's in it.
  {
    const body = new Geo().box(1, 3.5, TINY_Z, 180, 186.5, TINY_Z + 34.5);
    part('tiny', body, { color: hex('#1c2027', 0.8), edge: hex('#9aa5b3', 0.6), group: 't', shell: true });
    const face = new Geo().box(1, 2.6, TINY_Z + 1, 112, 3.5, TINY_Z + 17).circle([12, 0, TINY_Z + 9], 'y', 4.2, 2.5)
      .circle([34, 0, TINY_Z + 9], 'y', 2.2, 2.5).circle([45, 0, TINY_Z + 9], 'y', 2.2, 2.5);
    face.loop([[56, 2.5, TINY_Z + 7.5], [65, 2.5, TINY_Z + 7.5], [65, 2.5, TINY_Z + 10.5], [56, 2.5, TINY_Z + 10.5]]);
    face.loop([[72, 2.5, TINY_Z + 6.5], [84, 2.5, TINY_Z + 6.5], [84, 2.5, TINY_Z + 11.5], [72, 2.5, TINY_Z + 11.5]]);
    part('tiny', face, { color: hex('#0c0e11'), edge: hex('#7a8592', 0.8), group: 't' });
    part('tiny', new Geo().box(113, 2.4, TINY_Z + 1, 118, 3.5, TINY_Z + 17), { color: hex('#d8262c'), edge: hex('#ff8080', 0.5), group: 't' });

    const nvme = new Geo().box(30, 40, TINY_Z + 1, 52, 120, TINY_Z + 3.2);
    nvme.loop([[32, 60, TINY_Z + 3.3], [50, 60, TINY_Z + 3.3], [50, 112, TINY_Z + 3.3], [32, 112, TINY_Z + 3.3]]);
    part('nvme', nvme, { color: hex('#1d3326'), edge: hex('#79b48c', 0.8), group: 'ti' });

    const riitop = new Geo().box(95, 46, TINY_Z - 9, 117, 126, TINY_Z + 1);
    RIITOP_PORTS.forEach((y) => riitop.loop([[99, y - 3, TINY_Z - 9.1], [113, y - 3, TINY_Z - 9.1], [113, y + 3, TINY_Z - 9.1], [99, y + 3, TINY_Z - 9.1]]));
    part('riitop', riitop, { color: hex('#c8332b'), edge: hex('#ff9d8f', 0.85), group: 'ti' });

    // Rear ports, from the top-down photo: seen from the front, the onboard port and the X710 are on the left,
    // the USB fan regulator in the middle and the power supply on the right.
    const nic = new Geo().box(22, 40, TINY_Z + 22, 90, 184, TINY_Z + 24);
    nic.box(45, 110, TINY_Z + 24, 67, 132, TINY_Z + 30);
    part('nic', nic, { color: hex('#1d5b38'), edge: hex('#7fd19c', 0.7), group: 'ti' });
    part('nic', new Geo().box(24, 184, TINY_Z + 3, 76, 187.5, TINY_Z + 31), { color: hex('#e2b93b'), edge: hex('#ffe08a', 0.7), group: 'ti' });
    part('nic', new Geo().box(28, 186.5, TINY_Z + 9, 44, 197, TINY_Z + 23).box(52, 186.5, TINY_Z + 9, 68, 197, TINY_Z + 23),
      { color: hex('#b8975a'), edge: hex('#e9d29a', 0.8), group: 'ti' });
    part('tiny', new Geo().box(8, 186.5, TINY_Z + 4, 20, 196, TINY_Z + 16), { color: hex('#b8975a'), edge: hex('#e9d29a', 0.6), group: 't' });

    const usb = new Geo().box(88, 186.5, TINY_Z + 8, 100, 199, TINY_Z + 14).box(84, 199, TINY_Z + 6, 104, 200.6, TINY_Z + 56);
    usb.cyl([0, 199.8, TINY_Z + 36], 'x', 5.5, 104, 116, 20).box(86, 200.6, TINY_Z + 22, 94, 203, TINY_Z + 30);
    part('usb', usb, { color: hex('#2f6fc4'), edge: hex('#8fc0ff', 0.7), group: 't' });
    part('usb', new Geo().box(96, 200.6, TINY_Z + 16, 99, 201.6, TINY_Z + 19, false), { color: hex('#7fb4ff'), emit: [0.3, 0.45, 1], lit: 0, group: 't' });
  }

  // Power supply: stands on end on the case floor behind the drive cage, against the right-hand wall seen from
  // the front (the left seen from the rear), mostly clear of the 120 mm fan. Its small fan is on the top end.
  {
    const g = new Geo().box(99.5, 218, 0, 180.5, 259, 165);
    g.box(150, 228, 165, 174, 248, 168); // AC inlet
    g.box(97, 226, 128, 99.5, 238, 142).box(97, 226, 146, 99.5, 240, 158); // modular sockets: Molex, 24-pin
    part('psu', g, { color: hex('#15181d'), edge: hex('#8a95a3', 0.7), group: 'p' });
    const fc = [124, 238.5, 165.4];
    const grille = new Geo().circle(fc, 'z', 18.5, 165.4, 36).circle(fc, 'z', 6, 165.4, 20);
    grille.loop([[104, 218.5, 165.4], [144, 218.5, 165.4], [144, 258.5, 165.4], [104, 258.5, 165.4]]);
    for (let i = 0; i < 8; i++) { const a = (i / 8) * Math.PI * 2; grille.seg([fc[0] + 6 * Math.cos(a), fc[1] + 6 * Math.sin(a), 165.4], [fc[0] + 18.5 * Math.cos(a), fc[1] + 18.5 * Math.sin(a), 165.4]); }
    part('psu', grille, { color: [0, 0, 0, 0], edge: hex('#9aa5b3', 0.8), linesOnly: true, group: 'p' });
    part('psu', blades(fc, 6.5, 17, 7, 165.2, 166, 'z'), { color: hex('#2a2f36'), edge: hex('#7b8592', 0.35), group: 'p', spin: { c: fc, speed: 4, axis: 'z' } });
    part('switch', new Geo().box(100, 286, 168, 118, 300, 180).box(105, 285, 172, 113, 286, 177), { color: hex('#1a1d22'), edge: hex('#7ddc8a', 0.6), group: 'c' });
  }

  // Cables: control points carry the group they move with when the model explodes.
  const cables = [];
  function cable(ent, ctrl, color, r = 1.9, offsets = [[0, 0, 0]], opts = {}) {
    cables.push({ ent, ctrl, color, r, offsets, ...opts });
  }
  const SATA_IN = [[131, 85.5], [141, 85.5], [131, 39.5], [141, 39.5]];
  RIITOP_PORTS.forEach((yp, i) => {
    const [cx, cz] = SATA_IN[i], zr = 141 - 2.6 * i, yr = i < 2 ? 207 : 211;
    cable('sata', [[106, yp, TINY_Z - 9, 'ti'], [106, yp, zr, 'ti'], [106, 170, zr, 'ti'], [cx, yr, zr - 4, 's'], [cx, yr, cz, 's'], [cx, 199, cz, 's']],
      hex('#9fd8ff'), 2.1, [[0, 0, 0]], { emit: [0.05, 0.1, 0.14], plugs: [[cx - 3.5, 193, cz - 1, cx + 3.5, 201, cz + 12]] });
  });
  // Adapter-side plugs.
  {
    const g = new Geo();
    RIITOP_PORTS.forEach((y) => g.box(99, y - 3, TINY_Z - 17, 113, y + 3, TINY_Z - 9));
    part('sata', g, { color: hex('#0f1216'), edge: hex('#9fd8ff', 0.6), group: 'ti' });
  }
  const WIRES = [hex('#f2c94c'), hex('#1b1d21'), hex('#1b1d21'), hex('#e0483e')];
  const ribbon = WIRES.map((_, i) => [-3.3 + 2.2 * i, 0, 0]);
  cable('molex', [[97, 232, 135, 'p'], [88, 232, 135, 'p'], [88, 212, 126, 's'], [135.5, 212, 124, 's'], [135.5, 212, 114, 's'], [135.5, 205, 109.5, 's']],
    WIRES, 0.95, ribbon, { plugs: [[130.5, 194, 98, 140.5, 206, 121]] });
  cable('molex', [[135.5, 205, 108, 's'], [135.5, 213, 100, 's'], [135.5, 213, 70, 's'], [135.5, 205, 64.5, 's']],
    WIRES, 0.95, ribbon, { plugs: [[130.5, 194, 53, 140.5, 206, 76]] });
  cable('switch', [[97, 233, 152, 'p'], [84, 233, 152, 'p'], [84, 240, 196, 'p'], [92, 250, 214, 'c'], [104, 278, 226, 'c'], [109, 293, 180, 'c']],
    [hex('#3dbb5a'), hex('#1b1d21')], 0.9, [[-1, 0, 0], [1, 0, 0]]);
  cable('cords', [[162, 238, 168, 'p'], [162, 238, 178, 'p'], [162, 266, 180, 'c'], [162, 284, 160, 'c'], [162, 296, 60, 'c'], [162, 300, -3, 'c']], hex('#202328'), 3);
  cable('cords', [[140, 186.5, TINY_Z + 10, 't'], [140, 196, TINY_Z + 10, 't'], [140, 204, 216, 't'], [140, 288, 226, 'c'], [140, 310, 60, 'c'], [140, 314, -3, 'c']], hex('#202328'), 2.4);
  cable('cords', [[14, 196, TINY_Z + 10, 't'], [14, 205, TINY_Z + 14, 't'], [14, 214, 220, 't'], [14, 290, 228, 'c'], [14, 318, -3, 'c']], hex('#d9c25a'), 2.6);
  cable('cords', [[36, 197, TINY_Z + 16, 'ti'], [36, 207, TINY_Z + 20, 'ti'], [36, 220, 224, 't'], [36, 296, 230, 'c'], [36, 324, -3, 'c']], hex('#5d97cf'), 2.6);
  cable('cords', [[60, 197, TINY_Z + 16, 'ti'], [60, 206, TINY_Z + 20, 'ti'], [60, 217, 222, 't'], [60, 292, 229, 'c'], [60, 320, -3, 'c']], hex('#202328'), 2.6);
  cable('usb', [[94, 202, TINY_Z + 56, 't'], [94, 204, 236, 't'], [94, 278, 248, 'c'], [94, 306, 80, 'c'], [94, 310, -3, 'c']], hex('#202328'), 1.6);

  /* ---------- WebGL ---------- */
  const gl = canvas.getContext('webgl', { antialias: true, alpha: false, powerPreference: 'low-power' });
  if (!gl) { root.classList.add('is-static'); return; }

  function program(vs, fs) {
    const p = gl.createProgram();
    gl.bindAttribLocation(p, 0, 'aPos');
    gl.bindAttribLocation(p, 1, 'aNor');
    for (const [type, src] of [[gl.VERTEX_SHADER, vs], [gl.FRAGMENT_SHADER, fs]]) {
      const s = gl.createShader(type);
      gl.shaderSource(s, src); gl.compileShader(s);
      if (!gl.getShaderParameter(s, gl.COMPILE_STATUS)) throw new Error(gl.getShaderInfoLog(s));
      gl.attachShader(p, s);
    }
    gl.linkProgram(p);
    if (!gl.getProgramParameter(p, gl.LINK_STATUS)) throw new Error(gl.getProgramInfoLog(p));
    const u = {};
    for (let i = 0, n = gl.getProgramParameter(p, gl.ACTIVE_UNIFORMS); i < n; i++) {
      const name = gl.getActiveUniform(p, i).name; u[name] = gl.getUniformLocation(p, name);
    }
    return { p, u, aPos: gl.getAttribLocation(p, 'aPos'), aNor: gl.getAttribLocation(p, 'aNor') };
  }
  const shade = program(
    `attribute vec3 aPos; attribute vec3 aNor; uniform mat4 uVP; uniform mat4 uM; varying vec3 vN; varying vec3 vW;
     void main() { vec4 w = uM * vec4(aPos, 1.0); vW = w.xyz; vN = (uM * vec4(aNor, 0.0)).xyz; gl_Position = uVP * w; }`,
    `precision mediump float; uniform vec4 uColor; uniform vec3 uEmit; uniform vec3 uEye; uniform float uLit; uniform float uDim;
     varying vec3 vN; varying vec3 vW;
     void main() {
       vec3 n = normalize(vN); vec3 v = normalize(uEye - vW); if (dot(n, v) < 0.0) n = -n;
       vec3 l1 = normalize(vec3(-0.45, -0.7, 0.8)); vec3 l2 = normalize(vec3(0.7, 0.55, 0.3));
       float d = 0.3 + 0.55 * max(dot(n, l1), 0.0) + 0.25 * max(dot(n, l2), 0.0) + 0.06 * n.z;
       float s = pow(max(dot(n, normalize(l1 + v)), 0.0), 36.0) * 0.32;
       float rim = pow(1.0 - max(dot(n, v), 0.0), 3.0) * 0.22;
       vec3 c = mix(uColor.rgb, uColor.rgb * d + s + rim * vec3(0.62, 0.85, 1.0), uLit) * uDim + uEmit;
       gl_FragColor = vec4(c, uColor.a);
     }`);
  const flat = program(
    'attribute vec3 aPos; uniform mat4 uVP; uniform mat4 uM; void main() { gl_Position = uVP * uM * vec4(aPos, 1.0); }',
    'precision mediump float; uniform vec4 uColor; void main() { gl_FragColor = uColor; }');

  function buffers(geo, dynamic) {
    const usage = dynamic ? gl.DYNAMIC_DRAW : gl.STATIC_DRAW;
    const b = { tc: geo.t.length / 3, lc: geo.l.length / 3 };
    if (b.tc) {
      b.tb = gl.createBuffer(); gl.bindBuffer(gl.ARRAY_BUFFER, b.tb); gl.bufferData(gl.ARRAY_BUFFER, new Float32Array(geo.t), usage);
      b.nb = gl.createBuffer(); gl.bindBuffer(gl.ARRAY_BUFFER, b.nb); gl.bufferData(gl.ARRAY_BUFFER, new Float32Array(geo.n), usage);
    }
    if (b.lc) { b.lb = gl.createBuffer(); gl.bindBuffer(gl.ARRAY_BUFFER, b.lb); gl.bufferData(gl.ARRAY_BUFFER, new Float32Array(geo.l), usage); }
    return b;
  }
  function centre(geo) {
    const a = geo.t.length ? geo.t : geo.l, lo = [1e9, 1e9, 1e9], hi = [-1e9, -1e9, -1e9];
    for (let i = 0; i < a.length; i += 3) for (let k = 0; k < 3; k++) { lo[k] = Math.min(lo[k], a[i + k]); hi[k] = Math.max(hi[k], a[i + k]); }
    return mul(add(lo, hi), 0.5);
  }
  meshes.forEach((m) => { m.buf = buffers(m.geo); m.c = centre(m.geo); m.alpha = m.color[3]; m.geo = null; });

  // Cable meshes are rebuilt while the model explodes, because their ends move with different groups.
  const cableMeshes = [];
  cables.forEach((cb) => {
    const colors = Array.isArray(cb.color[0]) ? cb.color : [cb.color];
    cb.offsets.forEach((o, i) => cableMeshes.push({ ent: cb.ent, cb, off: o, color: colors[i % colors.length], emit: cb.emit, group: 's', cable: true }));
    if (cb.plugs) cableMeshes.push({ ent: cb.ent, cb, plugMesh: true, color: cb.ent === 'molex' ? hex('#e8e3d6') : hex('#0f1216'), edge: cb.ent === 'molex' ? hex('#9a958a', 0.8) : hex('#9fd8ff', 0.6), group: 's' });
  });
  function groupOffset(g, e) { return mul(GROUPS[g] || GROUPS.s, e); }
  function rebuildCables(e) {
    for (const m of cableMeshes) {
      const g = new Geo();
      if (m.plugMesh) m.cb.plugs.forEach((p) => g.box(...p));
      else g.tube(route(m.cb.ctrl.map((p) => add(add([p[0], p[1], p[2]], m.off), groupOffset(p[3], e))), 12), m.cb.r, 8);
      if (!m.buf) { m.buf = buffers(g, true); m.c = centre(g); m.alpha = 1; continue; }
      gl.bindBuffer(gl.ARRAY_BUFFER, m.buf.tb); gl.bufferData(gl.ARRAY_BUFFER, new Float32Array(g.t), gl.DYNAMIC_DRAW);
      gl.bindBuffer(gl.ARRAY_BUFFER, m.buf.nb); gl.bufferData(gl.ARRAY_BUFFER, new Float32Array(g.n), gl.DYNAMIC_DRAW);
      m.buf.tc = g.t.length / 3;
    }
  }
  rebuildCables(0);
  meshes.push(...cableMeshes);

  const grid = new Geo();
  for (let x = -140; x <= 320; x += 20) grid.seg([x, -120, -3.3], [x, 400, -3.3]);
  for (let y = -120; y <= 400; y += 20) grid.seg([-140, y, -3.3], [320, y, -3.3]);
  const gridBuf = buffers(grid);

  /* ---------- state ---------- */
  const home = { yaw: -0.72, pitch: 0.4, dist: 760 };
  const cam = { yaw: home.yaw, pitch: home.pitch, dist: home.dist, target: [92, 150, 92] };
  let explode = 0, explodeTo = 0, explodeFrom = 0, explodeT0 = 0;
  let showCase = true, selected = null, hover = null, spinning = !reduce, lastT = performance.now(), fanAngle = 0;
  let tween = null, needsDraw = true;

  function homeTarget() { return [92, 150, 92 + 34 * explode]; }
  function entCentre(id) {
    const ms = meshes.filter((m) => m.ent === id && m.buf && (m.buf.tc || m.buf.lc));
    const sum = ms.reduce((a, m) => add(a, add(m.c, m.cable ? [0, 0, 0] : groupOffset(m.group, explode))), [0, 0, 0]);
    return mul(sum, 1 / ms.length);
  }
  function aimTarget() {
    return selected && selected !== 'case' ? add(mul(homeTarget(), 0.45), mul(entCentre(selected), 0.55)) : homeTarget();
  }
  function goTo(view, ms = 750) {
    tween = { from: { ...cam, target: cam.target.slice() }, to: view, t0: performance.now(), ms: reduce ? 1 : ms };
    needsDraw = true;
  }

  /* ---------- UI ---------- */
  const el = (tag, cls, html) => { const e = document.createElement(tag); if (cls) e.className = cls; if (html != null) e.innerHTML = html; return e; };
  const bar = el('div', 'model__bar');
  const views = el('div', 'model__group'), tools = el('div', 'model__group');
  const btn = (label, title, onClick, pressed) => {
    const b = el('button', 'model__btn', label); b.type = 'button'; b.title = title;
    if (pressed != null) b.setAttribute('aria-pressed', String(pressed));
    b.addEventListener('click', onClick); return b;
  };
  const VIEWS = { Front: { yaw: -0.38, pitch: 0.22 }, Back: { yaw: Math.PI - 0.62, pitch: 0.34 }, Top: { yaw: -0.25, pitch: 1.2 } };
  for (const [name, v] of Object.entries(VIEWS)) {
    views.append(btn(name, `${name} view`, () => { spinning = false; goTo({ ...v, dist: cam.dist, target: aimTarget() }); }));
  }
  const explodeBtn = btn('Explode', 'Pull the parts apart', () => setExplode(explodeTo ? 0 : 1), false);
  const caseBtn = btn('Case', 'Show or hide the printed case', () => { showCase = !showCase; caseBtn.setAttribute('aria-pressed', String(showCase)); needsDraw = true; }, true);
  tools.append(explodeBtn, caseBtn);
  bar.append(views, tools);
  const zoom = el('div', 'model__zoom');
  zoom.append(btn('+', 'Zoom in', () => zoomBy(0.85)), btn('−', 'Zoom out', () => zoomBy(1 / 0.85)));
  const info = el('div', 'model__info'); info.setAttribute('aria-live', 'polite');
  const tip = el('div', 'model__tip');
  root.append(bar, zoom, info, tip);
  const list = el('ul', 'model__parts');
  const chips = {};
  ENTS.forEach((e) => {
    const li = el('li'), b = el('button', 'model__part', `<i style="--c:${e.dot}"></i>${e.name}`);
    b.type = 'button'; b.setAttribute('aria-pressed', 'false');
    b.addEventListener('click', () => select(selected === e.id ? null : e.id, true));
    chips[e.id] = b; li.append(b); list.append(li);
  });
  root.after(list);

  function setInfo() {
    const e = selected && ENT[selected];
    info.innerHTML = e
      ? `<span class="model__k">${String(e.n).padStart(2, '0')} · ${e.kind}</span><strong>${e.name}</strong><span>${e.desc}</span>`
      : `<span class="model__k">Homelab NAS · 3D</span><span>Drag to turn it, tap a part to see what it is, or press Explode.</span>`;
  }
  function select(id, fromList) {
    selected = id;
    for (const [k, b] of Object.entries(chips)) b.setAttribute('aria-pressed', String(k === id));
    if (id === 'case' && !showCase) { showCase = true; caseBtn.setAttribute('aria-pressed', 'true'); }
    setInfo();
    spinning = false;
    goTo({ yaw: cam.yaw, pitch: cam.pitch, dist: cam.dist, target: aimTarget() }, fromList ? 750 : 500);
  }
  function setExplode(v) {
    explodeFrom = explode; explodeTo = v; explodeT0 = performance.now();
    explodeBtn.setAttribute('aria-pressed', String(!!v));
    needsDraw = true;
  }
  function zoomBy(f) { spinning = false; tween = null; cam.dist = Math.min(1400, Math.max(320, cam.dist * f)); needsDraw = true; }
  setInfo();

  /* ---------- drawing ---------- */
  let VP = null, eye = null;
  function resize() {
    const dpr = Math.min(window.devicePixelRatio || 1, 2);
    const w = Math.round(canvas.clientWidth * dpr), h = Math.round(canvas.clientHeight * dpr);
    if (w && h && (canvas.width !== w || canvas.height !== h)) { canvas.width = w; canvas.height = h; needsDraw = true; }
  }
  function camera() {
    const aspect = canvas.width / canvas.height;
    const fit = aspect < 1.2 ? Math.pow(1.2 / aspect, 0.85) : 1;
    const d = cam.dist * fit * (1 + 0.26 * explode), cp = Math.cos(cam.pitch);
    eye = add(cam.target, [d * cp * Math.sin(cam.yaw), -d * cp * Math.cos(cam.yaw), d * Math.sin(cam.pitch)]);
    VP = mat4mul(perspective((32 * Math.PI) / 180, aspect, 20, 4000), lookAt(eye, cam.target, [0, 0, 1]));
  }
  function modelMatrix(m) {
    const off = m.cable ? [0, 0, 0] : groupOffset(m.group, explode);
    return m.spin ? spinAbout(m.spin.c, fanAngle * m.spin.speed, off, m.spin.axis) : translate(off);
  }
  function bindAttrib(prog, name, buf) {
    const loc = prog[name]; if (loc < 0) return;
    gl.bindBuffer(gl.ARRAY_BUFFER, buf); gl.enableVertexAttribArray(loc); gl.vertexAttribPointer(loc, 3, gl.FLOAT, false, 0, 0);
  }
  const visible = (m) => showCase || !m.isCase;
  const SIG = [0.62, 0.85, 1];

  function drawFaces(m, M, xray) {
    if (!m.buf.tc || m.linesOnly) return;
    const sel = selected === m.ent, hov = hover === m.ent && !sel, dim = selected && !sel && m.ent !== 'case' ? 0.5 : 1;
    gl.useProgram(shade.p);
    gl.uniformMatrix4fv(shade.u.uVP, false, VP); gl.uniformMatrix4fv(shade.u.uM, false, M);
    gl.uniform3fv(shade.u.uEye, eye);
    let a = m.alpha;
    if (sel && a < 1) a = Math.max(a, m.isCase ? 0.12 : 0.62);
    if (xray) a = 0.28;
    gl.uniform4f(shade.u.uColor, m.color[0], m.color[1], m.color[2], a);
    const e = m.emit || [0, 0, 0], boost = xray ? 0.45 : sel ? 0.22 : hov ? 0.1 : 0;
    gl.uniform3f(shade.u.uEmit, e[0] + SIG[0] * boost, e[1] + SIG[1] * boost, e[2] + SIG[2] * boost);
    gl.uniform1f(shade.u.uLit, m.lit == null ? 1 : m.lit);
    gl.uniform1f(shade.u.uDim, dim);
    bindAttrib(shade, 'aPos', m.buf.tb); bindAttrib(shade, 'aNor', m.buf.nb);
    gl.drawArrays(gl.TRIANGLES, 0, m.buf.tc);
    gl.disableVertexAttribArray(1);
  }
  function drawLines(m, M, xray) {
    if (!m.buf.lc || !m.edge) return;
    const sel = selected === m.ent, dim = selected && !sel ? 0.45 : 1;
    gl.useProgram(flat.p);
    gl.uniformMatrix4fv(flat.u.uVP, false, VP); gl.uniformMatrix4fv(flat.u.uM, false, M);
    const c = sel ? [...SIG, xray ? 0.35 : 0.95] : [m.edge[0], m.edge[1], m.edge[2], m.edge[3] * dim];
    gl.uniform4fv(flat.u.uColor, c);
    bindAttrib(flat, 'aPos', m.buf.lb);
    gl.drawArrays(gl.LINES, 0, m.buf.lc);
  }

  function draw() {
    camera();
    gl.viewport(0, 0, canvas.width, canvas.height);
    gl.clearColor(0.043, 0.059, 0.078, 1);
    gl.clear(gl.COLOR_BUFFER_BIT | gl.DEPTH_BUFFER_BIT);
    gl.enable(gl.DEPTH_TEST); gl.depthFunc(gl.LEQUAL);
    gl.enable(gl.BLEND); gl.blendFunc(gl.SRC_ALPHA, gl.ONE_MINUS_SRC_ALPHA);
    gl.disableVertexAttribArray(1);

    // floor grid
    gl.depthMask(false);
    gl.useProgram(flat.p);
    gl.uniformMatrix4fv(flat.u.uVP, false, VP); gl.uniformMatrix4fv(flat.u.uM, false, translate([0, 0, 0]));
    gl.uniform4f(flat.u.uColor, 0.62, 0.85, 1, 0.055);
    bindAttrib(flat, 'aPos', gridBuf.lb); gl.drawArrays(gl.LINES, 0, gridBuf.lc);

    const list = meshes.filter(visible).map((m) => ({ m, M: modelMatrix(m) }));
    const opaque = list.filter((x) => x.m.alpha >= 1 && !x.m.linesOnly);
    const clear = list.filter((x) => x.m.alpha < 1 || x.m.linesOnly)
      .map((x) => ({ ...x, d: len(sub(add(x.m.c, x.m.cable ? [0, 0, 0] : groupOffset(x.m.group, explode)), eye)) }))
      .sort((a, b) => b.d - a.d);

    gl.depthMask(true);
    gl.enable(gl.POLYGON_OFFSET_FILL); gl.polygonOffset(1, 1);
    opaque.forEach((x) => drawFaces(x.m, x.M));
    gl.depthMask(false);
    opaque.forEach((x) => drawLines(x.m, x.M));
    clear.forEach((x) => { drawFaces(x.m, x.M); drawLines(x.m, x.M); });
    gl.disable(gl.POLYGON_OFFSET_FILL);

    if (selected) { // show the selection through anything in front of it
      gl.depthFunc(gl.ALWAYS);
      list.filter((x) => x.m.ent === selected).forEach((x) => { if (!x.m.buf.lc || x.m.cable) drawFaces(x.m, x.M, true); drawLines(x.m, x.M, true); });
      gl.depthFunc(gl.LEQUAL);
    }
    gl.depthMask(true);
  }

  /* ---------- picking: shells first, then everything else drawn over them ---------- */
  let fb = null, fbTex, fbDepth, fbW = 0, fbH = 0;
  function pick(px, py) {
    const w = Math.max(1, canvas.width >> 1), h = Math.max(1, canvas.height >> 1);
    if (!fb || w !== fbW || h !== fbH) {
      if (fb) { gl.deleteFramebuffer(fb); gl.deleteTexture(fbTex); gl.deleteRenderbuffer(fbDepth); }
      fb = gl.createFramebuffer(); fbTex = gl.createTexture(); fbDepth = gl.createRenderbuffer();
      gl.bindTexture(gl.TEXTURE_2D, fbTex);
      gl.texImage2D(gl.TEXTURE_2D, 0, gl.RGBA, w, h, 0, gl.RGBA, gl.UNSIGNED_BYTE, null);
      gl.texParameteri(gl.TEXTURE_2D, gl.TEXTURE_MIN_FILTER, gl.NEAREST);
      gl.bindRenderbuffer(gl.RENDERBUFFER, fbDepth); gl.renderbufferStorage(gl.RENDERBUFFER, gl.DEPTH_COMPONENT16, w, h);
      gl.bindFramebuffer(gl.FRAMEBUFFER, fb);
      gl.framebufferTexture2D(gl.FRAMEBUFFER, gl.COLOR_ATTACHMENT0, gl.TEXTURE_2D, fbTex, 0);
      gl.framebufferRenderbuffer(gl.FRAMEBUFFER, gl.DEPTH_ATTACHMENT, gl.RENDERBUFFER, fbDepth);
      fbW = w; fbH = h;
    }
    camera();
    gl.bindFramebuffer(gl.FRAMEBUFFER, fb);
    gl.viewport(0, 0, w, h);
    gl.clearColor(0, 0, 0, 0); gl.clear(gl.COLOR_BUFFER_BIT | gl.DEPTH_BUFFER_BIT);
    gl.disable(gl.BLEND); gl.enable(gl.DEPTH_TEST); gl.depthFunc(gl.LEQUAL); gl.depthMask(true);
    gl.useProgram(flat.p); gl.uniformMatrix4fv(flat.u.uVP, false, VP);
    const pass = (shells) => meshes.forEach((m) => {
      if (m.nopick || !visible(m) || !m.buf.tc || m.linesOnly || !!m.shell !== shells) return;
      gl.uniformMatrix4fv(flat.u.uM, false, modelMatrix(m));
      gl.uniform4f(flat.u.uColor, ENT[m.ent].n / 255, 0, 0, 1);
      bindAttrib(flat, 'aPos', m.buf.tb); gl.drawArrays(gl.TRIANGLES, 0, m.buf.tc);
    });
    pass(true); gl.clear(gl.DEPTH_BUFFER_BIT); pass(false);
    const out = new Uint8Array(4);
    const rx = Math.min(w - 1, Math.floor((px / canvas.clientWidth) * w)), ry = Math.min(h - 1, Math.floor((1 - py / canvas.clientHeight) * h));
    gl.readPixels(rx, ry, 1, 1, gl.RGBA, gl.UNSIGNED_BYTE, out);
    gl.bindFramebuffer(gl.FRAMEBUFFER, null);
    gl.enable(gl.BLEND);
    needsDraw = true;
    return out[3] ? (ENTS[out[0] - 1] || null) : null;
  }

  /* ---------- input ---------- */
  const pointers = new Map();
  let moved = 0, pinch = 0, hoverTimer = 0;
  const local = (e) => { const r = canvas.getBoundingClientRect(); return [e.clientX - r.left, e.clientY - r.top]; };
  canvas.addEventListener('pointerdown', (e) => {
    try { canvas.setPointerCapture(e.pointerId); } catch (err) { /* synthetic or already released */ }
    pointers.set(e.pointerId, [e.clientX, e.clientY]);
    moved = 0; spinning = false; tween = null;
    if (pointers.size === 2) { const [a, b] = [...pointers.values()]; pinch = Math.hypot(a[0] - b[0], a[1] - b[1]); }
    if (e.pointerType === 'mouse') canvas.focus({ preventScroll: true });
  });
  canvas.addEventListener('pointermove', (e) => {
    if (!pointers.has(e.pointerId)) {
      if (e.pointerType !== 'mouse') return;
      clearTimeout(hoverTimer);
      const [x, y] = local(e);
      hoverTimer = setTimeout(() => {
        const hit = pick(x, y);
        hover = hit && hit.id !== 'case' ? hit.id : null;
        canvas.style.cursor = hover ? 'pointer' : '';
        tip.textContent = hover ? ENT[hover].name : '';
        tip.style.left = `${x}px`; tip.style.top = `${y}px`;
        tip.classList.toggle('is-on', !!hover);
        kick();
      }, 60);
      return;
    }
    const prev = pointers.get(e.pointerId), dx = e.clientX - prev[0], dy = e.clientY - prev[1];
    pointers.set(e.pointerId, [e.clientX, e.clientY]);
    if (pointers.size === 1) {
      cam.yaw -= dx * 0.0085;
      cam.pitch = Math.min(1.45, Math.max(-0.12, cam.pitch + dy * 0.0075));
      moved += Math.abs(dx) + Math.abs(dy);
    } else if (pointers.size === 2) {
      const [a, b] = [...pointers.values()], d = Math.hypot(a[0] - b[0], a[1] - b[1]);
      if (pinch) cam.dist = Math.min(1400, Math.max(320, cam.dist * (pinch / d)));
      pinch = d; moved += 10;
    }
    tip.classList.remove('is-on');
    needsDraw = true;
  });
  const release = (e) => {
    if (!pointers.has(e.pointerId)) return;
    pointers.delete(e.pointerId);
    if (e.type === 'pointerup' && moved < 6 && pointers.size === 0) {
      const [x, y] = local(e), hit = pick(x, y);
      select(hit && hit.id !== 'case' ? (hit.id === selected ? null : hit.id) : null);
    }
    if (pointers.size < 2) pinch = 0;
  };
  canvas.addEventListener('pointerup', release);
  canvas.addEventListener('pointercancel', release);
  canvas.addEventListener('pointerleave', () => { tip.classList.remove('is-on'); if (hover) { hover = null; needsDraw = true; } });
  canvas.addEventListener('wheel', (e) => {
    if (!e.ctrlKey && document.activeElement !== canvas) return;
    e.preventDefault();
    zoomBy(Math.exp(e.deltaY * (e.ctrlKey ? 0.01 : 0.0012)));
  }, { passive: false });
  canvas.addEventListener('keydown', (e) => {
    const k = e.key;
    if (k === 'ArrowLeft' || k === 'ArrowRight') cam.yaw += k === 'ArrowLeft' ? 0.12 : -0.12;
    else if (k === 'ArrowUp' || k === 'ArrowDown') cam.pitch = Math.min(1.45, Math.max(-0.12, cam.pitch + (k === 'ArrowUp' ? 0.1 : -0.1)));
    else if (k === '+' || k === '=') zoomBy(0.88);
    else if (k === '-') zoomBy(1 / 0.88);
    else if (k === 'e' || k === 'E') setExplode(explodeTo ? 0 : 1);
    else if (k === 'Escape') select(null);
    else return;
    e.preventDefault(); spinning = false; needsDraw = true;
  });

  /* ---------- loop ---------- */
  let running = false, raf = 0;
  function frame(now) {
    raf = 0;
    const dt = Math.min(0.05, (now - lastT) / 1000); lastT = now;
    resize();
    if (explode !== explodeTo) {
      const t = Math.min(1, (now - explodeT0) / (reduce ? 1 : 1100));
      explode = lerp(explodeFrom, explodeTo, ease(t));
      if (t >= 1) explode = explodeTo;
      rebuildCables(explode);
      if (!tween) cam.target = aimTarget();
      needsDraw = true;
    }
    if (tween) {
      const t = Math.min(1, (now - tween.t0) / tween.ms), k = ease(t), f = tween.from, to = tween.to;
      let dy = to.yaw - f.yaw; dy = Math.atan2(Math.sin(dy), Math.cos(dy));
      cam.yaw = f.yaw + dy * k; cam.pitch = lerp(f.pitch, to.pitch, k); cam.dist = lerp(f.dist, to.dist, k);
      cam.target = f.target.map((v, i) => lerp(v, to.target[i], k));
      if (t >= 1) tween = null;
      needsDraw = true;
    }
    if (spinning) { cam.yaw += dt * 0.16; needsDraw = true; }
    if (!reduce) { fanAngle += dt; needsDraw = true; }
    if (needsDraw) { needsDraw = false; draw(); }
    if (running && (!reduce || tween || explode !== explodeTo || needsDraw)) raf = requestAnimationFrame(frame);
  }
  function kick() { if (running && !raf) { lastT = performance.now(); raf = requestAnimationFrame(frame); } }
  ['pointerdown', 'pointermove', 'keydown', 'click', 'wheel'].forEach((t) => root.addEventListener(t, () => kick(), { passive: true }));
  root.addEventListener('click', () => kick());
  function setRunning(on) { running = on; if (on) { needsDraw = true; kick(); } else if (raf) { cancelAnimationFrame(raf); raf = 0; } }

  new ResizeObserver(() => { resize(); needsDraw = true; kick(); }).observe(canvas);
  if ('IntersectionObserver' in window) {
    new IntersectionObserver(([e]) => setRunning(e.isIntersecting && !document.hidden), { rootMargin: '120px' }).observe(root);
  } else setRunning(true);
  document.addEventListener('visibilitychange', () => setRunning(!document.hidden && root.getBoundingClientRect().bottom > 0));
  resize(); camera(); draw();
  root.classList.add('is-live');
})();
