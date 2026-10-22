"""Differential checks against the actual pygame Fish, not copied expectations."""
import json
import os
from pathlib import Path
import shutil
import subprocess
from unittest.mock import patch

import pytest

pytest.importorskip("pygame")
from src.visuals.fish import Fish

ROOT = Path(__file__).resolve().parents[1]


def browser(expression, data):
    if not shutil.which("node"):
        pytest.skip("Node is required for native/browser differential tests")
    result = subprocess.run(
        ["node", "--input-type=module", "-e", """
import * as fish from './web/fish.mjs';
let input='';for await(const chunk of process.stdin)input+=chunk;
const data=JSON.parse(input);
""" + expression], input=json.dumps(data), text=True, capture_output=True,
        cwd=ROOT, check=True, env={**os.environ, "PYGAME_HIDE_SUPPORT_PROMPT": "1"},
    )
    return json.loads(result.stdout)


def test_metric_shape_color_effect_and_thread_parity():
    cases = []
    expected = []
    for name in ["chrome", "code", "systemd", "slack", "docker", "zsh", "python", "日本語🐟"]:
        for memory, cpu in [(0, 0), (.5, 25), (5, 80), (25, 100), (100, 6400)]:
            f = Fish(12, name, 25, -30)
            f.update_process_data(memory, cpu, 40, 1)
            f.age = 60
            f.pulsation_phase = .6
            f.is_spawning = True
            f.spawn_progress = .65
            f.school_members = [12, 13]
            f.set_fork_event()
            f.fork_glow_timer = 15
            f.set_exec_event()
            f.exec_timer = 15
            cases.append(dict(name=name, memory=memory, cpu=cpu))
            expected.append(dict(size=f.current_size, giant=f.is_memory_giant,
                shape=f.fish_shape, color=list(f.color), glow=f.glow_intensity,
                display_size=f.get_display_size(), display_color=list(f.get_display_color()),
                alpha=f.get_display_alpha(), satellites=f.get_thread_satellites()))
    actual = browser("""
console.log(JSON.stringify(data.map(c=>{
 const p={name:c.name,memory_percent:c.memory,cpu_percent:c.cpu,num_threads:40};
 const f=fish.makeFish('test',p,25,-30,3072);
 Object.assign(f,{age:60,pulse:.6,spawn:.65,school:[12,13],fork:15,exec:15});
 const a=fish.appearance(f);
 return {size:f.size,giant:f.giant,shape:f.shape,color:f.color.map(x=>Math.round(x*255)),glow:f.glow,
 display_size:a.size,display_color:a.color.map(x=>Math.round(x*255)),alpha:Math.round(a.alpha*255),satellites:fish.satellites(f)};
})));
""", cases)
    for left, right in zip(expected, actual):
        for key in left:
            if key == "satellites":
                for a, b in zip(left[key], right[key]):
                    assert a == pytest.approx(b)
            elif isinstance(left[key], (float, int)):
                assert left[key] == pytest.approx(right[key])
            else:
                assert left[key] == right[key]


def test_boids_kinetic_energy_and_motion_match_native():
    group = [12, 13, 14]
    fishes = [Fish(pid, "python", x, y) for pid, x, y in [(12, 0, 0), (13, 20, 15), (14, -40, 30)]]
    for f in fishes:
        f.update_process_data(1, 30, 2, 0)
        f.school_members = group
        f.vx, f.vy = 1, -.5
        f.target_x, f.target_y = 200, -100
        f.behavior_timer = 2
        f.decision_interval = 40
        f.age = 2
    native_force = fishes[0].calculate_flocking_forces(fishes[1:])
    native_energy = fishes[0]._calculate_kinetic_energy_light(fishes[1:])
    with patch("random.uniform", side_effect=lambda a, b: (a+b)/2), patch("random.randint", return_value=300):
        fishes[0].update_position(1200, 800, fishes[1:])
    actual = browser("""
const school=[12,13,14];
const fs=[[12,0,0],[13,20,15],[14,-40,30]].map(([pid,x,y])=>{
const f=fish.makeFish('test',{pid,name:'python',memory_percent:1,cpu_percent:30,num_threads:2},x,y,4096);
Object.assign(f,{school,vx:1,vy:-.5,targetX:200,targetY:-100,behavior:2,decision:40,age:2,random:()=>.5});return f;});
const force=fish.flocking(fs[0],fs.slice(1)),energy=fish.kineticEnergy(fs[0],fs.slice(1));
fish.updateFish(fs[0],fs.slice(1));console.log(JSON.stringify({force,energy,motion:[fs[0].x,fs[0].y,fs[0].vx,fs[0].vy]}));
""", {})
    assert actual["force"] == pytest.approx(native_force)
    assert actual["energy"] == pytest.approx(native_energy)
    assert actual["motion"] == pytest.approx([fishes[0].x, fishes[0].y, fishes[0].vx, fishes[0].vy])


def test_all_seven_shape_primitives_match_pygame(monkeypatch):
    import pygame
    data, expected = [], []
    surface = pygame.Surface((1200, 800), pygame.SRCALPHA)
    calls = []

    def ellipse(_, color, rect):
        x, y, w, h = rect
        calls.append(dict(type=0, points=[x+w/2, y+h/2, w/2, h/2, 0, 0]))

    def polygon(_, color, points):
        calls.append(dict(type=1, points=[v for point in points for v in point]))

    def circle(_, color, center, radius):
        calls.append(dict(type=0, points=[*center, radius, radius, 0, 0]))

    monkeypatch.setattr(pygame.draw, "ellipse", ellipse)
    monkeypatch.setattr(pygame.draw, "polygon", polygon)
    monkeypatch.setattr(pygame.draw, "circle", circle)
    for shape in ["fish", "shark", "tropical", "ray", "dolphin", "whale", "eel"]:
        for angle in [0, .7, -2]:
            calls.clear()
            f = Fish(1, "test", 300, 400)
            f.angle, f.tail_swing = angle, .4
            length, width = 36, 18
            if shape == "ray":
                length, width = length*1.2, width*1.5
            elif shape == "whale":
                length, width = length*1.3, width*1.2
            elif shape == "eel":
                length, width = length*2, width*.4
            method = "generic_fish" if shape == "fish" else "tropical_fish" if shape == "tropical" else shape
            getattr(f, "_draw_"+method)(surface, (100, 150, 200), 255, length, width)
            expected.append(list(calls))
            data.append(dict(shape=shape, angle=angle))
    actual = browser("""
const {fishPrimitives}=await import('./web/geometry.mjs');
console.log(JSON.stringify(data.map(c=>{
const f=fish.makeFish('x',{name:'test',cpu_percent:0,memory_percent:0,num_threads:1},300,400,3072);
Object.assign(f,{shape:c.shape,angle:c.angle,tail:.4,size:20,spawn:1});
return fishPrimitives(f).map(({type,points})=>({type,points}));
})));
""", data)
    for native, web in zip(expected, actual):
        assert len(native) == len(web)
        for a, b in zip(native, web):
            assert a["type"] == b["type"]
            # pygame Rect/circle raster coordinates truncate to integer pixels.
            assert a["points"] == pytest.approx(b["points"], abs=1.1)
