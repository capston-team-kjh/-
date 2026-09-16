import test from 'node:test';
import assert from 'node:assert/strict';
import {readFile} from 'node:fs/promises';
import {createHash} from 'node:crypto';
import * as ort from 'onnxruntime-web';
import {MODEL_SHA256,MODEL_CLASSES,validateProbabilities,ProductionDecision} from './production-decision.mjs';

test('shipped production bytes and real WASM outputs match contract',async()=>{
 const bytes=await readFile(new URL('../../public/focus_classifier.onnx',import.meta.url));
 assert.equal(createHash('sha256').update(bytes).digest('hex'),MODEL_SHA256);
 ort.env.wasm.numThreads=1;
 const session=await ort.InferenceSession.create(bytes,{executionProviders:['wasm']});
 try {
  assert.deepEqual(session.inputNames,['float_input']);
  assert.deepEqual(session.outputNames,['label','probabilities']);
  for(const flag of [2,3,4,6,8,9]){
   const x=new Float32Array(16);x[0]=x[1]=x[2]=1;x[flag]=1;
   const r=await session.run({float_input:new ort.Tensor('float32',x,[1,16])});
   assert.equal(r.probabilities.type,'float32');assert.deepEqual(r.probabilities.dims,[1,5]);
   validateProbabilities(r.probabilities.data);
   assert.equal(r.label.data[0],MODEL_CLASSES[Array.from(r.probabilities.data).indexOf(Math.max(...r.probabilities.data))]);
   assert.doesNotThrow(()=>new ProductionDecision().step(0,{faceSeen:false,personSeen:true},r.probabilities.data));
  }
 } finally {await session.release();}
});
