"""Reproduce camera-ray error decomposition from published joint JSON.
Run: python scripts/evaluate_view_depth.py (requires numpy).
All methods share the same valid hand frames and valid joints.
"""
import csv, hashlib, json
from pathlib import Path
import numpy as np
ROOT = Path(__file__).resolve().parents[1]
IDS = ['dexycb_box', 'dexycb_banana', 'aria_1976', 'aria_3209']
METHODS = ['hggt_native', 'hawor', 'hggt_adapted']

def compute():
    rows, hashes, totals = [], {}, {k: [] for k in METHODS}
    for seq in IDS:
        p = ROOT / 'docs/interactive3d' / (seq + '.json')
        hashes[seq] = hashlib.sha256(p.read_bytes()).hexdigest()
        d = json.loads(p.read_text()); ms = d['methods']
        assert d['unit'] == 'm' and d['joint_order'][0] == 'wrist'
        # JSON null whole joints become [nan,nan,nan].
        def array(k):
            return np.array([[[j if j is not None else [None]*3 for j in hand] for hand in frame] for frame in ms[k]['joints']], dtype=float)
        arrays = {k: array(k) for k in ['gt'] + METHODS}
        gt = arrays['gt']; valid = np.ones(gt.shape[:2], dtype=bool)
        jvalid = np.ones(gt.shape[:3], dtype=bool)
        for k in arrays:
            valid &= np.array(ms[k]['valid'], dtype=bool)
            jvalid &= np.array(ms[k]['joint_valid'], dtype=bool) & np.isfinite(arrays[k]).all(axis=-1)
        norms = np.linalg.norm(gt[:,:,0], axis=-1)
        valid &= np.isfinite(norms) & (norms > 1e-12) & jvalid[:,:,0]
        jvalid &= valid[:,:,None]
        rays = np.divide(gt[:,:,0], norms[:,:,None], out=np.zeros_like(gt[:,:,0]), where=(norms>1e-12)[:,:,None])
        for method in METHODS:
            err = arrays[method] - gt
            radial = np.sum(err * rays[:,:,None,:], axis=-1)[jvalid]
            total_sq = np.sum(err**2, axis=-1)[jvalid]
            perp_sq = np.maximum(0, total_sq-radial**2)
            values = (len(total_sq), int(valid.sum()), float(total_sq.sum()), float(np.sum(radial**2)), float(perp_sq.sum()), float(np.sqrt(total_sq).sum()))
            totals[method].append(values)
            rows.append(summarize(seq, method, values))
    for method in METHODS:
        rows.append(summarize('all',method, np.array(totals[method]).sum(axis=0)))
    return {'schema':'view-depth-error-v1','generated_date':'2026-11-11','ray':'unit vector from camera origin to GT wrist per hand-frame','aggregation':'sum radial squared error / sum full 3D squared error; pooled over joints, not mean of sequence percentages','units':'mm for distances; m^2 for stored energy sums','source_sha256':hashes,'rows':rows}

def summarize(seq, method, values):
    n, hands, full, radial, perpendicular, dist = values
    assert abs(full-radial-perpendicular) < 1e-7
    return dict(sequence=seq, method=method, hand_frames=int(hands), joints=int(n), radial_energy_pct=100*radial/full, radial_rmse_mm=1000*np.sqrt(radial/n), transverse_rmse_mm=1000*np.sqrt(perpendicular/n), full_rmse_mm=1000*np.sqrt(full/n), mpjpe_mm=1000*dist/n, full_squared_error_m2=float(full), radial_squared_error_m2=float(radial))

if __name__ == '__main__':
    result=compute(); out=ROOT/'docs/downloads/view_depth_errors.json'
    out.write_text(json.dumps(result,indent=2,ensure_ascii=False)+'\n')
    with out.with_suffix('.csv').open('w') as f:
        w=csv.DictWriter(f,fieldnames=result['rows'][0]);w.writeheader();w.writerows(result['rows'])
    for r in result['rows']: print(r['sequence'],r['method'],r['hand_frames'],round(r['radial_energy_pct'],3),round(r['radial_rmse_mm'],3),round(r['transverse_rmse_mm'],3))
