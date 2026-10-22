// Shape construction mirrors pygame Fish._draw_*; both renderers consume it.
import {appearance,satellites} from './fish.mjs';
export function fishPrimitives(f,zoom=1,highlight=false,quality='full') {
  const a=appearance(f,highlight), size=a.size*zoom, color=[...a.color,a.alpha], out=[];
  const ellipse=(x,y,rx,ry,c=color)=>out.push({type:0,points:[x,y,rx,ry,0,0],color:c});
  const triangle=(points,c=color)=>out.push({type:1,points:points.flat(),color:c});
  const {x,y}=f,cos=Math.cos(f.angle),sin=Math.sin(f.angle);
  if(size<2)return out;
  if(quality==='minimal'){ellipse(x,y,Math.max(2,Math.min(Math.trunc(size),24)),Math.max(2,Math.min(Math.trunc(size),24)));return out;}
  if(size>=3 && a.alpha>20/255){
    let length=size*1.8,width=size*.9;
    if(f.shape==='ray'){length*=1.2;width*=1.5;}
    if(f.shape==='whale'){length*=1.3;width*=1.2;}
    if(f.shape==='eel'){length*=2;width*=.4;}
    if(f.shape==='fish'){
      ellipse(x-length*.1,y,length*.4,width*.5);
      ellipse(x+length*.35,y,length*.15,width*.3);
      const tx=x-cos*length*.4,ty=y-sin*length*.4,ts=width*.5;
      for(const sign of [1,-1])triangle([[tx,ty],[tx-cos*ts*1.2+sign*sin*ts*.3*f.tail,ty-sin*ts*1.2-sign*cos*ts*.3*f.tail],[tx-cos*ts*.8,ty-sin*ts*.8]]);
      const dx=x-cos*length*.1,dy=y-sin*length*.1,ds=width*.3;
      triangle([[dx,dy],[dx+sin*ds*.8,dy-cos*ds*.8],[dx+sin*ds*.5,dy-cos*ds*.5]]);
      if(width>8){const eye=Math.max(2,width*.15),ex=x+cos*length*.3+sin*width*.2,ey=y+sin*length*.3-cos*width*.2;
        ellipse(ex,ey,eye,eye,[1,1,1,a.alpha]);const pupil=Math.max(1,eye*.6);ellipse(ex,ey,pupil,pupil,[0,0,0,a.alpha]);}
    }else{
      ellipse(x,y,length/2,width/2);
      const tail={shark:.7,tropical:.6,ray:.8,dolphin:.7,whale:.9,eel:.5}[f.shape];
      const angle=f.angle+(f.shape==='ray'?Math.PI:Math.PI/2)+f.tail;
      const ratio={shark:.8,tropical:.7,ray:.9,dolphin:.8,whale:.8,eel:.7}[f.shape];
      triangle([[x,y],[x+Math.cos(angle)*length*tail,y+Math.sin(angle)*length*tail],[x+Math.cos(angle)*length*tail*ratio,y+Math.sin(angle)*length*tail*ratio]]);
      if(['tropical','dolphin'].includes(f.shape)){const fin=length*(f.shape==='tropical'?.4:.5),fa=f.angle-Math.PI/2+f.tail;triangle([[x,y],[x+Math.cos(fa)*fin,y+Math.sin(fa)*fin],[x+Math.cos(fa)*fin*.8,y+Math.sin(fa)*fin*.8]]);}
    }
  }
  if(quality==='full'&&f.p.num_threads>1&&size>5){
    const satSize=Math.max(1.5,Math.min(size*.20*(1+f.p.num_threads/20),size*.7));
    const satColor=[...a.color,Math.floor(a.alpha*255/2)/255];
    if(satSize>=2)for(const [sx,sy] of satellites(f,size)){
      ellipse(sx-satSize*.25,sy,satSize*.75,satSize*.5,satColor);
      triangle([[sx-satSize,sy],[sx-satSize*1.5,sy-satSize/3],[sx-satSize*1.5,sy+satSize/3]],satColor);
    }
  }
  return out;
}
export function projectedFish(f,camera,width,height) {
  return {...f,x:(f.x-camera.x)*camera.zoom+width/2,y:(f.y-camera.y)*camera.zoom+height/2};
}
export function visibleFish(f,camera,width,height) {
  const x=(f.x-camera.x)*camera.zoom+width/2,y=(f.y-camera.y)*camera.zoom+height/2;
  const margin=appearance(f).size*camera.zoom*7+30;
  return x>-margin&&x<width+margin&&y>-margin&&y<height+margin;
}
