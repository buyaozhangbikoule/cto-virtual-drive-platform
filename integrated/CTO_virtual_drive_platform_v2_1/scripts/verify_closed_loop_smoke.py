"""Run three REAL solver feedback iterations. No measurement mocks here."""
from pathlib import Path
import json,sys
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from scripts import ltspice_closed_loop as cl

if __name__=='__main__':
    p=cl.create_session(frequency_hz=899000.,amplitude=.4,amplitude_target=.4,period_s=.001,max_steps=3)
    print('SESSION '+str(p),flush=True)
    for _ in range(3):
        r=cl.run_step(p)
        print(json.dumps(r,ensure_ascii=False),flush=True)
    state=cl.load(p/'session.json');records=state['records']
    assert len(records)==3
    for k in [1,2]:
        assert records[k]['command']==records[k-1]['next_command']
        assert cl.load(p/f'step_{k:03d}/stimulus.json')['parent_feedback_sha256']==cl.sha(p/f'step_{k-1:03d}/feedback.json')
    cl.dump(p/'smoke_acceptance.json',dict(real_ltspice=True,iterations=3,causal_chain_passed=True,
            no_analytic_feedback=True,scope='接口小规模实跑；非寻优收敛验收、非动态扰动/安全性证明'))
    print('REAL_FEEDBACK_CHAIN_PASSED',flush=True)
