import { test } from 'node:test';
import assert from 'node:assert/strict';
import { Multiverse, processRef, galaxyLayout, skyFor, Journey, transitionRect, pollTanks } from '../../web/multiverse.mjs';
const p = {pid:1,ppid:0,create_time:1,name:'fish',exe:'',cmdline:[],status:'running',cpu_percent:2,memory_percent:1,num_threads:1};
const envelope = (host, extra={}) => ({stale:false,snapshot:{schema_version:1,host_id:host,hostname:host,boot_id:'boot',session_id:'session',source:'psutil',collected_at:1,sequence:1,processes:[p],events:[],connections:[],...extra}});
const catalog = n => Array.from({length:n},(_,i)=>({host_id:`h${i}`,hostname:`Host ${i}`,stale:false}));
test('tank switches preserve fish, selection, filters and camera; qualified endpoints reject PID reuse',()=>{
 const m = new Multiverse();m.catalog(catalog(2));
 const a=m.select('h0');a.apply(envelope('h0'),10);
 const key=[...a.world.fish.keys()][0],fish=a.world.fish.get(key);
 a.world.selection=key;a.camera.x=42;a.world.setFilters({limit:10});
 const ref=processRef(a,p),b=m.select('h1');b.apply(envelope('h1'),20);
 assert.notEqual([...b.world.fish.keys()][0],key);
 assert.equal(m.resolve(ref).tank,a);
 m.select('h0');assert.equal(a.world.fish.get(key),fish);assert.equal(a.world.selection,key);assert.equal(a.camera.x,42);assert.equal(a.world.filters.limit,10);
 a.apply(envelope('h0',{sequence:2,processes:[{...p,create_time:2}]}),30);assert.equal(m.resolve(ref),null);
 assert.throws(()=>b.apply(envelope('h0'),40));
 b.camera.x=99;b.apply(envelope('h1',{boot_id:'new-boot',session_id:'new-session'}),50);assert.equal(b.camera.x,0);
});
test('catalog pages are bounded and disappeared hosts retain their last state',()=>{
 const m=new Multiverse();m.catalog(catalog(20));m.overview=true;
 assert.equal(m.visible.length,6);assert.equal(m.pages,4);m.page=3;assert.equal(m.visible.length,2);
 const active=m.active;active.apply(envelope('h0'),1);m.catalog(catalog(2).slice(1));
 assert.equal(active.freshness.mode,'offline');assert.equal(active.world.processes.size,1);
 assert.throws(()=>m.catalog([{host_id:'x',hostname:'x'},{host_id:'x',hostname:'x'}]));
 assert.deepEqual(skyFor('a'),skyFor('a'));assert.notDeepEqual(skyFor('a'),skyFor('b'));
});
test('visible polling isolates failures, limits concurrency and does not select late responses',async()=>{
 const m=new Multiverse();m.catalog(catalog(8));m.overview=true;
 let inflight=0,peak=0;
 await pollTanks(m.visible,async host=>{inflight++;peak=Math.max(peak,inflight);await new Promise(r=>setTimeout(r,2));inflight--;if(host==='h1')throw Error('offline');return envelope(host);},()=>true,()=>10);
 assert.equal(peak,3);assert.equal(m.tanks.size,8);assert.equal(m.active.host,'h0');
 assert.equal(m.ordered[1].freshness.mode,'offline');assert.equal(m.ordered[2].freshness.mode,'live');assert.equal(m.ordered[6].world.snapshot,null);
 await pollTanks([m.active],async()=>envelope('h0',{sequence:2}),()=>false,()=>20);
 assert.equal(m.active.world.snapshot.sequence,1);
});
test('journey reverses without a jump; reduced motion lands immediately; layout stays within the viewport',()=>{
 const j=new Journey();j.go(0,true);j.go(1);j.step(.4);const before=j.depth;assert.ok(before>0&&before<1);j.go(0);assert.equal(j.depth,before);j.step(2);assert.equal(j.depth,0);j.go(1,true);assert.equal(j.depth,1);
 for(const [w,h] of [[390,844],[1464,723]])for(const r of galaxyLayout(6,w,h)){assert.ok(r.x>=0&&r.y>=0&&r.x+r.width<=w&&r.y+r.height<=h);}
 const r=galaxyLayout(3,1000,700)[1];assert.deepEqual(transitionRect(r,r,0,1000,700),r);
 const end=transitionRect(r,r,1,1000,700);assert.equal(end.x,0);assert.equal(end.y,0);assert.equal(end.width,1000);assert.equal(end.height,700);
});
