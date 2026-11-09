const assert=require('assert'); const A=require('./attendance');
class Mem{constructor(){this.m=new Map()}getItem(k){return this.m.get(k)||null}setItem(k,v){this.m.set(k,v)}removeItem(k){this.m.delete(k)}}
const s=new Mem(),e={id:'e1',name:'Safety Webinar',date:'2026-11-01',time:'10:00-11:00',hrs:2,hrs_est:false};
assert.equal(A.get('e1',s).state,'unknown'); assert.throws(()=>A.set('e1','maybe',s)); A.set('e1','attended',s); assert.equal(A.get('e1',s).state,'attended');
assert.equal(A.shouldPrompt(e,'opened',new Date('2026-11-02T00:00:00+08:00'),new Mem()),false); assert.equal(A.shouldPrompt(e,'registered_manual',new Date('2026-11-02T00:00:00+08:00'),new Mem()),true);
let logs=A.addToLog([],e,'H&S',2); assert.equal(logs.length,1); assert.throws(()=>A.addToLog(logs,e,'H&S',2)); assert.throws(()=>A.buildLogRecord(e,'H&S',0)); console.log('attendance tests PASS');
