#!/usr/bin/env python3
"""Validate the exact browser payload against published frame mappings and metrics."""
import json
from pathlib import Path
import numpy as np

ROOT=Path(__file__).resolve().parents[1]
D=ROOT/'docs'
def load(p): return json.loads(p.read_text())
def coords(m): return np.array([[[p if p is not None else [np.nan]*3 for p in h] for h in f] for f in m['joints']], dtype=float)
def main():
 total=0;counts={k:0 for k in ['gt','hggt_native','hggt_adapted','hawor']};infill=0
 for sample in load(D/'manifest.json')['samples']:
  sid=sample['id'];p=load(D/'interactive3d'/f'{sid}.json');n=sample['frame_count'];total+=n
  assert not p.get('preview_only'),sid
  assert p['frame_ids']==sample['source_frame_ids'] and len(p['frame_ids'])==n,sid
  assert p['unit']=='m' and p['side_order']==['left','right']
  assert np.all(np.diff(p['timestamps_s'])>0)
  assert np.allclose(np.array(p['timestamps_s'])-p['timestamps_s'][0],p['timestamps_relative_s'],atol=1e-9)
  assert len(p['joint_edges'])==20 and len(p['joint_order'])==21
  arrays={};masks={}
  for name,m in p['methods'].items():
   assert m['available'] and len(m['joints'])==n
   a=coords(m);v=np.array(m['valid']);jv=np.array(m['joint_valid']);assert a.shape==(n,2,21,3) and v.shape==(n,2)
   assert np.isfinite(a[v]).all() and np.isnan(a[~v]).all()
   assert np.array_equal(jv,np.isfinite(a).all(-1))
   assert 'points_file' not in m
   arrays[name]=a;masks[name]=v;counts[name]+=int(v.sum())
  assert p['methods']['gt']['license']['license_url'].startswith('https://creativecommons.org/')
  common=masks['gt'] & masks['hggt_native'] & masks['hggt_adapted'] & masks['hawor']
  published=load(D/'reports'/f'{sid}_metrics.json')['sample']
  assert int(common.sum())==published['paired_hand_frames']
  g=arrays['gt'];g=g-g[:,:,:1,:]
  for name,label in [('hggt_native','HGGT'),('hawor','HaWoR')]:
   a=arrays[name];a=a-a[:,:,:1,:]
   rr=float(np.linalg.norm((a-g)[common],axis=-1).mean()*1000)
   expected=next(m['rr_mpjpe_mm'] for m in published['methods'] if m['method']==label)
   assert abs(rr-expected)<.002,(sid,name,rr,expected)
  delta=arrays['hggt_adapted']-arrays['hggt_native'];assert np.max(np.abs((delta-delta[:,:,:1,:])[common]))<4e-6
  f=np.array(p['methods']['hawor']['infilled']);assert np.array_equal(f,masks['hawor'] & ~np.array(p['detected']));infill+=int(f.sum())
  print(f'{sid}: {n} frames, {int(common.sum())} matched hands, {int(f.sum())} labeled infills: PASS')
 assert total==446 and counts=={'gt':746,'hggt_native':715,'hggt_adapted':715,'hawor':746} and infill==31
 print('PASS:',total,'frames;',counts,'valid hands;',infill,'infills')
if __name__=='__main__': main()
