"""Render the same frozen Fish states in pygame, WebGPU and Canvas.

Run with the gui extra installed:
  python tools/compare_native_web.py --output /tmp/aquarium-comparison --serve
Open http://127.0.0.1:8766 and compare the reference/renderers. No live OS data.
"""

import argparse
import json
import os
from pathlib import Path
import sys
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.request import Request, urlopen
from urllib.error import HTTPError

os.environ.setdefault("SDL_VIDEODRIVER", "dummy")
os.environ.setdefault("PYGAME_HIDE_SUPPORT_PROMPT", "1")
ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
import pygame
from src.visuals.fish import Fish

WIDTH, HEIGHT = 1280, 800


def scene():
    states = []
    names = ["chrome", "code", "systemd", "slack", "docker", "zsh", "python"]
    for i, name in enumerate(names):
        states.append(
            dict(
                name=name,
                x=100 + i * 180,
                y=145,
                memory=0.5,
                cpu=10,
                threads=1,
                label=name,
            )
        )
    for i, (effect, value) in enumerate(
        [("spawn", 0.3), ("fork", 45), ("exec", 15), ("death", 0.5)]
    ):
        states.append(
            dict(
                name="python",
                x=150 + i * 320,
                y=360,
                memory=1,
                cpu=10,
                threads=1,
                label=effect,
                **{effect: value},
            )
        )
    states.extend(
        [
            dict(
                name="python",
                x=160,
                y=635,
                memory=0.5,
                cpu=90,
                threads=1,
                label="CPU 90%",
            ),
            dict(
                name="python",
                x=450,
                y=635,
                memory=5,
                cpu=10,
                threads=1,
                label="memory 5%",
            ),
            dict(
                name="docker",
                x=850,
                y=635,
                memory=20,
                cpu=10,
                threads=1,
                label="memory 20%",
            ),
            dict(
                name="python",
                x=1140,
                y=635,
                memory=0.5,
                cpu=10,
                threads=15,
                label="15 threads",
            ),
        ]
    )
    return states


def render(output):
    pygame.init()
    screen = pygame.Surface((WIDTH, HEIGHT))
    for y in range(HEIGHT):
        pygame.draw.line(
            screen, (0, 0, int(20 + (1 - y / HEIGHT) * 30)), (0, y), (WIDTH, y)
        )
    font = pygame.font.Font(None, 23)
    states = scene()
    for i, s in enumerate(states):
        f = Fish(100 + i, s["name"], s["x"], s["y"])
        f.update_process_data(s["memory"], s["cpu"], s["threads"], 0)
        f.is_spawning = "spawn" in s
        f.spawn_progress = s.get("spawn", 1)
        f.is_dying = "death" in s
        f.death_progress = s.get("death", 0)
        f.age = 60
        f.pulsation_phase = 0.6
        f.angle = 0.5
        f.vx = f.vy = 0
        f.swim_cycle = 0.4
        f.swim_phase_offset = 0.7
        f.personality_factor = 1
        if "fork" in s:
            f.set_fork_event()
            f.fork_glow_timer = s["fork"]
        if "exec" in s:
            f.set_exec_event()
            f.exec_timer = s["exec"]
        # Freeze lightning RNG so the reference and browser use a repeatable
        # illustration; exact bolts are deliberately not a pixel parity claim.
        import random

        random.seed(100 + i)
        f.draw(screen, font)
        text = font.render(s["label"], True, (200, 216, 240))
        screen.blit(text, (s["x"] - text.get_width() / 2, s["y"] + 60))
    output.mkdir(parents=True, exist_ok=True)
    pygame.image.save(screen, str(output / "pygame.png"))
    (output / "scene.json").write_text(
        json.dumps(dict(width=WIDTH, height=HEIGHT, states=states))
    )
    pygame.quit()


HTML = """<!doctype html><html lang="ja"><meta charset="utf-8"><title>Native / WebGPU / Canvas parity</title>
<style>body{margin:0;background:#080c1c;color:#ddd;font:14px system-ui}header{padding:16px}button{margin-left:12px}section{display:flex;flex-direction:column;gap:16px}canvas,img{width:1280px;height:800px}#stage{position:relative;width:1280px;height:800px;background:linear-gradient(#000032,#000014)}canvas{position:absolute;inset:0}#under{z-index:0}#fish{z-index:1}#over{z-index:2}h2{margin:10px}</style>
<header>同じ状態で pygame / ブラウザを比較 · <span id="backend">initializing</span><button id="toggle">Canvas / WebGPU 切替</button></header>
<section><div><h2>pygame reference</h2><img src="/pygame.png" alt="pygame reference"></div><div><h2>Browser</h2><div id="stage"><canvas id="under"></canvas><canvas id="fish"></canvas><canvas id="over"></canvas></div></div></section>
<script type="module">
import {makeFish,appearance} from '/web/fish.mjs';
import {createRenderer,CanvasRenderer,freshCanvas} from '/web/renderer.mjs';
import {prepareCanvas,drawUnderlay} from '/web/effects.mjs';
const data=await(await fetch('/scene.json')).json();
const world={fish:new Map(),highlightSchools:false,quality:'full',time:2,snapshot:{connections:[]},byPid(){return new Map()}};
for(const [i,s] of data.states.entries()){
const f=makeFish('scene'+i,{pid:100+i,name:s.name,memory_percent:s.memory,cpu_percent:s.cpu,num_threads:s.threads},s.x,s.y,3072);
const cpu=1+Math.expm1(2*s.cpu/100)/Math.expm1(2)*4;
Object.assign(f,{spawn:s.spawn??1,dying:!!s.death,death:s.death??0,fork:s.fork??0,exec:s.exec??0,age:60,pulse:.6,angle:.5,tail:Math.sin(.4+.1*cpu+.7)*Math.min(.2*cpu,1)});
world.fish.set(i,f);}
let canvas=document.querySelector('#fish'),renderer=await createRenderer(canvas,()=>{}),forceCanvas=false;
const camera={x:data.width/2,y:data.height/2,zoom:1};
function paint(){document.querySelector('#backend').textContent=renderer.name;renderer.render(world,camera,data.width,data.height);
const under=prepareCanvas(document.querySelector('#under'),data.width,data.height);drawUnderlay(under,world,camera,data.width,data.height,{particles:0,debug:false,ipc:false,habitat:false});
const over=prepareCanvas(document.querySelector('#over'),data.width,data.height);over.fillStyle='#c8d8f0';over.font='16px sans-serif';over.textAlign='center';for(const s of data.states)over.fillText(s.label,s.x,s.y+75);}
paint();document.querySelector('#toggle').onclick=async()=>{forceCanvas=!forceCanvas;canvas=freshCanvas(renderer.canvas);renderer.destroy();renderer=await createRenderer(canvas,()=>{},{forceCanvas});paint();};
</script></html>"""


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, default=Path("/tmp/aquarium-comparison"))
    parser.add_argument("--serve", action="store_true")
    parser.add_argument("--port", type=int, default=8766)
    parser.add_argument(
        "--ui-server",
        default="http://127.0.0.1:8765",
        help="Local fixture aggregation server for /responsive",
    )
    args = parser.parse_args()
    render(args.output)
    print(f"Reference: {args.output / 'pygame.png'}", flush=True)
    if not args.serve:
        return

    class Handler(BaseHTTPRequestHandler):
        def do_GET(self):
            path = self.path.split("?")[0]
            if path == "/responsive":
                body = b"""<!doctype html><meta charset="utf-8"><title>390px aquarium QA</title>
<style>body{margin:0;background:#080c1c;color:#aaa;font:12px sans-serif}p{margin:12px}iframe{display:block;width:390px;height:844px;border:0;margin:12px}</style>
<p>390 x 844 CSS pixels / production app in a constrained viewport</p><iframe title="390px aquarium" src="/ui/"></iframe>"""
                content = "text/html; charset=utf-8"
            elif path.startswith("/ui/"):
                # A development-only frame provides a real narrow CSS viewport
                # without changing the user's browser window. Production's
                # frame-ancestors policy remains unchanged.
                from src.server import STATIC_FILES, WEB_ROOT

                asset = STATIC_FILES.get(path[3:])
                if asset:
                    name, content = asset
                    body = (WEB_ROOT / name).read_bytes()
                elif path.startswith("/ui/api/v1/"):
                    try:
                        with urlopen(
                            Request(
                                args.ui_server + self.path[3:],
                                headers={"Accept": "application/json"},
                            ),
                            timeout=5,
                        ) as response:
                            body = response.read(17 * 1024 * 1024)
                            content = "application/json"
                    except HTTPError as exc:
                        self.send_error(exc.code)
                        return
                else:
                    self.send_error(404)
                    return
            elif path == "/":
                body = HTML.encode()
                content = "text/html"
            elif path in ("/pygame.png", "/scene.json"):
                body = (args.output / path[1:]).read_bytes()
                content = "image/png" if path.endswith(".png") else "application/json"
            elif path.startswith("/web/") and path[5:] in {
                "fish.mjs",
                "geometry.mjs",
                "renderer.mjs",
                "effects.mjs",
            }:
                body = (ROOT / path[1:]).read_bytes()
                content = "text/javascript"
            else:
                self.send_error(404)
                return
            self.send_response(200)
            self.send_header("Content-Type", content)
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def log_message(self, *args):
            pass

    print(f"Comparison: http://127.0.0.1:{args.port}", flush=True)
    ThreadingHTTPServer(("127.0.0.1", args.port), Handler).serve_forever()


if __name__ == "__main__":
    main()
