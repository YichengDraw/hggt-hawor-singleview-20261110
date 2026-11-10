from pathlib import Path
import json,numpy as np
R=Path('/nvme-ssd2/zhaoyicheng/hggt-reproduction-20261110')
DOAS=Path('/nvme-ssd2/zhaoyicheng/doas-official-projection-20261030')
ARIA=Path('/nvme-ssd2/zhaoyicheng/aria-calibration-audit-20261030/hot3d_official')
order=['left','right'];samples=[];evaluation=[];summary=[]
for sid,kind,seq,n in [('dexycb_box','DexYCB','20200928_143606',74),('dexycb_banana','DexYCB','20200928_145724',72),('aria_1976','HOT3D-Aria','001976',150),('aria_3209','HOT3D-Aria','003209',150)]:
 d=R/'data'/sid;d.mkdir(parents=True,exist_ok=True)
 if kind=='DexYCB':
  hp=Path('/nvme-ssd1/wlq/doas-reproduction-20261018/benchmarks/rgb_frontend/raw')/sid/sid;video=hp.parent/(sid+'.mp4')
  gp=Path('/nvme-ssd1/wlq/doas-reproduction-20261018/benchmarks/dexycb/heldout_reference')/seq/'gt.npz';z=np.load(gp)
  K=z['K'].astype(np.float64);frame_ids=z['frame_id'];times=np.arange(n)/30.;camera='836212060125';size=(640,480)
  j=np.full((n,2,21,3),np.nan,np.float32);j[:,1]=z['joints_m'];mask=np.zeros((n,2),bool);mask[:,1]=z['valid'];vis=mask.astype(np.float32);c2w=None
  vn='G_box' if sid.endswith('box') else 'G_banana';gv=np.load(Path('/nvme-ssd1/zhaoyicheng/contact-backend-benchmark-20261102/data/raw')/vn/vn/'all_hand_meshes.npz')
  verts=np.full((n,2,778,3),np.nan,np.float32);verts[:,1]=gv['right_vertices'];faces=gv['right_faces'];cal_src=str(gp)+' :: K only, published RGB camera calibration'
 else:
  hp=DOAS/'frontend/rgb'/('clip-'+seq)/('clip-'+seq);video=hp.parent/('clip-'+seq+'.mp4')
  cm=json.loads((ARIA/seq/'manifest.json').read_text());K=np.asarray([f['K_768'] for f in cm['frames']],np.float64);frame_ids=np.array([f['source_frame'] for f in cm['frames']]);ts=np.array([f['timestamp_ns'] for f in cm['frames']],np.int64);times=(ts-ts[0])*1e-9;camera='214-1';size=(768,768)
  gp=Path('/nvme-ssd1/wlq/doas-reproduction-20261018/aria/eval_gt/trajectory_gt')/('clip-'+seq)/'gt_hand_object.npz';z=np.load(gp);assert np.array_equal(ts,z['timestamp_ns']);c2w=z['c2w'];w2c=np.linalg.inv(c2w)
  j=np.stack([np.einsum('tij,tkj->tki',w2c[:,:3,:3],z[s+'_joints_world'])+w2c[:,:3,3,None].transpose(0,2,1) for s in order],axis=1)
  mask=np.stack([z[s+'_valid'] for s in order],axis=1).astype(bool);vis=np.stack([z[s+'_rgb_visibility'] for s in order],axis=1);verts=None;faces=None;cal_src=str(ARIA/seq/'manifest.json')+' :: per-frame K_768'
 tracks=np.load(hp/f'tracks_0_{n}/model_tracks.npy',allow_pickle=True).item()
 box=np.full((n,2,4),np.nan,np.float32);score=np.full((n,2),np.nan,np.float32);det=np.zeros((n,2),bool);ids=np.full((n,2),-1,np.int32)
 for tid,rows in tracks.items():
  for row in rows:
   i=int(row['frame']);h=int(np.asarray(row['det_handedness']).reshape(-1)[0]);b=np.asarray(row['det_box']).reshape(-1,5)[0]
   if not (0<=i<n and h in [0,1]):continue
   if np.isfinite(score[i,h]) and score[i,h]>=b[4]:continue
   box[i,h]=b[:4];score[i,h]=b[4];det[i,h]=bool(row['det']);ids[i,h]=int(float(tid))
 valid=np.isfinite(box).all(-1)&((box[:,:,2:]-box[:,:,:2])>0).all(-1)
 imgs=sorted(p for p in (hp/'extracted_images').iterdir() if p.suffix.lower() in ['.png','.jpg','.jpeg']);assert len(imgs)==n,(sid,len(imgs),n)
 np.savez_compressed(d/'input.npz',bbox=box,valid=valid,detected=det,score=score,K=K,frame_ids=frame_ids,timestamps_s=times,side_order=np.array(order),image_paths=np.array([str(x) for x in imgs]),image_size=np.array(size),track_ids=ids)
 samples.append(dict(id=sid,dataset=kind,sequence_id=seq,frame_count=n,camera_id=camera,rgb_video=str(video),rgb_frames=str(hp/'extracted_images'),input_npz=str(d/'input.npz'),image_size=list(size),bbox_source=str(hp/f'tracks_0_{n}/model_tracks.npy'),bbox_format='xyxy, unexpanded detector box; runner applies fixed1.2 expansion',hand_order=order,calibration_source=cal_src,pixel_contract='same cached images originally read by HaWoR',split_status='development examples; author training overlap unknown',gt_inference_access=False))
 h=np.load(hp/'all_hand_meshes.npz');hj=np.stack([h[s+'_joints'] for s in order],axis=1);hv=np.stack([h[s+'_vertices'] for s in order],axis=1);hm=np.stack([h[s+'_valid'] for s in order],axis=1).astype(bool);f=float((hp/'img_focal.txt').read_text());Kh=np.array([[f,0,size[0]/2],[0,f,size[1]/2],[0,0,1]])
 np.savez_compressed(d/'hawor_legacy.npz',joints_camera=hj,vertices_camera=hv,valid=hm,side_order=np.array(order),K_used=np.repeat(Kh[None],n,axis=0),faces_left=h['left_faces'],faces_right=h['right_faces'])
 gd=dict(joints_camera=j.astype(np.float32),valid=mask,visibility=vis,side_order=np.array(order),frame_ids=frame_ids,timestamps_s=times,K=K,eval_only=np.array(True))
 if c2w is not None:gd['camera_to_world']=c2w
 if verts is not None:gd['vertices_camera']=verts;gd['faces_right']=faces
 np.savez_compressed(d/'evaluation_gt.npz',**gd)
 evaluation.append(dict(id=sid,gt_npz=str(d/'evaluation_gt.npz'),gt_source=str(gp),hawor_legacy=str(d/'hawor_legacy.npz'),hawor_source=str(hp/'all_hand_meshes.npz'),legacy_hawor_focal=f,legacy_hawor_mode='static_camera; camera-space only',annotation_joint_order='OpenPose21 wrist thumb index middle ring little',note='GT camera trajectory used for scoring only'))
 summary.append(dict(id=sid,n=n,detected=det.sum(0).tolist(),box_valid=valid.sum(0).tolist(),gt_valid=mask.sum(0).tolist(),legacy_valid=hm.sum(0).tolist(),K_first=K[0].tolist(),legacy_focal=f,first_image=str(imgs[0]),last_image=str(imgs[-1])))
(R/'data/inputs_manifest.json').write_text(json.dumps(dict(schema='hggt-singleview-inputs-v1',hand_order=order,samples=samples),indent=2)+'\n')
(R/'data/evaluation_manifest.json').write_text(json.dumps(dict(schema='hggt-singleview-evaluation-v1',eval_only=True,samples=evaluation),indent=2)+'\n')
(R/'reports/data_inventory.json').write_text(json.dumps(summary,indent=2)+'\n')
print(json.dumps(summary,indent=2))
