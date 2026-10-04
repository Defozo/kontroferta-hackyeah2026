import test from 'node:test';
import assert from 'node:assert/strict';
import { zonedInstant, localParts } from '../src/dates.ts';
import { previewRecordedDemo } from '../src/recorded.ts';
import type { CaseDetail } from '../src/types.ts';

test('Warsaw UTC conversions and overnight service preserve explicit dates',()=>{
  assert.equal(zonedInstant('2026-10-10','09:00','Europe/Warsaw'),'2026-10-10T07:00:00.000Z');
  assert.equal(zonedInstant('2026-12-10','09:00','Europe/Warsaw'),'2026-12-10T08:00:00.000Z');
  assert.equal(zonedInstant('2026-10-11','01:00','Europe/Warsaw'),'2026-10-10T23:00:00.000Z');
  assert.deepEqual(localParts('2026-10-10T23:00:00Z','Europe/Warsaw'),{date:'2026-10-11',time:'01:00'});
  assert.throws(()=>zonedInstant('2026-03-29','02:30','Europe/Warsaw'));
  assert.throws(()=>zonedInstant('2026-10-25','02:30','Europe/Warsaw'));
  assert.throws(()=>zonedInstant('2026-10-10','09:00','Unknown/Zone'));
});

const example={recordedDemo:true,offers:[{id:'A'},{id:'B'},{id:'C'}],analysis:{offers:[{id:'A'},{id:'B'},{id:'C'}]}} as unknown as CaseDetail;
test('Public authored demo retains exact one-grosz winner and budget boundaries',()=>{
  for(const [value,winners,aFeasible] of [[0,['A'],true],[69900,['A'],true],[69999,['A'],true],[70000,['A','B'],true],[70001,['B'],true],[70100,['B'],true],[79999,['B'],true],[80000,['B'],true],[80001,['B'],false],[80100,['B'],false],[120000,['B'],false]] as Array<[number,string[],boolean]>){
    const preview=previewRecordedDemo(example,value);
    assert.deepEqual(preview.common_winners,winners,`Surcharge ${value}`);
    assert.equal(preview.robust_feasible.includes('A'),aFeasible,`Budget ${value}`);
    assert.equal(preview.scenarios[0].costs.A,480000+value);
    assert.equal(preview.robust_feasible.includes('C'),false);
  }
  assert.throws(()=>previewRecordedDemo(example,-1));
  assert.throws(()=>previewRecordedDemo(example,0.5));
  assert.throws(()=>previewRecordedDemo({...example,recordedDemo:false},0));
});
