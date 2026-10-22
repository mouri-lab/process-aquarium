import {test} from 'node:test';
import assert from 'node:assert/strict';
import {Camera,View,LIMITS,SORTS,SHORTCUTS} from '../../web/controls.mjs';
import {AquariumWorld} from '../../web/world.mjs';
import {makeFish,appearance,worldSize,updateFish} from '../../web/fish.mjs';

const p=(pid,name='worker',ppid=0)=>({pid,name,ppid,create_time:1,cpu_percent:10,memory_percent:1,num_threads:3,cmdline:[]});
const snap=(ps,extra={})=>({schema_version:1,sequence:1,host_id:'h',hostname:'h',boot_id:'b',session_id:'s',source:'psutil',collected_at:1,events:[],connections:[],processes:ps,...extra});
test('native shortcuts and all limit/sort presets are reachable',()=>{
  const w=new AquariumWorld(),v=new View(),c=new Camera();
  for(const key of ['d','i','t','q','f','F11','l','s','o','c','r'])assert.ok(SHORTCUTS[key]);
  for(const limit of LIMITS.slice(1).concat([0])){v.action('limit',w,c);assert.equal(w.filters.limit,limit);}
  for(const sort of SORTS.slice(1).concat(['cpu'])){v.action('sort',w,c);assert.equal(w.filters.sort,sort);}
  v.action('order',w,c);assert.equal(w.filters.order,'asc');
  v.action('schools',w,c);assert.equal(w.highlightSchools,true);
  for(const ui of [1,2,0]){v.action('ui',w,c);assert.equal(v.ui,ui);}
  for(const mode of [1,2,0]){v.action('camera',w,c);assert.equal(c.mode,mode);}
});
test('camera auto center/follow/manual use native smoothing independent of refresh rate',()=>{
  const f={x:100,y:-200},world={fish:new Map([['f',f]]),selected:()=>f};
  const a=new Camera(),b=new Camera();a.update(world,1/30);b.update(world,1/60);b.update(world,1/60);
  assert.ok(Math.abs(a.x-b.x)<1e-10);assert.equal(a.x,1.0000000000000009);
  a.follow('f');a.update(world,1/30);assert.ok(a.x>8);a.manual();const old=a.x;a.update(world,1/30);assert.equal(a.x,old);
  a.zoomAt(100,50,100);assert.equal(a.zoom,5);assert.ok(Math.abs((100/a.zoom+a.x)-(100+old))<1e-10);
  a.zoomAt(0,0,.0001);assert.equal(a.zoom,.1);a.reset();assert.equal(a.mode,0);assert.equal(a.zoom,1);
});
test('family and same-name groups remain distinct from the isolates school',()=>{
  const w=new AquariumWorld();w.apply(snap([p(10,'parent',2),p(11,'child',10),p(20,'same'),p(21,'same'),p(30,'alpha'),p(31,'beta')]));
  const by=w.byPid();assert.equal(by.get(10).school,by.get(11).school);
  assert.equal(by.get(20).school,by.get(21).school);assert.equal(by.get(30).isolatedSchool,true);
  const isolate=by.get(30);isolate.spawn=1;assert.equal(appearance(isolate,true).alpha,63/255);
  by.get(20).spawn=1;assert.equal(appearance(by.get(20),true).alpha,1);
});
test('IPC attracts fish, produces clickable conversations and bounds history',()=>{
  const w=new AquariumWorld();w.apply(snap([p(10),p(11)],{connections:[{pid_a:10,pid_b:11,kind:'pipe'}]}));
  const [a,b]=w.byPid().values();a.x=0;a.y=0;b.x=50;b.y=0;w.step(1/30);
  assert.ok(a.talk>0&&b.talk>0);assert.deepEqual(a.partners,[11]);assert.deepEqual(b.partners,[10]);
  w.apply(snap([p(10)],{sequence:2,collected_at:100}));assert.equal(w.history.size,0);
});
test('fixed timestep yields identical trajectories at 30 and 120 Hz',()=>{
  const a=new AquariumWorld(),b=new AquariumWorld();a.apply(snap([p(10),p(11)]));b.apply(snap([p(10),p(11)]));
  for(let i=0;i<60;i++)a.step(1/30);for(let i=0;i<240;i++)b.step(1/120);
  assert.deepEqual([...a.fish.values()].map(f=>[f.x,f.y,f.age,f.tail]),[...b.fish.values()].map(f=>[f.x,f.y,f.age,f.tail]));
});
test('quality can be explicitly selected and recovers with hysteresis',()=>{
  const v=new View(),w=new AquariumWorld();v.quality='minimal';v.adapt(60,1/30,w);assert.equal(w.quality,'minimal');
  v.quality='auto';for(let i=0;i<200;i++)v.adapt(10,1/30,w);assert.equal(w.quality,'minimal');
  for(let i=0;i<200;i++)v.adapt(60,1/30,w);assert.equal(w.quality,'full');
});
test('world bounds, orbit, death and multicore CPU stay bounded',()=>{
  assert.equal(worldSize(20,20),1200);assert.equal(worldSize(400,400),4272);assert.equal(worldSize(0,500),4872);
  const f=makeFish('x',{...p(1),cpu_percent:6400},0,0,1200);f.random=()=>.5;
  f.orbit={x:0,y:0,radius:80,speed:.05,timer:0,duration:3};
  for(let i=0;i<3;i++)updateFish(f,[]);assert.equal(f.orbit,null);assert.ok(Math.abs(f.vx)<=14);
  f.dying=true;for(let i=0;i<34;i++)updateFish(f,[]);assert.equal(f.death,1);assert.equal(appearance(f).alpha,0);
});
