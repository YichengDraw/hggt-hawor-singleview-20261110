#!/usr/bin/env python3
"""Replay released HaWoR camera mode with shared detector tracks and calibrated K.
Only input calibration and artifact-only rendering are adapted. Temporal network,
track chunking, left reflection, infiller and MANO decoding are upstream functions.
"""
import os,sys,json,time,inspect,shutil,traceback
from pathlib import Path
from types import SimpleNamespace
import numpy as np
ROOT=Path('/nvme-ssd2/zhaoyicheng/hggt-reproduction-20261110')
SRC=Path('/nvme-ssd2/wlq/do-as-i-do-official-20260930/source/reconstruction/modules/HaWoR')
sys.path.insert(0,str(SRC));os.chdir(SRC)
import torch,joblib
torch.set_num_threads(4)
from scripts.scripts_test_video import hawor_video as hv
from hawor.utils.process import get_mano_faces,run_mano,run_mano_left
source=inspect.getsource(hv.hawor_motion_estimation)
source=source.replace('model, model_cfg = load_hawor(args.checkpoint)','model, model_cfg = _SHARED_MODEL')
source=source.replace('img_center = [img.shape[1] / 2, img.shape[0] / 2]# w/2, h/2','img_center = args.calibration_center')
begin=source.index('    H, W = img.shape[:2]')
end=source.index('    frame_chunks_all = defaultdict(list)',begin)
source=source[:begin]+source[end:]
begin=source.index('            # get hand mask')
end=source.index('    joblib.dump(frame_chunks_all',begin)
source=source[:begin]+source[end:]
adapted=ROOT/'scripts/data_eval/hawor_motion_camera_adapted.py'
adapted.write_text(source)
checkpoint=str(SRC/'weights/hawor/checkpoints/hawor.ckpt')
shared=hv.load_hawor(checkpoint)
ns=dict(hv.__dict__);ns['_SHARED_MODEL']=shared
exec(compile(source,str(adapted),'exec'),ns)
motion=ns['hawor_motion_estimation']
manifest=json.loads((ROOT/'data/inputs_manifest.json').read_text())
outroot=ROOT/'outputs/hawor';outroot.mkdir(parents=True,exist_ok=True)
state={'started_unix':time.time(),'gpu':os.environ.get('CUDA_VISIBLE_DEVICES'),'method':'official HaWoR camera mode + fixed published calibration','samples':{}}
status=ROOT/'reports/data_inventory_hawor_status.json'
def save():status.write_text(json.dumps(state,indent=2)+'\n')
save()
cap=np.array([[92,38,234],[234,38,239],[38,122,239],[239,122,279],[122,118,279],[279,118,215],[118,117,215],[215,117,214],[117,119,214],[214,119,121],[119,120,121],[121,120,78],[120,108,78],[78,108,79]])
fr=np.concatenate([get_mano_faces(),cap],axis=0).astype(np.int32);fl=fr[:,[0,2,1]]
for s in manifest['samples']:
 sid=s['id'];t0=time.time();dest=outroot/sid;seq=dest/'work';seq.mkdir(parents=True,exist_ok=True);z=np.load(s['input_npz']);n=s['frame_count'];K=z['K']
 f=float(np.median((K[:,0,0]+K[:,1,1])/2));center=np.median(K[:,:2,2],axis=0).tolist();eff=np.array([[f,0,center[0]],[0,f,center[1]],[0,0,1.]])
 state['samples'][sid]={'status':'running','started_unix':t0,'focal':f,'center':center,'output':str(dest/'predictions.npz')};save()
 print('START',sid,'focal',f,'center',center,flush=True)
 try:
  images=seq/'extracted_images'
  if not images.exists():images.symlink_to(s['rgb_frames'],target_is_directory=True)
  trackdir=seq/f'tracks_0_{n}';trackdir.mkdir(exist_ok=True)
  old=Path(s['bbox_source']).parent
  for name in ['model_boxes.npy','model_tracks.npy']:
   if not (trackdir/name).exists():shutil.copy2(old/name,trackdir/name)
  args=SimpleNamespace(checkpoint=checkpoint,infiller_weight=str(SRC/'weights/hawor/checkpoints/infiller.pt'),video_path=str(images),img_focal=f,calibration_center=center,static_camera=True)
  chunks,_=motion(args,0,n,str(seq))
  with torch.no_grad():pt,pr,pp,pb,pv=hv.hawor_infiller(args,0,n,chunks,True)
  verts=[];joints=[]
  for hi,func in enumerate([run_mano_left,run_mano]):
   with torch.no_grad():o=func(pt[hi:hi+1],pr[hi:hi+1],pp[hi:hi+1],betas=pb[hi:hi+1])
   verts.append(o['vertices'][0].detach().cpu().numpy());joints.append(o['joints'][0].detach().cpu().numpy())
  verts=np.stack(verts,axis=1);joints=np.stack(joints,axis=1)
  native_valid=np.asarray(pv).T.astype(bool)
  np.savez_compressed(dest/'predictions.npz',verts_cam=verts,joints_cam=joints,vertices_camera=verts,joints_camera=joints,valid=native_valid,detected=z['detected'],side_order=z['side_order'],faces_left=fl,faces_right=fr,K=K,K_used=np.repeat(eff[None],n,axis=0),frame_ids=z['frame_ids'],timestamps_s=z['timestamps_s'],mano_transl=pt.numpy().transpose(1,0,2),mano_global_orient=pr.numpy().transpose(1,0,2),mano_hand_pose=pp.numpy().transpose(1,0,2),mano_betas=pb.numpy().transpose(1,0,2))
  receipt=dict(method='HaWoR camera mode',source=str(SRC),checkpoint=checkpoint,infiller=args.infiller_weight,input=s,calibration_effective=eff.tolist(),changes=['use published fx/fy average and median principal point','reuse identical detector tracks and cached image pixels','omit SLAM-mask-only rasterization and legacy aitviewer export; all model and infiller computations unchanged'],raw_valid=native_valid.sum(0).tolist(),detected=z['detected'].sum(0).tolist(),seconds=time.time()-t0,cuda_peak_allocated_mib=torch.cuda.max_memory_allocated()/2**20)
  (dest/'receipt.json').write_text(json.dumps(receipt,indent=2)+'\n')
  state['samples'][sid].update(status='completed',seconds=time.time()-t0,valid=native_valid.sum(0).tolist());save();print('DONE',sid,receipt['seconds'],flush=True)
 except Exception:
  state['samples'][sid].update(status='failed',traceback=traceback.format_exc());save();raise
state['completed_unix']=time.time();state['status']='completed';save()

