export interface Signals { faceSeen:boolean; personSeen:boolean; ear:number; irisY:number; head:number; badPosture:boolean; pageTurn:boolean; penFidget:boolean; restlessHand:boolean; }
export interface Decision {model_state:string; model_confidence:number; mediapipe_state:string; final_state:string; decision_source:string; calibration_valid:boolean;}
export const MODEL_CLASSES: readonly string[];
export const MODEL_SHA256: string;
export const SETTINGS: Readonly<Record<string,number>>;
export function validateFeatures(features: Float32Array): void;
export function validateProbabilities(probabilities: Float32Array | number[]): void;
export class ProductionDecision {reset():void;step(now:number,signals:Signals,probabilities:Float32Array | number[] | null):Decision;}
export function toTimelinePoint(t:number,decision:Decision):{t:number;state:string};
