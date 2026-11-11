import importlib.util
import unittest
from pathlib import Path
import numpy as np
p=Path(__file__).resolve().parents[1]/'scripts/evaluate_view_depth.py'
s=importlib.util.spec_from_file_location('depth',p);d=importlib.util.module_from_spec(s);s.loader.exec_module(d)
class DepthTests(unittest.TestCase):
 def test_synthetic_summary(self):
  r=d.summarize('test','test',(2,1,25,9,16,7))
  self.assertAlmostEqual(r['radial_energy_pct'],36)
  self.assertAlmostEqual(r['full_rmse_mm']**2,r['radial_rmse_mm']**2+r['transverse_rmse_mm']**2)
 def test_shared_denominators_and_energy(self):
  rows=d.compute()['rows']
  for seq in d.IDS+['all']:
   rs=[r for r in rows if r['sequence']==seq]
   self.assertEqual(len({r['joints'] for r in rs}),1)
   self.assertEqual(len({r['hand_frames'] for r in rs}),1)
   for r in rs:
    self.assertTrue(0<=r['radial_energy_pct']<=100)
    self.assertAlmostEqual(r['full_rmse_mm']**2,r['radial_rmse_mm']**2+r['transverse_rmse_mm']**2,places=5)
  total=[r for r in rows if r['sequence']=='all' and r['method']=='hggt_native'][0]
  self.assertEqual(total['hand_frames'],715);self.assertEqual(total['joints'],15015)
  self.assertAlmostEqual(total['radial_energy_pct'],98.52978,places=4)
if __name__=='__main__': unittest.main()
