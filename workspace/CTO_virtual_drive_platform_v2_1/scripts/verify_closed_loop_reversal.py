"""Five actual solver rounds to check feedback reversal, not convergence/safety."""
from pathlib import Path
import json,sys
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from scripts import ltspice_closed_loop as cl

if __name__=='__main__':
    p=cl.create_session(frequency_hz=899000.,amplitude=.4,amplitude_target=.4,
                        period_s=.001,step_hz=500.,max_steps=5)
    print('SESSION '+str(p),flush=True)
    for _ in range(5):
        r=cl.run_step(p)
        print(json.dumps({k:r[k] for k in ['iteration','command','next_command','reason','wall_seconds']}|
            {'measured_p_port_mW':r['measurement']['p_port_W']*1000},ensure_ascii=False),flush=True)
    records=cl.load(p/'session.json')['records']
    chain=all(records[k]['command']==records[k-1]['next_command'] and
        cl.load(p/f'step_{k:03d}/stimulus.json')['parent_feedback_sha256']==cl.sha(p/f'step_{k-1:03d}/feedback.json')
        for k in range(1,len(records)))
    reversals=[]
    for k in range(1,len(records)-1):
        prev,cur,nxt=records[k-1],records[k],records[k+1]
        incoming=cur['command']['frequency_hz']-prev['command']['frequency_hz']
        outgoing=nxt['command']['frequency_hz']-cur['command']['frequency_hz']
        if incoming*outgoing<0:
            reversals.append({'decision_iteration':k+1,'executed_iteration':k+2,
                'previous_power_W':prev['measurement']['p_port_W'],
                'current_power_W':cur['measurement']['p_port_W'],
                'measured_power_declined':cur['measurement']['p_port_W']<prev['measurement']['p_port_W']})
    result={'real_ltspice':True,'iterations':len(records),'causal_chain_passed':chain,
        'executed_reversals':reversals,'feedback_reversal_passed':chain and any(r['measured_power_declined'] for r in reversals),
        'scope':'固定负载低幅五轮接口检查；不是全局寻优、动态扰动、连续稳态或硬保护验收'}
    cl.dump(p/'reversal_acceptance.json',result)
    print(json.dumps(result,ensure_ascii=False),flush=True)
    if not result['feedback_reversal_passed']:raise SystemExit('未观测到预期反馈反向，保留结果供检查')
