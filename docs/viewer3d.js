/* Dependency-free, orthographic 3D viewer. Real 21-joint skeletons, never a fitted mesh. */
'use strict';
(() => {
  const colors = {gt:'#d98b21',hggt:'#148fa1',hawor:'#a47bd6'};
  const names = {gt:'GT',hggt:'HGGT',hawor:'HaWoR'};
  const finite = p => p && p.length === 3 && p.every(Number.isFinite);
  const node = (tag, cls, text) => {const n=document.createElement(tag);if(cls)n.className=cls;if(text!==undefined)n.textContent=text;return n;};
  function button(text, action) {const b=node('button','',text);b.type='button';b.addEventListener('click',action);return b;}
  function select(label, entries, value, action) {
    const wrap=node('label','v3-select',label), input=node('select');input.setAttribute('aria-label',label);
    for(const [v,t] of entries){const o=node('option','',t);o.value=v;input.append(o);}input.value=value;
    input.addEventListener('change',action);wrap.append(input);return {wrap,input};
  }
  function check(label, color, action) {
    const wrap=node('label','v3-check'),input=node('input');input.type='checkbox';input.checked=true;input.setAttribute('aria-label',label);
    const dot=node('i');dot.style.background=color;wrap.append(input,dot,document.createTextNode(label));input.addEventListener('change',action);return {wrap,input};
  }
  function attach(wrapper, sample, timeline) {
    const panel=node('section','viewer3d');panel.setAttribute('aria-label',`${sample.title || sample.id} 交互三维视图`);
    const header=node('div','v3-heading'),title=node('h3','','交互 3D · 同帧检查');
    const badge=node('span','v3-badge','可旋转 / 缩放 / 平移');header.append(title,badge);panel.append(header);
    const intro=node('p','v3-intro','GT、HGGT 与 HaWoR 的真实 21 关节骨架，可独立显示或叠加。与下方视频时间轴同步；不生成或冒充 GT 网格。');panel.append(intro);
    const load=button('载入此序列 3D',loadData),loadStatus=node('span','v3-load-status','按需加载，不运行推理');
    const loader=node('div','v3-loader');loader.append(load,loadStatus);panel.append(loader);
    const content=node('div','v3-content');content.hidden=true;panel.append(content);
    const choices=node('div','v3-choices');content.append(choices);
    let data=null,frame=0,yaw=-0.28,pitch=-0.18,center=[0,0,0],span=0.35,zoom=1,pan=[0,0],scheduled=false,loading=false;
    const methodInputs={};
    for(const key of ['gt','hggt','hawor']) {const c=check(names[key],colors[key],()=>{fit();redraw();});methodInputs[key]=c.input;choices.append(c.wrap);}
    const variant=select('HGGT 几何',[['hggt_adapted','标定平移适配'],['hggt_native','原生输出']], 'hggt_adapted',()=>{fit();redraw();});choices.append(variant.wrap);
    const sides=select('手侧',[['both','左右手'],['left','左手'],['right','右手']], 'both',()=>{fit();redraw();});choices.append(sides.wrap);
    const alignment=select('坐标显示',[['camera','相机空间 · 米'],['wrist','腕部平移对齐 · 米']], 'camera',()=>{fit();redraw();});choices.append(alignment.wrap);
    const canvasWrap=node('div','v3-canvas-wrap'),canvas=node('canvas','v3-canvas');canvas.tabIndex=0;canvas.setAttribute('role','img');canvas.setAttribute('aria-label','三维手部视图。拖动旋转，Shift 拖动平移，滚轮缩放。W A S D 旋转，加减缩放，R 重置。');
    canvasWrap.append(canvas);content.append(canvasWrap);const ctx=canvas.getContext('2d');
    const tools=node('div','v3-tools');
    function preset(y,p){yaw=y;pitch=p;redraw();}
    tools.append(button('正视',()=>preset(0,0)),button('侧视',()=>preset(Math.PI/2,0)),button('俯视',()=>preset(0,Math.PI/2)),button('斜视',()=>preset(-0.55,-0.35)),button('＋',()=>{zoom=Math.min(30,zoom*1.25);redraw();}),button('－',()=>{zoom=Math.max(.05,zoom/1.25);redraw();}),button('重置视角',()=>{yaw=-.28;pitch=-.18;fit();redraw();}));
    tools.children[4].setAttribute('aria-label','放大三维视图');tools.children[5].setAttribute('aria-label','缩小三维视图');
    const help=node('span','v3-help','拖动旋转 · Shift / 右键拖动平移 · 滚轮缩放 · 触屏双指缩放与平移');tools.append(help);content.append(tools);
    const state=node('p','v3-state');state.setAttribute('aria-live','off');content.append(state);
    const handStatus=node('div','v3-hand-status');content.append(handStatus);
    const note=node('p','v3-note');content.append(note);
    const details=node('details','v3-details');details.append(node('summary','','数据定义、坐标与限制'));
    const explanation=node('div');details.append(explanation);content.append(details);
    const insertion=wrapper.querySelector('.player-toolbar');wrapper.insertBefore(panel,insertion);
    function selected(){return ['gt','hggt','hawor'].filter(k=>methodInputs[k].checked && !methodInputs[k].disabled).map(k=>({key:k,id:k==='hggt'?variant.input.value:k,method:data?.methods[k==='hggt'?variant.input.value:k]})).filter(x=>x.method);}
    function visibleSide(h){return sides.input.value==='both'||sides.input.value===['left','right'][h];}
    function transform(p,joints,h){if(!finite(p))return null;if(alignment.input.value==='wrist'){const root=joints?.[0];if(!finite(root))return null;const offset=sides.input.value==='both'?(h===0?-.12:.12):0;return [p[0]-root[0]+offset,p[1]-root[1],p[2]-root[2]];}return p;}
    function valid(m,h){return !!m?.valid?.[frame]?.[h];}
    function fit(){
      if(!data)return;const ps=[];
      // Fit the selected geometry over the whole clip so motion stays in view.
      for(const {method:m} of selected())for(let f=0;f<data.frame_ids.length;f++)for(let h=0;h<2;h++)if(visibleSide(h)&&m.valid?.[f]?.[h])for(const p of m.joints[f][h]){const q=transform(p,m.joints[f][h],h);if(q)ps.push(q);}
      if(!ps.length)return;
      const lo=[0,1,2].map(a=>Math.min(...ps.map(p=>p[a]))),hi=[0,1,2].map(a=>Math.max(...ps.map(p=>p[a])));
      center=lo.map((v,a)=>(v+hi[a])/2);span=Math.max(.12,Math.hypot(...lo.map((v,a)=>hi[a]-v))*1.25);zoom=1;pan=[0,0];
    }
    async function loadData(){
      if(loading||data)return;loading=true;load.disabled=true;loadStatus.textContent='正在读取真实逐帧关节…';
      try {
        const response=await fetch(`interactive3d/${encodeURIComponent(sample.id)}.json`);if(!response.ok)throw new Error(`HTTP ${response.status}`);
        const d=await response.json();
        if(d.frame_ids.length!==sample.frame_count||d.side_order?.join(',')!=='left,right'||d.unit!=='m')throw new Error('数据帧数、手侧或单位不匹配');
        if(sample.source_frame_ids && d.frame_ids.some((v,i)=>String(v)!==String(sample.source_frame_ids[i])))throw new Error('视频与三维源帧映射不匹配');
        data=d;for(const k of ['gt','hggt','hawor']){const id=k==='hggt'?variant.input.value:k;if(!data.methods[id] || data.methods[id].available===false){methodInputs[k].disabled=true;methodInputs[k].checked=false;}}
        content.hidden=false;loader.hidden=true;
        explanation.append(node('p','', '统一使用原 RGB 相机坐标：+X 向右，+Y 向下，+Z 向前，单位米。页面为正交观察视图，拖动仅改变观察角度，不修改源几何；网格仅作观察辅助，不代表真实地面。初始视角适应整个片段，相机运动不等于世界轨迹。'));
        explanation.append(node('p','', 'GT 仅展示已验证的 21 个标注关节，不生成 GT 网格。HGGT 的「原生输出」与「标定平移适配」共享形状、姿态和尺度，后者仅使用模型自己的投影求一个平移，不读取 GT 对齐。HaWoR 是原生相机空间输出。'));
        explanation.append(node('p','', '腕部平移对齐：每个方法分别减去自己的腕部。双手分置左/右展示槽，仅比较关节形状、方向与尺度；不保留手间位置，也不用于绝对位置判断。没有 Procrustes、旋转或尺度拟合。'));
        explanation.append(node('p','', '此交互视图仅显示 21 关节骨架，不新增 MANO 顶点、拓扑或模型资产。骨架使用评价中统一的指尖定义。无效手、无效关节不显示、不填零、不插值；HaWoR 漏检补全单独标注。视频按导出帧率回放，三维按相同帧索引对应，另显示采集时间。'));
        const links=node('p');const a=node('a','','数据来源与许可');a.href='interactive3d/README.md';links.append(a);explanation.append(links);
        fit();redraw();
      }catch(e){loadStatus.textContent=`3D 加载失败：${e.message}。可重试；原视频仍可使用。`;load.disabled=false;}finally{loading=false;}
    }
    function rotate(p){const x=p[0],y=p[1],z=p[2],cx=Math.cos(yaw),sx=Math.sin(yaw),cy=Math.cos(pitch),sy=Math.sin(pitch),xx=cx*x+sx*z,zz=-sx*x+cx*z;return [xx,cy*y-sy*zz,sy*y+cy*zz];}
    function redraw(){if(scheduled||!data)return;scheduled=true;requestAnimationFrame(()=>{scheduled=false;draw();});}
    function draw(){
      if(!data||!ctx||!panel.isConnected||panel.closest('[hidden]'))return;
      const w=canvasWrap.clientWidth,h=canvasWrap.clientHeight;if(!w||!h)return;
      const dpr=Math.min(window.devicePixelRatio||1,2);if(canvas.width!==Math.round(w*dpr)||canvas.height!==Math.round(h*dpr)){canvas.width=Math.round(w*dpr);canvas.height=Math.round(h*dpr);}ctx.setTransform(dpr,0,0,dpr,0,0);ctx.clearRect(0,0,w,h);
      ctx.fillStyle='#141d25';ctx.fillRect(0,0,w,h);const scale=Math.min(w,h)*.80/span*zoom;
      const project=p=>{const q=rotate(p.map((v,a)=>v-center[a]));return [w/2+pan[0]+q[0]*scale,h/2+pan[1]+q[1]*scale,q[2]];};
      // Neutral reference grid centered on the view, not an estimated world floor.
      const step=span>.7?.1:.05,size=Math.max(step*2,Math.ceil(span/step)*step/2);ctx.strokeStyle='#283640';ctx.lineWidth=1;
      for(let x=-size;x<=size+.0001;x+=step){for(const pair of [[[center[0]+x,center[1]+size/3,center[2]-size],[center[0]+x,center[1]+size/3,center[2]+size]],[[center[0]-size,center[1]+size/3,center[2]+x],[center[0]+size,center[1]+size/3,center[2]+x]]]){const a=project(pair[0]),b=project(pair[1]);ctx.beginPath();ctx.moveTo(a[0],a[1]);ctx.lineTo(b[0],b[1]);ctx.stroke();}}
      const primitives=[],labels=[],status=[];let shown=0;
      for(const {key,id,method:m} of selected()){
        for(let hand=0;hand<2;hand++){
          if(!visibleSide(hand))continue;const side=['左','右'][hand],j=m.joints?.[frame]?.[hand];
          if(!valid(m,hand)){status.push(`${names[key]} ${side}：无有效数据`);continue;}
          const infilled=!!m.infilled?.[frame]?.[hand];status.push(`${names[key]} ${side}：${infilled?'漏检时序补全':'有效'}`);shown++;
          {
            const q=j.map((p,k)=>m.joint_valid?.[frame]?.[hand]?.[k]===false?null:transform(p,j,hand)).map(p=>p?project(p):null);
            for(const [a,b] of data.joint_edges)if(q[a]&&q[b])primitives.push({type:'line',a:q[a],b:q[b],z:(q[a][2]+q[b][2])/2,color:colors[key],dash:hand===0||infilled});
            for(const p of q)if(p)primitives.push({type:'point',q:p,z:p[2]-.0001,color:colors[key],r:key==='gt'?3.3:2.7,alpha:1});
          }
          const root=transform(j?.[0],j,hand);if(root)labels.push({q:project(root),label:`${names[key]} ${side}`,color:colors[key]});
        }
      }
      primitives.sort((a,b)=>b.z-a.z);
      for(const p of primitives){ctx.globalAlpha=p.alpha??1;if(p.type==='line'){ctx.strokeStyle=p.color;ctx.lineWidth=2.2;ctx.setLineDash(p.dash?[5,3]:[]);ctx.beginPath();ctx.moveTo(p.a[0],p.a[1]);ctx.lineTo(p.b[0],p.b[1]);ctx.stroke();ctx.setLineDash([]);}else{ctx.fillStyle=p.color;ctx.beginPath();ctx.arc(p.q[0],p.q[1],p.r,0,Math.PI*2);ctx.fill();}}
      ctx.globalAlpha=1;ctx.font='12px system-ui';for(const l of labels){ctx.fillStyle=l.color;ctx.fillText(l.label,l.q[0]+9,l.q[1]+(l.label.startsWith('GT')?-16:l.label.startsWith('HGGT')?0:16));}
      // Orientation triad is rotated exactly like the data.
      const origin=[w-65,h-65];for(const [p,label,color] of [[[1,0,0],'X','#ee8790'],[[0,1,0],'Y','#8ec995'],[[0,0,1],'Z','#8bb5ed']]){const q=rotate(p);ctx.strokeStyle=color;ctx.fillStyle=color;ctx.beginPath();ctx.moveTo(...origin);ctx.lineTo(origin[0]+q[0]*30,origin[1]+q[1]*30);ctx.stroke();ctx.fillText(label,origin[0]+q[0]*40,origin[1]+q[1]*40);}
      const length=[.001,.002,.005,.01,.02,.05,.1,.2,.5,1,2].reduce((best,x)=>Math.abs(x*scale-75)<Math.abs(best*scale-75)?x:best,.05);ctx.strokeStyle='#b5c5cb';ctx.fillStyle='#b5c5cb';ctx.beginPath();ctx.moveTo(20,h-30);ctx.lineTo(20+length*scale,h-30);ctx.stroke();ctx.fillText(`${Number((length*100).toPrecision(3))} cm`,20,h-39);
      ctx.fillStyle='#acbdc7';ctx.fillText('正交视图 · 米 · 左虚线 / 右实线',16,25);
      if(!shown){ctx.textAlign='center';ctx.fillStyle='#d5dce1';ctx.fillText(selected().length?'当前帧 / 手侧无有效数据':'请至少选择一种方法',w/2,h/2);ctx.textAlign='left';}
      const ts=data.timestamps_relative_s?.[frame] ?? (data.timestamps_s?.[frame]-data.timestamps_s?.[0]);
      state.textContent=`第 ${frame+1} / ${data.frame_ids.length} 帧 · 源帧 ${data.frame_ids[frame]} · 采集 +${Number(ts).toFixed(4)} s · ${alignment.input.value==='camera'?'原相机空间':'各手腕部平移对齐（非绝对位置）'}`;
      handStatus.replaceChildren(...status.map(s=>node('span',s.includes('补全')?'infilled':'',s)));
      note.textContent=(variant.input.value==='hggt_native'?'HGGT 原生输出：不使用标定平移适配。':'HGGT 标定平移适配：仅整体平移；无 GT 对齐。')+' GT 只有关节骨架，未生成 GT 网格。';
      canvas.dataset.frame=String(frame);canvas.dataset.renderedHands=String(shown);canvas.dataset.primitiveCount=String(primitives.length);canvas.dataset.yaw=yaw.toFixed(4);canvas.dataset.pitch=pitch.toFixed(4);canvas.dataset.zoom=zoom.toFixed(4);
    }
    const pointers=new Map();let gesture=null;
    canvas.addEventListener('contextmenu',e=>e.preventDefault());
    canvas.addEventListener('pointerdown',e=>{canvas.setPointerCapture(e.pointerId);pointers.set(e.pointerId,[e.clientX,e.clientY]);gesture=null;canvas.focus();});
    canvas.addEventListener('pointermove',e=>{
      if(!pointers.has(e.pointerId))return;const old=pointers.get(e.pointerId);pointers.set(e.pointerId,[e.clientX,e.clientY]);
      if(pointers.size>=2){const [a,b]=[...pointers.values()],g={distance:Math.hypot(a[0]-b[0],a[1]-b[1]),mid:[(a[0]+b[0])/2,(a[1]+b[1])/2]};if(gesture){zoom=Math.max(.05,Math.min(30,zoom*g.distance/Math.max(gesture.distance,1)));pan[0]+=g.mid[0]-gesture.mid[0];pan[1]+=g.mid[1]-gesture.mid[1];}gesture=g;}
      else if(e.shiftKey||e.buttons===2){pan[0]+=e.clientX-old[0];pan[1]+=e.clientY-old[1];}
      else{yaw+=(e.clientX-old[0])*.008;pitch=Math.max(-Math.PI/2,Math.min(Math.PI/2,pitch+(e.clientY-old[1])*.008));}redraw();
    });
    function release(e){pointers.delete(e.pointerId);gesture=null;}canvas.addEventListener('pointerup',release);canvas.addEventListener('pointercancel',release);canvas.addEventListener('lostpointercapture',release);
    canvas.addEventListener('wheel',e=>{e.preventDefault();zoom=Math.max(.05,Math.min(30,zoom*Math.exp(-e.deltaY*.001)));redraw();},{passive:false});
    canvas.addEventListener('keydown',e=>{let handled=true;switch(e.key.toLowerCase()){case 'a':yaw-=.12;break;case 'd':yaw+=.12;break;case 'w':pitch-=.12;break;case 's':pitch+=.12;break;case '+':case '=':zoom=Math.min(30,zoom*1.2);break;case '-':zoom=Math.max(.05,zoom/1.2);break;case 'r':yaw=-.28;pitch=-.18;fit();break;default:handled=false;}if(handled){e.preventDefault();e.stopPropagation();redraw();}});
    new ResizeObserver(redraw).observe(canvasWrap);
    wrapper.addEventListener('comparisonframe',e=>{frame=e.detail.frame;redraw();});
    // First sequence starts ready; remaining payloads are loaded only when requested.
    if(sample.id==='dexycb_box')loadData();
    return {panel,setFrame:n=>{frame=n;redraw();}};
  }
  window.HandComparison3D={attach};
})();
