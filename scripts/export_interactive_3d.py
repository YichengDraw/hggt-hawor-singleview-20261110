#!/usr/bin/env python3
"""Export existing predictions; no inference, MANO assets, topology or GT fitting.

GT release requires --gt-release JSON keyed by dataset with license_url,
attribution and permission_basis, reviewed by the publisher. No GT meshes are
exported: the DexYCB evaluation cache's vertices have separate provenance.
"""
import argparse
import hashlib
import json
from pathlib import Path
import numpy as np

EDGES = [[0,1],[1,2],[2,3],[3,4],[0,5],[5,6],[6,7],[7,8],[0,9],[9,10],[10,11],[11,12],[0,13],[13,14],[14,15],[15,16],[0,17],[17,18],[18,19],[19,20]]
JOINT_NAMES = ['wrist'] + [f'{f}_{j}' for f in ['thumb','index','middle','ring','little'] for j in ['base','middle','distal','tip']]

def sha(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()

def dump(path, obj):
    path.write_text(json.dumps(obj, ensure_ascii=False, separators=(',', ':'), allow_nan=False)+'\n')

def checked(z, inp, name):
    for k in ['frame_ids', 'timestamps_s']:
        assert z[k].shape == inp[k].shape, (name,k)
        assert np.allclose(z[k], inp[k], rtol=0, atol=1e-7), (name,k)
    assert list(z['side_order'].astype(str)) == ['left','right'], name

def joint_json(j, valid):
    joint_valid = np.isfinite(j).all(-1) & valid[...,None]
    return [[[np.round(j[t,h,k].astype(float),6).tolist() if joint_valid[t,h,k] else None
              for k in range(21)] for h in range(2)] for t in range(len(j))], joint_valid

def main():
    ap=argparse.ArgumentParser(); ap.add_argument('--root',type=Path,required=True)
    ap.add_argument('--out',type=Path); ap.add_argument('--gt-release',type=Path)
    args=ap.parse_args(); root=args.root.resolve(); out=args.out or root/'site/interactive3d'
    release=json.loads(args.gt_release.read_text()) if args.gt_release else {}
    inputs=json.loads((root/'data/inputs_manifest.json').read_text())['samples']
    ev={x['id']:x for x in json.loads((root/'data/evaluation_manifest.json').read_text())['samples']}
    out.mkdir(parents=True,exist_ok=True); index=[]; checks=[]
    for s in inputs:
        sid=s['id']; paths={'input':Path(s['input_npz']),'gt':Path(ev[sid]['gt_npz']),
            'hggt':root/'outputs/hggt'/sid/'predictions.npz','hawor':root/'outputs/hawor'/sid/'predictions.npz'}
        z={k:np.load(p,allow_pickle=False) for k,p in paths.items()}; inp=z['input']; n=len(inp['frame_ids'])
        for k in ['gt','hggt','hawor']: checked(z[k],inp,k)
        assert n==s['frame_count']; ts=inp['timestamps_s'].astype(float)
        assert np.isfinite(ts).all() and np.all(np.diff(ts)>0)
        input_valid=inp['valid'].astype(bool); detected=inp['detected'].astype(bool)
        track=input_valid.any(0); hg=z['hggt']; hw=z['hawor']; gt=z['gt']
        masks={'gt':gt['valid'].astype(bool), 'hggt_native':hg['valid'].astype(bool)&input_valid,
            'hggt_adapted':hg['valid'].astype(bool)&hg['adapter_valid'].astype(bool)&input_valid,
            'hawor':hw['valid'].astype(bool)&track[None,:]}
        methods={}; stats={}; gt_release=release.get(s['dataset'])
        if gt_release:
            assert all(gt_release.get(k) for k in ['license_url','attribution','permission_basis'])
        for method,src,jkey,vkey in [('gt',gt,'joints_camera',None),
                ('hggt_native',hg,'joints_cam_native','verts_cam_native'),
                ('hggt_adapted',hg,'joints_cam','verts_cam'),('hawor',hw,'joints_cam','verts_cam')]:
            raw=np.asarray(src[jkey],dtype=float); assert raw.shape==(n,2,21,3),(sid,method,raw.shape)
            mask=masks[method]&np.isfinite(raw).all(axis=(-1,-2))
            stats[method]={'valid_hand_frames':int(mask.sum()),'by_side':mask.sum(0).tolist()}
            if method=='gt' and not gt_release:
                methods[method]={'available':False,'reason':'Dataset annotation redistribution permission not yet verified.'}; continue
            j=raw.copy()
            # Match the evaluation's dataset-defined fingertip locations while retaining
            # native 16 MANO kinematic joints. Native stored 21 joints use OpenPose order.
            if vkey:
                v=np.asarray(src[vkey],dtype=np.float32); assert v.shape==(n,2,778,3)
                tips=[745,317,444,556,673] if s['dataset']=='DexYCB' else [744,320,443,554,671]
                j[:,:,[4,8,12,16,20],:]=v[:,:,tips,:]
                mask &= np.isfinite(v).all(axis=(-1,-2))
            jj,jv=joint_json(j,mask)
            m={'available':True,'joints':jj,'valid':mask.tolist(),'joint_valid':jv.tolist(),
                'source_array':jkey,'source_valid':src['valid'].astype(bool).tolist(),'joint_definition':'OpenPose21; native kinematic joints, dataset-defined fingertip vertices for predictions'}
            if method=='hawor':m['infilled']=(mask&~detected).tolist()
            if method=='gt':m['license']=gt_release
            methods[method]=m
        # Verify translation adapter did not alter pose or scale in source geometry.
        common=masks['hggt_native']&masks['hggt_adapted']
        a=hg['joints_cam_native'];b=hg['joints_cam']
        delta=b-a
        residual=float(np.nanmax(np.abs((delta-delta[:,:,:1])[common]))) if common.any() else None
        assert residual is None or residual<1e-5,(sid,'adapter is not translation-only',residual)
        payload={'schema':'hggt-hawor-interactive3d-v1','id':sid,'frame_count':n,
            'frame_ids':inp['frame_ids'].astype(int).tolist(),'timestamps_s':ts.tolist(),
            'timestamps_relative_s':(ts-ts[0]).tolist(),'side_order':['left','right'],'unit':'m',
            'axes':'OpenCV +X right,+Y down,+Z forward','coordinate_space':'per-frame calibrated RGB camera; not a fixed world frame',
            'joint_order':JOINT_NAMES,'joint_edges':EDGES,'input_valid':input_valid.tolist(),'detected':detected.tolist(),
            'mask_notes':{'input_valid':'Finite positive-size tracked detection box; not identical to current-frame detected.',
                'detected':'Original detector detection flag. HaWoR available on an existing tracked side may be temporal infill.',
                'valid':'Finite output and method mask; HGGT also requires input box; adapted requires adapter_valid.',
                'joint_valid':'Finite individual joint AND whole-hand method display validity.'},
            'methods':methods,'provenance':{'source_sha256':{k:sha(p) for k,p in paths.items()},
                'sources':{'input':f'data/{sid}/input.npz','gt':f'data/{sid}/evaluation_gt.npz','hggt':f'outputs/hggt/{sid}/predictions.npz','hawor':f'outputs/hawor/{sid}/predictions.npz'},
                'source_preparation':s.get('source_preparation','Original input and evaluation NPZ caches'),'original_gt_cache_sha256':ev[sid].get('original_gt_cache_sha256'),'gt_dataset':s['dataset'],'sequence_id':s['sequence_id'],'camera_id':s['camera_id'],
                'timestamps_note':'DexYCB uses 30 Hz cached video timing; HOT3D uses original timestamp differences.',
                'gt_mesh_exported':False,'predicted_vertices_exported':False,'mano_topology_exported':False,'gt_used_to_fit_predictions':False,
                'hggt_adapted':'Translation-only fit to HGGT own projected joints and known intrinsics; not GT alignment.',
                'joint_quantization_m':1e-6,
                'adapter_translation_residual_max_m':residual}}
        dump(out/f'{sid}.json',payload)
        index.append({'id':sid,'file':f'{sid}.json','frame_count':n,'gt_available':bool(gt_release),'methods':[k for k,v in methods.items() if v.get('available')]})
        checks.append({'id':sid,'frame_identity_verified':True,'timestamps_verified':True,'stats':stats,'adapter_translation_residual_max_m':residual})
        print(sid,n,stats,flush=True)
    dump(out/'index.json',{'schema':'hggt-hawor-interactive3d-index-v1','samples':index})
    dump(out/'validation.json',{'samples':checks,'total_frames':sum(s['frame_count'] for s in index),'gt_mesh_exported':False,'model_topology_exported':False})

if __name__=='__main__': main()
