import {
  fishPrimitives,
  projectedFish,
  visibleFish,
  rasterPrimitive,
} from "./geometry.mjs";
import { appearance } from "./fish.mjs";
const shader = /* wgsl */ `
struct Globals { viewport: vec2f, clipCenter: vec2f, clipRadius: vec2f, padding: vec2f }
struct Primitive { a: vec4f, b: vec4f, color: vec4f }
@group(0) @binding(0) var<uniform> globals: Globals;
@group(0) @binding(1) var<storage,read> instances: array<Primitive>;
struct Output { @builtin(position) position: vec4f, @location(0) uv: vec2f,
  @location(1) color: vec4f, @location(2) @interpolate(flat) kind: f32, @location(3) pixel: vec2f }
@vertex fn vertexMain(@builtin(vertex_index) vertex:u32,@builtin(instance_index) index:u32)->Output {
  let p=instances[index];
  let corners=array<vec2f,6>(vec2f(-1,-1),vec2f(1,-1),vec2f(1,1),vec2f(-1,-1),vec2f(1,1),vec2f(-1,1));
  var pixel=p.a.xy+corners[vertex]*p.a.zw;
  if(p.b.z>1.5){let delta=p.a.zw-p.a.xy;let len=max(length(delta),.001);let direction=delta/len;pixel=(p.a.xy+p.a.zw)*.5+direction*corners[vertex].x*(len*.5)+vec2f(-direction.y,direction.x)*corners[vertex].y*.75;}
  else if(p.b.z>0.5){let indices=array<u32,6>(0,1,2,2,2,2);let points=array<vec2f,3>(p.a.xy,p.a.zw,p.b.xy);pixel=points[indices[vertex]];}
  var output:Output;
  output.position=vec4f(pixel/globals.viewport*vec2f(2,-2)+vec2f(-1,1),0,1);
  output.pixel=pixel;output.uv=corners[vertex];output.color=p.color;output.kind=p.b.z;
  return output;
}
@fragment fn fragmentMain(input:Output)->@location(0) vec4f {
  var alpha=input.color.a;
  let d=length(input.uv);let edge=max(fwidth(d),.001);
  let lineEdge=max(fwidth(input.uv.y),.001);
  if(input.kind<.5){alpha*=1-smoothstep(1-edge,1+edge,d);}
  if(input.kind>1.5){alpha*=1-smoothstep(.5-lineEdge,.5+lineEdge,abs(input.uv.y));}
  if(globals.clipRadius.x>0){let q=(input.pixel-globals.clipCenter)/max(globals.clipRadius,vec2f(1));alpha*=1-smoothstep(.94,1.0,dot(q,q));}
  return vec4f(input.color.rgb,alpha);
}
`;
function primitives(world, camera, width, height, minimumPixels = 0) {
  const result = [];
  for (const fish of world.fish.values()) {
    if (!visibleFish(fish, camera, width, height)) continue;
    const f = projectedFish(fish, camera, width, height),
      a = appearance(fish, world.highlightSchools);
    if (minimumPixels && a.size * camera.zoom < 2) {
      result.push({
        type: 0,
        points: [f.x, f.y, minimumPixels, minimumPixels, 0, 0],
        color: [...a.color, a.alpha],
      });
    } else
      result.push(
        ...fishPrimitives(
          f,
          camera.zoom,
          world.highlightSchools,
          world.quality,
        ).map(rasterPrimitive),
      );
  }
  return result;
}

// Geometry is shared by both backends. Coordinates and clipping stay in CSS
// pixels, so one device/canvas can render several independent worlds.
export function viewPrimitives({
  world,
  camera,
  rect,
  opacity = 1,
  minimumPixels = 0,
}) {
  return primitives(world, camera, rect.width, rect.height, minimumPixels).map(
    (shape) => {
      const points = [...shape.points],
        pairs = shape.type === 0 ? 1 : shape.type === 2 ? 2 : 3;
      for (let i = 0; i < pairs; i++) {
        points[i * 2] += rect.x;
        points[i * 2 + 1] += rect.y;
      }
      return {
        ...shape,
        points,
        color: [...shape.color.slice(0, 3), shape.color[3] * opacity],
      };
    },
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
      renderer.slots = [];
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
    for (const slot of this.slots) slot.bindGroup = this.bind(slot.uniform);
  }
  bind(uniform) {
    return this.device.createBindGroup({
      layout: this.pipeline.getBindGroupLayout(0),
      entries: [
        { binding: 0, resource: { buffer: uniform } },
        { binding: 1, resource: { buffer: this.buffer } },
      ],
    });
  }
  render(world, camera, width, height) {
    this.renderViews(
      [{ world, camera, rect: { x: 0, y: 0, width, height } }],
      width,
      height,
    );
  }
  renderViews(views, width, height) {
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
    const batches = views.map((view) => ({
      view,
      shapes: viewPrimitives(view),
    }));
    this.reserve(batches.reduce((n, b) => n + b.shapes.length, 0));
    while (this.slots.length < batches.length) {
      const uniform = this.device.createBuffer({
        size: 32,
        usage: GPUBufferUsage.UNIFORM | GPUBufferUsage.COPY_DST,
      });
      this.slots.push({ uniform, bindGroup: this.bind(uniform) });
    }
    let index = 0;
    batches.forEach(({ view, shapes }, i) => {
      for (const shape of shapes) {
        this.data.set([...shape.points, shape.type, 0, ...shape.color], index);
        index += 12;
      }
      const clip = view.clip;
      this.device.queue.writeBuffer(
        this.slots[i].uniform,
        0,
        new Float32Array([
          width,
          height,
          clip?.x || 0,
          clip?.y || 0,
          clip?.rx || 0,
          clip?.ry || 0,
          0,
          0,
        ]),
      );
    });
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
    pass.setPipeline(this.pipeline);
    let first = 0;
    batches.forEach(({ shapes }, i) => {
      pass.setBindGroup(0, this.slots[i].bindGroup);
      if (shapes.length) pass.draw(6, shapes.length, 0, first);
      first += shapes.length;
    });
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
    this.renderViews(
      [{ world, camera, rect: { x: 0, y: 0, width, height } }],
      width,
      height,
    );
  }
  renderViews(views, width, height) {
    const ratio = Math.min(devicePixelRatio || 1, 2),
      ctx = this.context;
    if (this.canvas.width !== Math.round(width * ratio))
      this.canvas.width = Math.max(1, Math.round(width * ratio));
    if (this.canvas.height !== Math.round(height * ratio))
      this.canvas.height = Math.max(1, Math.round(height * ratio));
    ctx.setTransform(ratio, 0, 0, ratio, 0, 0);
    ctx.clearRect(0, 0, width, height);
    for (const view of views) {
      ctx.save();
      if (view.clip) {
        const c = view.clip;
        ctx.beginPath();
        ctx.ellipse(c.x, c.y, c.rx, c.ry, 0, 0, Math.PI * 2);
        ctx.clip();
      }
      for (const shape of viewPrimitives(view)) {
        const [r, g, b, alpha] = shape.color;
        ctx.fillStyle = `rgba(${Math.round(r * 255)},${Math.round(g * 255)},${Math.round(b * 255)},${alpha})`;
        ctx.beginPath();
        const p = shape.points;
        if (shape.type === 0)
          ctx.ellipse(p[0], p[1], p[2], p[3], 0, 0, Math.PI * 2);
        else if (shape.type === 2) {
          ctx.moveTo(p[0], p[1]);
          ctx.lineTo(p[2], p[3]);
          ctx.strokeStyle = ctx.fillStyle;
          ctx.lineWidth = 1;
          ctx.stroke();
          continue;
        } else {
          ctx.moveTo(p[0], p[1]);
          ctx.lineTo(p[2], p[3]);
          ctx.lineTo(p[4], p[5]);
          ctx.closePath();
        }
        ctx.fill();
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
