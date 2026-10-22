// Native Fish behavior, measured in 30 Hz simulation frames. No DOM/GPU/OS.
export const TAU = Math.PI * 2;
export const clamp = (x, low, high) => Math.max(low, Math.min(high, x));
export function hash(text) {
  let value = 2166136261;
  for (const char of String(text))
    value = Math.imul(value ^ char.codePointAt(0), 16777619);
  return value >>> 0;
}
export function colorOf(name) {
  const h = (hash(name) % 360) / 60,
    i = Math.floor(h),
    f = h - i;
  const v = 0.9,
    p = v * 0.3,
    q = v * (1 - 0.7 * f),
    t = v * (1 - 0.7 * (1 - f));
  return [
    [v, t, p],
    [q, v, p],
    [p, v, t],
    [p, q, v],
    [t, p, v],
    [v, p, q],
  ][i].map((x) => Math.trunc(x * 255) / 255);
}
export function shapeOf(name) {
  name = name.toLowerCase();
  for (const [shape, terms] of [
    ["shark", ["chrome", "firefox", "safari", "edge"]],
    ["tropical", ["code", "vscode", "atom", "sublime", "vim"]],
    ["ray", ["kernel", "system", "daemon", "service"]],
    ["dolphin", ["zoom", "slack", "discord", "teams"]],
    ["whale", ["photoshop", "docker", "virtualbox"]],
    ["eel", ["terminal", "bash", "zsh", "cmd"]],
  ])
    if (terms.some((term) => name.includes(term))) return shape;
  return "fish";
}
const exponential = (value, exponent, scale) =>
  1 +
  (Math.expm1((exponent * clamp(value, 0, 100)) / 100) / Math.expm1(exponent)) *
    scale;
export const speedLimit = (cpu) => 2 * Math.min(exponential(cpu, 4, 6), 8);
export const schoolSpeedLimit = (cpu) =>
  2.5 * Math.min(exponential(cpu, 4, 6), 8);
export function metrics(memory, cpu) {
  const factor = clamp(
    1 + Math.min(memory / 100, 1) ** 0.65 * 2.8 + Math.log1p(memory / 6) * 2.2,
    1,
    9,
  );
  return {
    size: 10 * factor,
    giant: memory >= 2 || factor >= 5.5,
    glow: (exponential(cpu, 3, 1) - 1) * 255,
    maxSpeed: speedLimit(cpu),
  };
}
export function makeFish(key, p, x, y, extent) {
  let seed = hash(key);
  const random = () => {
    seed = (Math.imul(seed, 1664525) + 1013904223) >>> 0;
    return seed / 2 ** 32;
  };
  return {
    key,
    p,
    x,
    y,
    vx: random() * 2 - 1,
    vy: random() * 2 - 1,
    targetX: x,
    targetY: y,
    angle: 0,
    phase: random() * TAU,
    cycle: 0,
    tail: 0,
    age: 0,
    random,
    behavior: Math.floor(random() * 101),
    decision: 40 + Math.floor(random() * 41),
    personality: 0.7 + random() * 0.6,
    extent,
    school: [],
    isolated: false,
    isolatedSchool: false,
    orbit: null,
    orbitAngle: random() * TAU,
    spawn: 0,
    death: 0,
    dying: false,
    fork: 0,
    exec: 0,
    pulse: 0,
    talk: 0,
    partners: [],
    message: "",
    color: colorOf(p.name),
    shape: shapeOf(p.name),
    ...metrics(p.memory_percent, p.cpu_percent),
    alpha: 0,
    flash: 0,
  };
}
export function updateMetrics(f, p) {
  f.p = p;
  f.color = colorOf(p.name);
  f.shape = shapeOf(p.name);
  Object.assign(f, metrics(p.memory_percent, p.cpu_percent));
  f.vx = clamp(f.vx, -f.maxSpeed, f.maxSpeed);
  f.vy = clamp(f.vy, -f.maxSpeed, f.maxSpeed);
}
export function appearance(f, highlight = false) {
  let size = f.size,
    alpha = 255,
    [r, g, b] = f.color.map((c) => Math.round(c * 255));
  if (f.school.length > 1) size *= 1.2;
  if (f.giant) {
    size *= 1 + 0.3 * Math.sin(f.pulse);
    r = Math.min(255, r + Math.trunc(50 * (1 + 0.5 * Math.sin(f.pulse))));
    b = Math.max(0, b - 20);
  }
  if (f.spawn < 1) {
    size *= 0.1 + 0.9 * f.spawn;
    alpha = Math.trunc(255 * f.spawn);
  }
  if (f.dying) {
    size *= 1 - f.death;
    alpha = Math.trunc(255 * (1 - f.death));
  }
  if (f.fork > 0) {
    size *= 1 + (f.fork / 60) * 0.3;
    [r, g, b] = [r, g, b].map((c) => Math.trunc(c + ((255 - c) * f.fork) / 60));
  }
  if (f.glow > 0) {
    const boost = (Math.expm1((3 * f.glow) / 255) / Math.expm1(3)) * 150;
    [r, g, b] = [r, g, b].map((c) => Math.min(255, Math.trunc(c + boost)));
  }
  if (f.exec > 0) {
    const shift = Math.trunc((1 - f.exec / 30) * 180);
    [r, g, b] = [r, g, b].map((c) => (c + shift) % 255);
  }
  if (highlight && (f.school.length < 2 || f.isolatedSchool))
    alpha = Math.trunc(alpha * 0.25);
  return {
    size,
    alpha: clamp(alpha, 0, 255) / 255,
    color: [r, g, b].map((c) => c / 255),
  };
}
export function satellites(f, size = f.size) {
  const count = Math.min(Math.max(0, f.p.num_threads - 1), 14),
    threads = Math.min(f.p.num_threads, 15);
  const radius = size * (1.8 + threads * 0.16 + Math.log1p(threads) * 0.06);
  return Array.from({ length: count }, (_, i) => {
    const a = (TAU * i) / count + f.age * 0.018;
    return [f.x + Math.cos(a) * radius, f.y + Math.sin(a) * radius];
  });
}
const sameSchool = (a, b) => a.school.length > 0 && a.school === b.school;
export function flocking(f, nearby) {
  let sx = 0,
    sy = 0,
    ax = 0,
    ay = 0,
    cx = 0,
    cy = 0,
    sn = 0,
    an = 0,
    cn = 0;
  for (const o of nearby) {
    const dx = f.x - o.x,
      dy = f.y - o.y,
      d = Math.hypot(dx, dy);
    if (d > 0 && d < 30) {
      sx += (dx * 30) / d;
      sy += (dy * 30) / d;
      sn++;
    }
    if (d > 0 && d < 60) {
      ax += o.vx;
      ay += o.vy;
      an++;
    }
    if (d > 0 && d < 120) {
      cx += o.x;
      cy += o.y;
      cn++;
    }
  }
  let x =
    (sn ? (sx / sn) * 2 : 0) +
    (an ? (ax / an - f.vx) * 1.5 : 0) +
    (cn ? (cx / cn - f.x) * 0.025 : 0);
  let y =
    (sn ? (sy / sn) * 2 : 0) +
    (an ? (ay / an - f.vy) * 1.5 : 0) +
    (cn ? (cy / cn - f.y) * 0.025 : 0);
  const norm = Math.hypot(x, y);
  if (norm > 0.5) {
    x = (x / norm) * 0.5;
    y = (y / norm) * 0.5;
  }
  return [x, y];
}
export function kineticEnergy(f, nearby) {
  return (
    0.5 *
      Math.max(f.p.memory_percent, 0.1) *
      Math.max(f.p.cpu_percent, 0.1) ** 2 +
    nearby.filter((o) => o !== f && sameSchool(f, o)).length * 25
  );
}
export function updateFish(f, nearby, attraction = [0, 0]) {
  f.age++;
  if (f.giant) f.pulse = (f.pulse + 0.15) % TAU;
  f.spawn = Math.min(1, f.spawn + 0.05);
  if (f.dying) {
    f.death = Math.min(1, f.death + 0.03);
    f.alpha = appearance(f).alpha;
    return f.death < 1;
  }
  f.fork = Math.max(0, f.fork - 1);
  f.exec = Math.max(0, f.exec - 1);
  f.flash = f.exec / 30;
  if (f.talk > 0 && --f.talk === 0) {
    f.message = "";
    f.partners = [];
  }
  f.behavior++;
  const school = nearby.filter((o) => sameSchool(f, o));
  const leader = school.reduce(
    (a, o) => (o.p.cpu_percent > a.p.cpu_percent ? o : a),
    f,
  );
  const random = (low, high) => low + f.random() * (high - low),
    bound = f.extent;
  if (f.behavior % (f.decision * (leader === f ? 1 : 2)) === 0) {
    f.targetX =
      leader === f
        ? random(-bound, bound)
        : clamp(
            leader.targetX + random(-200, 200) * f.personality,
            -bound,
            bound,
          );
    f.targetY =
      leader === f
        ? random(-bound, bound)
        : clamp(
            leader.targetY + random(-200, 200) * f.personality,
            -bound,
            bound,
          );
  }
  if (!f.orbit && Math.floor(f.random() * 600) === 0)
    f.orbit = {
      x: random(-bound * 0.5, bound * 0.5),
      y: random(-bound * 0.5, bound * 0.5),
      radius: random(80, 200),
      speed: random(0.02, 0.06),
      timer: 0,
      duration: 200 + Math.floor(f.random() * 301),
    };
  if (f.orbit) {
    const o = f.orbit;
    f.orbitAngle += o.speed;
    f.targetX = clamp(o.x + o.radius * Math.cos(f.orbitAngle), -bound, bound);
    f.targetY = clamp(o.y + o.radius * Math.sin(f.orbitAngle), -bound, bound);
    if (++o.timer >= o.duration) f.orbit = null;
  }
  if (school.length) {
    const [x, y] = flocking(f, school);
    f.vx += x * 1.5;
    f.vy += y * 1.5;
  }
  if (f.age % 3 === 0) {
    const energy = kineticEnergy(f, nearby);
    for (const o of nearby) {
      if (sameSchool(f, o)) continue;
      const dx = f.x - o.x,
        dy = f.y - o.y,
        d = Math.hypot(dx, dy),
        other = kineticEnergy(o, nearby);
      if (
        Math.abs(dx) + Math.abs(dy) < 250 &&
        d > 0 &&
        d < 180 &&
        energy < other
      ) {
        const force =
          ((180 - d) / 180) *
          0.015 *
          Math.min(other / Math.max(energy, 0.01), 4);
        f.vx += (dx / d) * force;
        f.vy += (dy / d) * force;
      }
    }
  }
  const dx = f.targetX - f.x,
    dy = f.targetY - f.y,
    d = Math.hypot(dx, dy);
  if (d > 5) {
    f.vx += (dx / d) * 0.4;
    f.vy += (dy / d) * 0.4;
  }
  f.vx += random(-0.05, 0.05) + attraction[0];
  f.vy += random(-0.05, 0.05) + attraction[1];
  // A solo fish needs the same cap as a school; the native loop omitted it
  // between metric refreshes. Keep runaway/multicore values bounded in both.
  const cap =
    f.school.length && nearby.length
      ? schoolSpeedLimit(
          (f.p.cpu_percent + school.reduce((n, o) => n + o.p.cpu_percent, 0)) /
            (school.length + 1),
        )
      : f.maxSpeed;
  f.vx = clamp(f.vx, -cap, cap);
  f.vy = clamp(f.vy, -cap, cap);
  f.x += f.vx;
  f.y += f.vy;
  for (const axis of ["x", "y"])
    if (Math.abs(f[axis]) > bound) {
      const sign = Math.sign(f[axis]);
      f[axis] = sign * bound;
      f["v" + axis] = -sign * Math.abs(f["v" + axis]) * 0.8;
      f[axis === "x" ? "targetX" : "targetY"] = random(
        -bound + 100,
        bound - 100,
      );
    }
  if (Math.abs(f.vx) > 0.1 || Math.abs(f.vy) > 0.1) {
    const delta = Math.atan2(
      Math.sin(Math.atan2(f.vy, f.vx) - f.angle),
      Math.cos(Math.atan2(f.vy, f.vx) - f.angle),
    );
    f.angle += delta * 0.1;
  }
  const speed = Math.hypot(f.vx, f.vy),
    cpu = exponential(f.p.cpu_percent, 2, 4);
  f.cycle += (0.1 + speed * 0.1) * cpu * f.personality;
  f.tail = Math.sin(f.cycle + f.phase) * Math.min((0.2 + speed * 0.1) * cpu, 1);
  f.alpha = appearance(f).alpha;
  return true;
}
export function worldSize(limit, count, width = 1200, height = 800) {
  const minimum = Math.max(width, height);
  if (!limit)
    return Math.max(
      minimum,
      count ? 3072 + (Math.max(201, count) - 200) * 6 : 3072,
    );
  return Math.max(
    minimum,
    limit <= 10
      ? minimum
      : limit <= 30
        ? 1024
        : limit <= 60
          ? 1536
          : limit <= 100
            ? 2048
            : limit <= 200
              ? 3072
              : 3072 + (limit - 200) * 6,
  );
}
