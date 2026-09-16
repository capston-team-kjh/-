// Initial settings reuse prior candidate durations; earRatio is an initial
// calibration setting. This production/rule combination has NOT passed a new
// accuracy evaluation. Never tune these on the consumed test.
export const SETTINGS = Object.freeze({calibrationSamples:5, drowsyProbability:0.65,
 drowsyMs:5000, closureMs:10000, irisDelta:0.08, headDelta:0.04,
 gazeDownMs:2000, confidence:0.65, maxGapMs:1500, earRatio:0.7});
export const MODEL_CLASSES = Object.freeze(['drowsy','focus','gaze_down','gaze_side','unknown']);
export const MODEL_SHA256='e07aabc51e7ac1b48610ebd3eba25bd671297d1a4b25a48c1ba379f4f125577f';
export function validateFeatures(features) {
 if (!(features instanceof Float32Array) || features.length!==16 || !features.every(Number.isFinite))
  throw new Error('Invalid production feature contract');
}
export function validateProbabilities(p) {
 if(p.length!==5 || !Array.from(p).every(v=>Number.isFinite(v)&&v>=0&&v<=1) || Math.abs(Array.from(p).reduce((a,b)=>a+b,0)-1)>1e-4)
  throw new Error('Invalid production probability contract');
}
const median = values => [...values].sort((a,b)=>a-b)[Math.floor(values.length/2)];
export class ProductionDecision {
 constructor(){this.reset();}
 reset(){this.samples=[];this.baseline=null;this.last=null;this.since={};}
 duration(key,active,now){if(!active){delete this.since[key];return 0;}if(this.since[key]===undefined)this.since[key]=now;return now-this.since[key];}
 step(now,s,p){
  if(!Number.isFinite(now))throw new Error('Invalid timestamp');
  if(p!==null)validateProbabilities(p);
  const continuous=this.last!==null && now>this.last && now-this.last<=SETTINGS.maxGapMs;
  if(!continuous){this.since={};if(!this.baseline)this.samples=[];}
  this.last=now;
  const index=p===null?-1:Array.from(p).indexOf(Math.max(...p));
  const result=(state,source,mp='unknown')=>({model_state:index<0?'unknown':MODEL_CLASSES[index],
   model_confidence:index<0?0:p[index],mediapipe_state:mp,final_state:state,decision_source:source,
   calibration_valid:Boolean(this.baseline)});
  if(!s.personSeen&&!s.faceSeen){this.since={};this.samples=[];return result('absent','mediapipe_absent','absent');}
  if(!s.faceSeen || ![s.ear,s.irisY,s.head].every(Number.isFinite)){
   this.since={};this.samples=[];return result('unknown','front_signal_missing');
  }
  if(!this.baseline){
   // User is explicitly asked to look straight ahead with eyes open.
   if(s.ear>0.16 && s.head<0.72 && s.irisY>=0 && s.irisY<=1){
    this.samples.push({ear:s.ear,irisY:s.irisY,head:s.head});
    if(this.samples.length>=SETTINGS.calibrationSamples)this.baseline={
     ear:median(this.samples.map(x=>x.ear)),irisY:median(this.samples.map(x=>x.irisY)),head:median(this.samples.map(x=>x.head))};
   }else this.samples=[];
   this.since={};return result('unknown','personal_calibration');
  }
  const closed=s.ear<=this.baseline.ear*SETTINGS.earRatio;
  const down=s.head-this.baseline.head>=SETTINGS.headDelta;
  const active=s.pageTurn||s.penFidget||s.restlessHand;
  const drowsyEvidence=closed||(down&&!active);
  const gaze=s.irisY-this.baseline.irisY>=SETTINGS.irisDelta&&down;
  const closure=this.duration('closure',closed,now);
  const combined=this.duration('drowsy',p!==null&&p[0]>=SETTINGS.drowsyProbability&&drowsyEvidence,now);
  const gazeMs=this.duration('gaze',gaze,now);
  if(closed&&closure>=SETTINGS.closureMs)return result('drowsy','mediapipe_long_eye_closure','drowsy');
  if(p!==null&&p[0]>=SETTINGS.drowsyProbability&&drowsyEvidence&&combined>=SETTINGS.drowsyMs)return result('drowsy','model_and_mediapipe','drowsy');
  if(gaze&&gazeMs>=SETTINGS.gazeDownMs)return result('gaze_down','mediapipe_gaze_down','gaze_down');
  if(index===3&&p[index]>=SETTINGS.confidence)return result('gaze_side','model');
  if(s.badPosture)return result('bad_posture','mediapipe_posture','bad_posture');
  for(const [flag,state] of [['pageTurn','page_turn'],['penFidget','pen_fidget'],['restlessHand','restless_hand']])
   if(s[flag])return result(state,'mediapipe_hand_activity',state);
  if(index===1&&p[index]>=SETTINGS.confidence)return result('focus','model');
  // Never relabel a discarded gaze_down/unknown probability as focus or drowsy.
  return result('unknown',p===null?'model_unavailable':'low_confidence_or_excluded_class');
 }
}
export const toTimelinePoint=(t,decision)=>({t,state:decision.final_state});
