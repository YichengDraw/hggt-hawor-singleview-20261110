/* Run with: node --test tests/test_hand_renderer.cjs. No browser/dependencies. */
'use strict';
const {test}=require('node:test');
const assert=require('node:assert/strict');
const fs=require('node:fs');
const path=require('node:path');
const H=require('../docs/hand-renderer.js');
const root=path.join(__dirname,'..');
const near=(a,b,eps=1e-10)=>assert.ok(Math.abs(a-b)<eps,`${a} != ${b}`);
const vecNear=(a,b,eps)=>a.forEach((v,i)=>near(v,b[i],eps));
const view={center:[0,0,0],rotation:[0,0,0,1],distance:1,pan:[0,0]};
function canvas(w=64,h=64,matching=false){const ctx={createImageData:(w,h)=>({data:new Uint8ClampedArray(w*h*4)}),putImageData(image){this.last=image;}};return {clientWidth:w,clientHeight:h,width:matching?w:0,height:matching?h:0,getContext:k=>k==='2d'?ctx:null,ctx};}
const triangle=(z,color,alpha=1)=>new Float32Array([[-.15,-.15,z],[.15,-.15,z],[0,.15,z]].flatMap(p=>[...p,0,0,1,...color,alpha]));
const join=(...arrays)=>new Float32Array(arrays.flatMap(a=>Array.from(a)));
function deepFreeze(o){if(o&&typeof o==='object'){Object.freeze(o);Object.values(o).forEach(deepFreeze);}return o;}

test('drag front surface follows right/left/up/down screen motion',()=>{
  for(const [dx,dy] of [[50,0],[-50,0],[0,50],[0,-50]]){
    const q=H.dragQuaternion(H.presets.front,[400,300],[400+dx,300+dy],800,600);
    const p=H.rotate([0,0,1],q);
    if(dx)assert.ok(p[0]*dx>0);if(dy)assert.ok(-p[1]*dy>0);
    near(Math.hypot(...q),1);near(Math.hypot(...p),1);
  }
});
test('drag inverse and 10000 repetitions preserve orientation and lengths',()=>{
  const original=H.presets.oblique.slice();let q=original.slice();
  for(let i=0;i<10000;i++){
    q=H.dragQuaternion(q,[322,144],[419,206],800,600);
    q=H.dragQuaternion(q,[419,206],[322,144],800,600);
  }
  vecNear(q,original,1e-10);near(Math.hypot(...q),1);
  near(Math.hypot(...H.rotate([.2,-.5,.8],q)),Math.hypot(.2,-.5,.8));
  vecNear(H.dragQuaternion(q,[400,300],[400,300],800,600),q);
});
test('presets, axis quaternion multiplication and coordinate conversion',()=>{
  for(const q of Object.values(H.presets))near(Math.hypot(...q),1);
  vecNear(H.rotate([0,0,1],H.axis([0,1,0],Math.PI/2)),[1,0,0]);
  vecNear(H.cv([1,2,3]),[1,-2,-3]);
});
test('all four sequences and methods produce finite geometry without source mutation',()=>{
  const samples=JSON.parse(fs.readFileSync(path.join(root,'docs/manifest.json'))).samples;
  assert.equal(samples.length,4);let generated=0;
  for(const sample of samples){
    const data=JSON.parse(fs.readFileSync(path.join(root,'docs/interactive3d',sample.id+'.json')));
    for(const [name,m] of Object.entries(data.methods)){
      const frames=new Set([0,Math.floor(data.frame_ids.length/2),data.frame_ids.length-1]);
      const infill=m.infilled?.findIndex(row=>row.some(Boolean));if(infill>=0)frames.add(infill);
      for(const f of frames){
        const hands=m.joints[f].flatMap((j,h)=>m.valid[f][h]?[{joints:j.map((p,i)=>m.joint_valid[f][h][i]?p:null),color:[.2,.7,.8]}]:[]);
        const before=JSON.stringify(hands);deepFreeze(hands);
        const withShell=H.geometry(hands,data.joint_edges,.14),bonesOnly=H.geometry(hands,data.joint_edges,0);
        for(const [part,array] of Object.entries(withShell)){
          assert.equal(array.length%30,0,`${sample.id}/${name}/${f}/${part}`);
          assert.ok(array.every(Number.isFinite),`${sample.id}/${name}/${f}/${part}: nonfinite`);
        }
        assert.deepEqual(withShell.bones,bonesOnly.bones);assert.equal(bonesOnly.shell.length,0);
        if(hands.length){assert.ok(withShell.bones.length);assert.ok(withShell.shell.length);generated++;}
        assert.equal(JSON.stringify(hands),before);
      }
    }
  }
  assert.ok(generated>=48);
});
test('null joints, absent hands and coincident joints stay finite',()=>{
  const edges=Array.from({length:20},(_,i)=>[i,i+1]);
  assert.equal(H.geometry([],edges,.14).bones.length,0);
  for(const joints of [Array(21).fill(null),Array.from({length:21},(_,i)=>i%3?null:[0,0,0]),Array.from({length:21},()=>[0,0,0])]){
    const g=H.geometry([{joints,color:[1,.5,0]}],edges,.14);
    assert.ok(g.bones.every(Number.isFinite));assert.ok(g.shell.every(Number.isFinite));
  }
});
test('software fallback initializes even when bitmap size already matches CSS size',()=>{
  for(const matching of [false,true]){const c=canvas(64,64,matching),r=H.createRenderer(c);assert.equal(r.kind,'software-3d');r.draw(view);assert.equal(c.ctx.last.data.length,64*64*4);}
});
test('projection uses camera signs, perspective and screen-space pan',()=>{
  const r=new H.SoftwareRenderer(canvas(800,600));
  vecNear(r.project([0,0,0],view),[400,300,0]);
  const p=r.project([.1,.1,.1],view);assert.ok(p[0]>400&&p[1]>300);near(p[2],-.1);
  for(const point of [[.1,.2,-.3],[.2,-.1,.4]]){
    const base=r.project(point,view),shift=r.project(point,{...view,pan:[31,-17]});
    vecNear(shift,[base[0]+31,base[1]-17,base[2]]);
  }
});
test('software depth-buffer occludes farther bones independently of draw order',()=>{
  const far=triangle(0,[1,0,0]),close=triangle(.2,[0,1,0]);
  const outputs=[];
  for(const bones of [join(far,close),join(close,far)]){const c=canvas(),r=new H.SoftwareRenderer(c);r.geometry={bones,shell:new Float32Array()};r.draw(view);outputs.push(c.ctx.last.data.slice());const i=(32*64+32)*4;assert.ok(outputs.at(-1)[i+1]>outputs.at(-1)[i]);}
  assert.deepEqual(outputs[0],outputs[1]);
});
test('software transparent triangles sort back-to-front and obey opaque depth',()=>{
  const far=triangle(-.2,[1,0,0],.14),close=triangle(.2,[0,0,1],.14),bone=triangle(0,[0,1,0]);
  const render=shell=>{const c=canvas(),r=new H.SoftwareRenderer(c);r.geometry={bones:bone,shell};r.draw(view);return c.ctx.last.data;};
  assert.deepEqual(render(join(far,close)),render(join(close,far)));
  // Far shell is fully hidden by the larger, nearer opaque triangle.
  assert.deepEqual(render(far),render(new Float32Array()));
  assert.notDeepEqual(render(close),render(new Float32Array()));
});

test('WebGL shader depth, screen-space pan and transparent submission agree with software',()=>{
  const sources=[],uploads=[],uniforms={},events=[];
  const methods={
    createShader:type=>({type}),shaderSource:(s,source)=>sources.push(source),getShaderParameter:()=>true,
    createProgram:()=>({}),getProgramParameter:()=>true,createBuffer:()=>({}),getUniformLocation:(_,n)=>n,
    getAttribLocation:(_,n)=>['aPosition','aNormal','aColor'].indexOf(n),
    uniform1f:(n,v)=>uniforms[n]=v,uniform2fv:(n,v)=>uniforms[n]=v,uniform3fv:(n,v)=>uniforms[n]=v,uniform4fv:(n,v)=>uniforms[n]=v,
    bufferData:(_,data)=>uploads.push(data.slice()),depthMask:b=>events.push(['depthMask',b]),
    blendFunc:(a,b)=>events.push(['blendFunc',a,b]),drawArrays:(_,__,n)=>events.push(['draw',n]),
  };
  const constants=new Set(['VERTEX_SHADER','FRAGMENT_SHADER','COMPILE_STATUS','LINK_STATUS','ARRAY_BUFFER','DYNAMIC_DRAW','TRIANGLES','FLOAT','DEPTH_TEST','LEQUAL','CULL_FACE','BLEND','SRC_ALPHA','ONE_MINUS_SRC_ALPHA','COLOR_BUFFER_BIT','DEPTH_BUFFER_BIT']);
  const gl=new Proxy(methods,{get:(o,k)=>k in o?o[k]:constants.has(k)?k:()=>{}});
  const c={clientWidth:800,clientHeight:600,width:0,height:0,getContext:()=>gl};
  const r=new H.Renderer(c),v={...view,pan:[31,-17]};
  r.geometry={bones:triangle(0,[0,1,0]),shell:join(triangle(.2,[0,0,1],.14),triangle(-.2,[1,0,0],.14))};
  const old=global.window;global.window={devicePixelRatio:1};try{r.draw(v);}finally{if(old===undefined)delete global.window;else global.window=old;}
  const shader=sources.find(s=>s.includes('gl_Position'));
  assert.match(shader,/gl_Position\.xy\s*\+=\s*uPan\s*\*\s*depth/,'pan must be applied in clip coordinates, not as world translation');
  vecNear(uniforms.uPan,[2*31/800,2*17/600]);
  assert.match(shader,/\(uFar\+uNear\)\/\(uFar-uNear\)\*depth-2\.0\*uFar\*uNear\/\(uFar-uNear\)/);
  const ndc=depth=>((uniforms.uFar+uniforms.uNear)/(uniforms.uFar-uniforms.uNear)*depth-2*uniforms.uFar*uniforms.uNear/(uniforms.uFar-uniforms.uNear))/depth;
  near(ndc(uniforms.uNear),-1);near(ndc(uniforms.uFar),1);
  assert.equal(uploads.length,2);assert.ok(uploads[1][2]<uploads[1][32],'transparent upload should begin with far triangle');
  assert.deepEqual(events.filter(e=>e[0]==='depthMask'),[['depthMask',true],['depthMask',false],['depthMask',true]]);
  assert.ok(events.some(e=>e[0]==='blendFunc'&&e[1]==='SRC_ALPHA'&&e[2]==='ONE_MINUS_SRC_ALPHA'));
});

test('shader failure on a WebGL-bound canvas preserves a useful original error',()=>{
  const gl={createShader:()=>({}),shaderSource(){},compileShader(){},getShaderParameter:()=>false,getShaderInfoLog:()=> 'shader compile diagnostic',createProgram:()=>({})};
  const c={getContext:kind=>kind==='webgl'?gl:null};
  assert.throws(()=>H.createRenderer(c),/shader compile diagnostic/);
});

// Camera-aligned startup must not silently return to the oblique preset.
test('viewer defaults and resets to camera-aligned direction', () => {
  const viewer = fs.readFileSync(path.join(__dirname, '../docs/viewer3d.js'), 'utf8');
  assert.match(viewer, /rotation=H\.presets\.front\.slice\(\),center=/);
  assert.match(viewer, /function reset\(\)\{rotation=H\.presets\.front\.slice\(\);viewName='相机视角'/);
  const right=H.rotate(H.cv([1,0,2]),H.presets.front);
  const down=H.rotate(H.cv([0,1,2]),H.presets.front);
  assert.ok(right[0]>0);
  assert.ok(-down[1]>0);
});

test('camera frustum uses current calibrated K, origin and +Z without mutating metadata',()=>{
  const meta={K:[[600,0,310],[0,620,250],[0,0,1]],image_size:[640,480]},before=JSON.stringify(meta);deepFreeze(meta);
  const cam=H.cameraModel(meta);vecNear(cam.origin,[0,0,0]);vecNear(cam.forward,[0,0,1]);
  const pixels=[[0,0],[640,0],[640,480],[0,480]];
  cam.corners.forEach((p,i)=>{near(p[2],.4);vecNear([600*p[0]/p[2]+310,620*p[1]/p[2]+250],pixels[i]);});
  assert.ok(cam.corners[0][0]<0&&cam.corners[0][1]<0);assert.equal(JSON.stringify(meta),before);
  assert.equal(H.cameraModel(null),null);assert.equal(H.cameraModel({K:[[0,0,0],[0,1,0],[0,0,1]],image_size:[640,480]}),null);
  const g=H.cameraGeometry(cam);assert.ok(g.length>0&&g.every(Number.isFinite));assert.equal(g.length%30,0);
  const r=new H.SoftwareRenderer(canvas(240,168));const v=H.fitScene(cam.points,H.presets.oblique,240,168);r.geometry=H.combineGeometry({bones:new Float32Array(),shell:new Float32Array()},cam);r.draw(v);assert.ok(r.depth.some(Number.isFinite));
  for(const p of cam.points){const q=r.project(p,v);assert.ok(q[0]>0&&q[0]<240&&q[1]>0&&q[1]<168&&v.distance-q[2]>0);}
});
test('camera guide toggle keeps hand geometry unchanged and overview is lightweight',()=>{
  const cam=H.cameraModel({K:[[330,0,384],[0,330,384],[0,0,1]],image_size:[768,768]});
  const base={bones:triangle(0,[1,0,0]),shell:triangle(-.1,[1,0,0],.14)};
  assert.equal(H.combineGeometry(base,null),base);const combined=H.combineGeometry(base,cam);assert.deepEqual(combined.bones.slice(0,base.bones.length),base.bones);assert.equal(combined.shell,base.shell);
  const overview=H.overviewGeometry([{joints:[[0,0,.3],[.1,0,.4]],color:[1,0,0]}],[[0,1]],cam);assert.equal(overview.shell.length,0);assert.ok(overview.bones.every(Number.isFinite));
});

test('published per-frame camera metadata matches all four joint sequences',()=>{
  const metadata=JSON.parse(fs.readFileSync(path.join(root,'docs/interactive3d/cameras.json')));
  assert.equal(Object.keys(metadata.cameras).length,4);
  for(const [id,c] of Object.entries(metadata.cameras)){
    const d=JSON.parse(fs.readFileSync(path.join(root,'docs/interactive3d',id+'.json')));assert.deepEqual(c.frame_ids,d.frame_ids);
    const Ks=c.K_frames||c.frame_ids.map(()=>c.K);assert.equal(Ks.length,d.frame_ids.length);
    const unique=new Set(Ks.map(JSON.stringify)).size;assert.equal(unique,id==='aria_1976'?3:id==='aria_3209'?4:1);
    for(const K of Ks){const cam=H.cameraModel({...c,K});assert.ok(cam);for(const p of cam.corners){const u=K[0][0]*p[0]/p[2]+K[0][2],v=K[1][1]*p[1]/p[2]+K[1][2];assert.ok(Math.min(Math.abs(u),Math.abs(u-c.image_size[0]))<1e-9);assert.ok(Math.min(Math.abs(v),Math.abs(v-c.image_size[1]))<1e-9);}}
  }
});
