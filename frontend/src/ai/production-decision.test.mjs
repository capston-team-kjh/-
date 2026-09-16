import test from 'node:test';
import assert from 'node:assert/strict';
import { ProductionDecision, toTimelinePoint, validateFeatures } from './production-decision.mjs';

const neutral = {faceSeen:true, personSeen:true, ear:0.3, irisY:0.5, head:0.5,
 badPosture:false, pageTurn:false, penFidget:false, restlessHand:false};
test('stale front evidence interrupts sustained drowsiness',()=>{
 const e=ready(), closed={...neutral,ear:0.05};
 for(let t=5000;t<10000;t+=1000)e.step(t,closed,[1,0,0,0,0]);
 assert.equal(e.step(10000,{...closed,faceSeen:false},null).final_state,'unknown');
 assert.notEqual(e.step(11000,closed,[1,0,0,0,0]).final_state,'drowsy');
});
function ready() {
 const engine = new ProductionDecision();
 for(let t=0;t<5000;t+=1000) engine.step(t,neutral,[0,1,0,0,0]);
 return engine;
}
test('ONNX gaze_down cannot create final gaze_down',()=>{
 assert.equal(ready().step(5000,neutral,[0,0,1,0,0]).final_state,'unknown');
});
test('calibrated iris and head evidence must last two seconds',()=>{
 const e=ready(), s={...neutral,irisY:0.65,head:0.6};
 assert.notEqual(e.step(5000,s,[0,1,0,0,0]).final_state,'gaze_down');
 e.step(6000,s,[0,1,0,0,0]);
 const d=e.step(7000,s,[0,1,0,0,0]);
 assert.equal(d.final_state,'gaze_down'); assert.equal(d.decision_source,'mediapipe_gaze_down');
});
test('uncalibrated or missing front face cannot become drowsy',()=>{
 const e=new ProductionDecision();
 for(let t=0;t<20000;t+=1000) assert.notEqual(e.step(t,{...neutral,ear:0.05},[1,0,0,0,0]).final_state,'drowsy');
 assert.equal(ready().step(5000,{...neutral,faceSeen:false},[1,0,0,0,0]).final_state,'unknown');
});
test('model drowsy needs bodily evidence and five continuous seconds',()=>{
 const e=ready();
 assert.notEqual(e.step(5000,neutral,[1,0,0,0,0]).final_state,'drowsy');
 for(let t=6000;t<11000;t+=1000) assert.notEqual(e.step(t,{...neutral,head:0.6},[1,0,0,0,0]).final_state,'drowsy');
 assert.equal(e.step(11000,{...neutral,head:0.6},[1,0,0,0,0]).final_state,'drowsy');
});
test('time gaps reset duration counters',()=>{
 const e=ready(); for(let t=5000;t<10000;t+=1000)e.step(t,{...neutral,head:0.6},[1,0,0,0,0]);
 assert.notEqual(e.step(20000,{...neutral,head:0.6},[1,0,0,0,0]).final_state,'drowsy');
});
test('strong eye closure works without ONNX after calibration',()=>{
 const e=ready(); for(let t=5000;t<15000;t+=1000)assert.notEqual(e.step(t,{...neutral,ear:0.05},null).final_state,'drowsy');
 assert.equal(e.step(15000,{...neutral,ear:0.05},null).decision_source,'mediapipe_long_eye_closure');
});
test('invalid numeric features fail instead of becoming zero',()=>{
 assert.throws(()=>validateFeatures(new Float32Array(34)));
 const f=new Float32Array(16);f[2]=NaN;assert.throws(()=>validateFeatures(f));
 f[2]=Infinity;assert.throws(()=>validateFeatures(f));
});
test('invalid front signals yield unknown and reset evidence',()=>{
 assert.equal(ready().step(5000,{...neutral,irisY:NaN},[1,0,0,0,0]).final_state,'unknown');
});
test('invalid probability contract fails',()=>{
 assert.throws(()=>ready().step(5000,neutral,[0,1,0]));
 assert.throws(()=>ready().step(5000,neutral,[NaN,1,0,0,0]));
});
test('absence and existing hand/posture states remain available',()=>{
 assert.equal(ready().step(5000,{...neutral,faceSeen:false,personSeen:false},null).final_state,'absent');
 for(const [flag,state] of [['badPosture','bad_posture'],['pageTurn','page_turn'],['penFidget','pen_fidget'],['restlessHand','restless_hand']])
 assert.equal(ready().step(5000,{...neutral,[flag]:true},[0,1,0,0,0]).final_state,state);
});
test('timeline contains final state only, with time',()=>{
 assert.deepEqual(toTimelinePoint(4,ready().step(5000,neutral,[0,1,0,0,0])),{t:4,state:'focus'});
});
test('hand activity prevents head-down-only drowsy confirmation',()=>{
 const e=ready();for(let t=5000;t<20000;t+=1000)assert.notEqual(e.step(t,{...neutral,head:0.6,pageTurn:true},[1,0,0,0,0]).final_state,'drowsy');
});
test('new session requires calibration again',()=>{
 const e=ready();e.reset();assert.equal(e.step(10000,neutral,[0,1,0,0,0]).decision_source,'personal_calibration');
});
test('iris alone or head alone cannot generate gaze_down',()=>{
 for(const signal of [{irisY:0.7},{head:0.7}]){
 const e=ready();for(let t=5000;t<10000;t+=1000)assert.notEqual(e.step(t,{...neutral,...signal},[0,0,1,0,0]).final_state,'gaze_down');
 }
});
