import { spawnSync } from 'node:child_process';
const r = spawnSync('unzip', ['-Z1', process.argv[2]], { encoding: 'utf8' });
console.log(JSON.stringify({status:r.status,error:r.error?.message,stdout:r.stdout?.slice(0,100),stderr:r.stderr?.slice(0,300),path:process.env.PATH}, null, 2));
