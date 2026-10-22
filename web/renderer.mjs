const shader = /* wgsl */ `
struct Globals { viewport: vec2f, camera: vec2f, zoom: f32, time: f32, padding: vec2f }
struct Fish { pose: vec4f, color: vec4f, features: vec4f }
@group(0) @binding(0) var<uniform> globals: Globals;
@group(0) @binding(1) var<storage, read> instances: array<Fish>;
struct Output {
  @builtin(position) position: vec4f,
  @location(0) uv: vec2f,
  @location(1) color: vec4f,
  @location(2) features: vec4f,
}
@vertex fn vertexMain(@builtin(vertex_index) vertex: u32, @builtin(instance_index) index: u32) -> Output {
  let corners = array<vec2f, 6>(vec2f(-1,-1),vec2f(1,-1),vec2f(1,1),vec2f(-1,-1),vec2f(1,1),vec2f(-1,1));
  let fish = instances[index];
  let uv = corners[vertex] * 1.6;
  let point = uv * fish.pose.z;
  let c = cos(fish.pose.w); let s = sin(fish.pose.w);
  let rotated = vec2f(c * point.x - s * point.y, s * point.x + c * point.y);
  let pixel = (fish.pose.xy + rotated - globals.camera) * globals.zoom + globals.viewport * .5;
  var output: Output;
  output.position = vec4f(pixel / globals.viewport * vec2f(2,-2) + vec2f(-1,1), 0, 1);
  output.uv = uv; output.color = fish.color; output.features = fish.features;
  return output;
}
@fragment fn fragmentMain(input: Output) -> @location(0) vec4f {
  var q = input.uv;
  let cpu = min(input.features.x, 2.0);
  let phase = input.features.y;
  let wag = sin(globals.time * (4.0 + cpu * 4.0) + phase) * .13;
  let bodyWidth = .30 + fract(phase * .17) * .13;
  let body = length(vec2f(q.x / .74, q.y / bodyWidth)) - 1.0;
  let tail = max(max(-1.2-q.x, q.x+.5), abs(q.y-wag) - (-q.x-.47)*.57);
  let fin = max(abs(q.x+.10)-.30, abs(q.y+.29)-.12);
  let shape = min(body, min(tail * 3.0, fin * 3.0));
  let edge = max(fwidth(shape), .012);
  let silhouette = 1.0 - smoothstep(-edge, edge, shape);
  let stripes = .88 + .12 * sin(q.x * (11.0 + fract(phase) * 6.0) + q.y * 3.0);
  var color = input.color.rgb * stripes * (1.0 - q.y * .25);
  let eye = 1.0 - smoothstep(.04,.065,length(q-vec2f(.43,-.065)));
  let glint = 1.0 - smoothstep(.012,.024,length(q-vec2f(.445,-.085)));
  color = mix(color, vec3f(.015,.065,.09), eye);
  color = mix(color, vec3f(.94,.99,1.0), glint);
  let glow = exp(-dot(q*vec2f(.7,1.7),q*vec2f(.7,1.7))*2.5) * (.025 + cpu*.20);
  let radius = length(q);
  let theta = atan2(q.y,q.x) + globals.time*.22;
  let dots = (1.0-smoothstep(.04,.075,abs(radius-1.05))) *
             (1.0-smoothstep(.10,.30,abs(sin(theta*max(input.features.z,1.0)*.5))));
  let satellites = dots * select(0.0,.55,input.features.z > 1.0);
  let ring = (1.0-smoothstep(.015,.035,abs(radius-1.42))) * input.features.w;
  let alpha = min(1.0, silhouette*.95 + glow + satellites + ring*.8) * input.color.a;
  let lit = mix(input.color.rgb*.75, color, silhouette);
  return vec4f(mix(lit, vec3f(.8,1.0,.95), ring*.65), alpha);
}
`;

function fishOnScreen(fish, camera, width, height) {
  const x = (fish.x - camera.x) * camera.zoom + width / 2;
  const y = (fish.y - camera.y) * camera.zoom + height / 2;
  const margin = fish.size * camera.zoom * 2 + 10;
  return (
    x > -margin && x < width + margin && y > -margin && y < height + margin
  );
}

class WebGPURenderer {
  static async create(canvas, onLost) {
    if (!navigator.gpu)
      throw new Error(
        "WebGPU requires a supported browser and HTTPS or localhost",
      );
    const adapter = await navigator.gpu.requestAdapter();
    if (!adapter) throw new Error("No WebGPU adapter is available");
    const device = await adapter.requestDevice();
    const renderer = new WebGPURenderer();
    renderer.device = device;
    renderer.canvas = canvas;
    renderer.name = "WebGPU";
    renderer.destroyed = false;
    try {
      const module = device.createShaderModule({
        label: "Process Aquarium fish",
        code: shader,
      });
      const info = await module.getCompilationInfo();
      const errors = info.messages.filter(
        (message) => message.type === "error",
      );
      if (errors.length)
        throw new Error(errors.map((error) => error.message).join("; "));
      const format = navigator.gpu.getPreferredCanvasFormat();
      renderer.pipeline = await device.createRenderPipelineAsync({
        layout: "auto",
        vertex: { module, entryPoint: "vertexMain" },
        fragment: {
          module,
          entryPoint: "fragmentMain",
          targets: [
            {
              format,
              blend: {
                color: {
                  srcFactor: "src-alpha",
                  dstFactor: "one-minus-src-alpha",
                },
                alpha: { srcFactor: "one", dstFactor: "one-minus-src-alpha" },
              },
            },
          ],
        },
        primitive: { topology: "triangle-list" },
      });
      renderer.context = canvas.getContext("webgpu");
      if (!renderer.context)
        throw new Error("Could not create a WebGPU canvas");
      renderer.context.configure({
        device,
        format,
        alphaMode: "premultiplied",
      });
      renderer.uniform = device.createBuffer({
        size: 32,
        usage: GPUBufferUsage.UNIFORM | GPUBufferUsage.COPY_DST,
      });
      renderer.capacity = 0;
      renderer.reserve(1);
      device.lost.then((info) => {
        if (!renderer.destroyed) onLost(info.message || "GPU device lost");
      });
      device.addEventListener("uncapturederror", (event) =>
        onLost(event.error.message),
      );
      return renderer;
    } catch (error) {
      renderer.destroyed = true;
      device.destroy();
      throw error;
    }
  }
  reserve(count) {
    if (count <= this.capacity) return;
    this.capacity = 2 ** Math.ceil(Math.log2(Math.max(1, count)));
    this.buffer?.destroy();
    this.buffer = this.device.createBuffer({
      size: this.capacity * 48,
      usage: GPUBufferUsage.STORAGE | GPUBufferUsage.COPY_DST,
    });
    this.data = new Float32Array(this.capacity * 12);
    this.bindGroup = this.device.createBindGroup({
      layout: this.pipeline.getBindGroupLayout(0),
      entries: [
        { binding: 0, resource: { buffer: this.uniform } },
        { binding: 1, resource: { buffer: this.buffer } },
      ],
    });
  }
  render(world, camera, width, height) {
    const ratio = Math.min(devicePixelRatio || 1, 2);
    const pixelWidth = Math.max(
      1,
      Math.min(
        this.device.limits.maxTextureDimension2D,
        Math.round(width * ratio),
      ),
    );
    const pixelHeight = Math.max(
      1,
      Math.min(
        this.device.limits.maxTextureDimension2D,
        Math.round(height * ratio),
      ),
    );
    if (this.canvas.width !== pixelWidth) this.canvas.width = pixelWidth;
    if (this.canvas.height !== pixelHeight) this.canvas.height = pixelHeight;
    const fish = [...world.fish.values()].filter((f) =>
      fishOnScreen(f, camera, width, height),
    );
    this.reserve(fish.length);
    let index = 0;
    for (const item of fish) {
      this.data.set(
        [
          item.x,
          item.y,
          item.size,
          item.angle,
          ...item.color,
          item.alpha,
          Math.min(item.p.cpu_percent / 100, 1) + item.flash,
          item.phase,
          Math.min(item.p.num_threads, 12),
          item.key === world.selection ? 1 : 0,
        ],
        index,
      );
      index += 12;
    }
    this.device.queue.writeBuffer(
      this.uniform,
      0,
      new Float32Array([
        width,
        height,
        camera.x,
        camera.y,
        camera.zoom,
        world.time,
        0,
        0,
      ]),
    );
    if (index)
      this.device.queue.writeBuffer(this.buffer, 0, this.data, 0, index);
    const encoder = this.device.createCommandEncoder();
    const pass = encoder.beginRenderPass({
      colorAttachments: [
        {
          view: this.context.getCurrentTexture().createView(),
          clearValue: { r: 0, g: 0, b: 0, a: 0 },
          loadOp: "clear",
          storeOp: "store",
        },
      ],
    });
    if (fish.length) {
      pass.setPipeline(this.pipeline);
      pass.setBindGroup(0, this.bindGroup);
      pass.draw(6, fish.length);
    }
    pass.end();
    this.device.queue.submit([encoder.finish()]);
  }
  destroy() {
    this.destroyed = true;
    this.device.destroy();
  }
}

export class CanvasRenderer {
  constructor(canvas) {
    this.canvas = canvas;
    this.context = canvas.getContext("2d");
    if (!this.context) throw new Error("Canvas rendering is unavailable");
    this.name = "Canvas 2D";
  }
  render(world, camera, width, height) {
    const ratio = Math.min(devicePixelRatio || 1, 2),
      ctx = this.context;
    if (this.canvas.width !== Math.round(width * ratio))
      this.canvas.width = Math.max(1, Math.round(width * ratio));
    if (this.canvas.height !== Math.round(height * ratio))
      this.canvas.height = Math.max(1, Math.round(height * ratio));
    ctx.setTransform(ratio, 0, 0, ratio, 0, 0);
    ctx.clearRect(0, 0, width, height);
    for (const fish of world.fish.values()) {
      if (!fishOnScreen(fish, camera, width, height)) continue;
      const size = fish.size * camera.zoom,
        rgb = fish.color.map((c) => Math.round(c * 255));
      const color = `rgb(${rgb.join(",")})`;
      ctx.save();
      ctx.translate(
        (fish.x - camera.x) * camera.zoom + width / 2,
        (fish.y - camera.y) * camera.zoom + height / 2,
      );
      ctx.rotate(fish.angle);
      ctx.globalAlpha = Math.max(0, fish.alpha);
      const glow = ctx.createRadialGradient(0, 0, 0, 0, 0, size * 1.7);
      glow.addColorStop(
        0,
        `rgba(${rgb.join(",")},${0.08 + Math.min(1, fish.p.cpu_percent / 100) * 0.24 + fish.flash * 0.25})`,
      );
      glow.addColorStop(1, `rgba(${rgb.join(",")},0)`);
      ctx.fillStyle = glow;
      ctx.fillRect(-size * 1.7, -size * 1.7, size * 3.4, size * 3.4);
      ctx.fillStyle = color;
      const wag =
        Math.sin(
          world.time * (4 + Math.min(1, fish.p.cpu_percent / 100) * 4) +
            fish.phase,
        ) *
        size *
        0.13;
      ctx.beginPath();
      ctx.moveTo(-size * 0.5, 0);
      ctx.lineTo(-size * 1.2, -size * 0.35 + wag);
      ctx.lineTo(-size * 1.2, size * 0.35 + wag);
      ctx.closePath();
      ctx.fill();
      ctx.beginPath();
      ctx.ellipse(
        0,
        0,
        size * 0.74,
        size * (0.3 + ((fish.phase * 0.17) % 1) * 0.13),
        0,
        0,
        Math.PI * 2,
      );
      ctx.fill();
      ctx.fillStyle = "#06232b";
      ctx.beginPath();
      ctx.arc(size * 0.43, -size * 0.065, size * 0.055, 0, Math.PI * 2);
      ctx.fill();
      ctx.fillStyle = "#e5fff7";
      ctx.beginPath();
      ctx.arc(size * 0.445, -size * 0.085, size * 0.018, 0, Math.PI * 2);
      ctx.fill();
      ctx.fillStyle = color;
      ctx.globalAlpha = fish.alpha * 0.5;
      const threads = Math.min(fish.p.num_threads, 12);
      if (threads > 1)
        for (let i = 0; i < threads; i++) {
          const theta = (i / threads) * Math.PI * 2 + world.time * 0.22;
          ctx.beginPath();
          ctx.arc(
            Math.cos(theta) * size * 1.05,
            Math.sin(theta) * size * 1.05,
            1.2,
            0,
            Math.PI * 2,
          );
          ctx.fill();
        }
      if (fish.key === world.selection) {
        ctx.globalAlpha = fish.alpha * 0.8;
        ctx.strokeStyle = "#caffee";
        ctx.lineWidth = 1;
        ctx.beginPath();
        ctx.arc(0, 0, size * 1.42, 0, Math.PI * 2);
        ctx.stroke();
      }
      ctx.restore();
    }
  }
  destroy() {}
}

export function freshCanvas(canvas) {
  const fresh = canvas.cloneNode(false);
  canvas.replaceWith(fresh);
  return fresh;
}

export async function createRenderer(
  canvas,
  onLost,
  { forceCanvas = false } = {},
) {
  if (!forceCanvas) {
    try {
      return await WebGPURenderer.create(canvas, onLost);
    } catch (error) {
      const renderer = new CanvasRenderer(freshCanvas(canvas));
      renderer.fallbackReason = error.message;
      return renderer;
    }
  }
  return new CanvasRenderer(canvas);
}
