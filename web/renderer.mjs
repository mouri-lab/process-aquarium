import {fishPrimitives, projectedFish, visibleFish} from './geometry.mjs';
const shader = /* wgsl */ `
struct Globals { viewport: vec2f, camera: vec2f, zoom: f32, time: f32, padding: vec2f }
struct Primitive { a: vec4f, b: vec4f, color: vec4f }
@group(0) @binding(0) var<uniform> globals: Globals;
@group(0) @binding(1) var<storage,read> instances: array<Primitive>;
struct Output { @builtin(position) position: vec4f, @location(0) uv: vec2f,
  @location(1) color: vec4f, @location(2) @interpolate(flat) kind: f32 }
@vertex fn vertexMain(@builtin(vertex_index) vertex:u32,@builtin(instance_index) index:u32)->Output {
  let p=instances[index];
  let corners=array<vec2f,6>(vec2f(-1,-1),vec2f(1,-1),vec2f(1,1),vec2f(-1,-1),vec2f(1,1),vec2f(-1,1));
  var pixel=p.a.xy+corners[vertex]*p.a.zw;
  if(p.b.z>0.5){let indices=array<u32,6>(0,1,2,2,2,2);let points=array<vec2f,3>(p.a.xy,p.a.zw,p.b.xy);pixel=points[indices[vertex]];}
  var output:Output;
  output.position=vec4f(pixel/globals.viewport*vec2f(2,-2)+vec2f(-1,1),0,1);
  output.uv=corners[vertex];output.color=p.color;output.kind=p.b.z;
  return output;
}
@fragment fn fragmentMain(input:Output)->@location(0) vec4f {
  var alpha=input.color.a;
  if(input.kind<.5){let d=length(input.uv);let edge=max(fwidth(d),.001);alpha*=1-smoothstep(1-edge,1+edge,d);}
  return vec4f(input.color.rgb,alpha);
}
`;
function primitives(world,camera,width,height){
  const result=[];
  for(const fish of world.fish.values())if(visibleFish(fish,camera,width,height))
    result.push(...fishPrimitives(projectedFish(fish,camera,width,height),camera.zoom,world.highlightSchools,world.quality));
  return result;
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
    const shapes=primitives(world,camera,width,height);
    this.reserve(shapes.length);
    let index=0;
    for(const shape of shapes){this.data.set([...shape.points,shape.type,0,...shape.color],index);index+=12;}
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
    if (shapes.length) {
      pass.setPipeline(this.pipeline);
      pass.setBindGroup(0, this.bindGroup);
      pass.draw(6, shapes.length);
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
    for(const shape of primitives(world,camera,width,height)){
      const [r,g,b,alpha]=shape.color;
      ctx.fillStyle=`rgba(${Math.round(r*255)},${Math.round(g*255)},${Math.round(b*255)},${alpha})`;
      ctx.beginPath();
      const p=shape.points;
      if(shape.type===0)ctx.ellipse(p[0],p[1],p[2],p[3],0,0,Math.PI*2);
      else{ctx.moveTo(p[0],p[1]);ctx.lineTo(p[2],p[3]);ctx.lineTo(p[4],p[5]);ctx.closePath();}
      ctx.fill();
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
