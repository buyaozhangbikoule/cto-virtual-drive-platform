"""Synthetic feedback unit tests, NOT LTspice experimental evidence."""
import sys,unittest
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from scripts import ltspice_closed_loop as cl

class Decisions(unittest.TestCase):
    def setUp(self):
        self.cfg=dict(limits=cl.LIMITS,hold_steps=2,amplitude_target=.4,amplitude_increment=.05,power_deadband=.002,step_hz=500.)
        self.state=dict(direction=1,previous=.1,hold_left=0,trip=False)
        self.cmd=dict(frequency_hz=900000.,amplitude=.4)
        self.m=dict(max_window_vpp=50.,max_window_irms_A=.002,p_port_W=.02)
    def test_feedback_changes_next_frequency(self):
        good=cl.decide(self.cfg,self.state,self.cmd,self.m)
        bad=cl.decide(self.cfg,self.state,self.cmd,{**self.m,'p_port_W':.001})
        self.assertEqual(good[0]['frequency_hz'],900500)
        self.assertEqual(bad[0]['frequency_hz'],899500)
    def test_hard_trip_and_latch(self):
        n,s,status,_,_=cl.decide(self.cfg,self.state,self.cmd,{**self.m,'max_window_vpp':161})
        self.assertEqual(n['amplitude'],0);self.assertEqual(n['frequency_hz'],self.cmd['frequency_hz'])
        self.assertEqual(status,'TRIP_TO_ZERO')
        self.assertEqual(cl.decide(self.cfg,s,n,self.m)[2],'HALTED')
    def test_soft_and_hold(self):
        n,s,status,_,_=cl.decide(self.cfg,self.state,self.cmd,{**self.m,'max_window_irms_A':.0058})
        self.assertEqual(status,'FOLDBACK');self.assertLess(n['amplitude'],.4)
        self.assertEqual(n['frequency_hz'],900000);self.assertIsNone(s['previous'])
        self.assertEqual(cl.decide(self.cfg,s,n,self.m)[2],'HOLD')
    def test_ramp_does_not_change_frequency(self):
        result=cl.decide({**self.cfg,'amplitude_target':.8},self.state,self.cmd,self.m)
        self.assertEqual(result[0]['frequency_hz'],900000);self.assertAlmostEqual(result[0]['amplitude'],.45)
    def test_boundary(self):
        result=cl.decide(self.cfg,self.state,{**self.cmd,'frequency_hz':1000000},self.m)
        self.assertTrue(result[-1]);self.assertLess(result[0]['frequency_hz'],1000000)
    def test_zero_not_a_power_observation(self):
        self.assertEqual(cl.decide({**self.cfg,'amplitude_target':0},self.state,{**self.cmd,'amplitude':0},self.m)[2],'HOLD')

if __name__=='__main__':unittest.main()
