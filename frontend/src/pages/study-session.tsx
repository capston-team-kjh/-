import { useState, useEffect, useRef, useMemo } from "react";
import { Play, Square, Activity, TrendingUp, Camera, Settings2 } from "lucide-react";
import { setupDualCameras } from "@/utils/dualCamManager"; 
import { FaceLandmarker, PoseLandmarker, FilesetResolver } from "@mediapipe/tasks-vision";
import * as ort from "onnxruntime-web";
import {
  AreaChart, Area, XAxis, YAxis, CartesianGrid, Tooltip, ResponsiveContainer
} from "recharts";

// IMPORT ALL NATIVE ML ENGINES
import { extractFrontMeasurements } from "../ai/continuous-features";
import { resolveHybridDecision } from "../ai/hybrid-decision";
import { FrontV2FeaturePipeline } from "../ai/front-v2-pipeline";

// FIX: Bumped gaze_down to 100 so reading a book is recorded as focused studying!
const STATE_WEIGHTS: Record<string, number> = {
  "focus": 100, "bad_posture": 60, "gaze_away": 40, "gaze_side": 40,
  "gaze_down": 100, "unknown": 50, "present_unknown": 50,
  "drowsy": 20, "sleep_suspect": 20, "absent": 0,
};

const FILTER_CONFIG: Record<string, number> = {
  gaze_side: 2,
  gaze_down: 2,
  bad_posture: 2,
  absent: 4,
};

const ANALYZE_CONFIG = {
  page_turn_min_path_len: 0.18,
  page_turn_min_net_disp: 0.14,
  page_turn_max_dir_changes: 2,
  page_turn_min_x_span: 0.12,
  page_turn_max_y_span: 0.10,

  pen_fidget_min_path_len: 0.18,
  pen_fidget_max_bbox_diag: 0.12,
  pen_fidget_min_dir_changes: 3,

  restless_hand_min_path_len: 0.28,
  restless_hand_min_bbox_diag: 0.18,
  restless_hand_min_dir_changes: 2,
};

const getHandFeatures = (points: {x: number, y: number}[]) => {
  if (points.length < 2) return null;
  let pathLen = 0;
  for (let i = 1; i < points.length; i++) {
    pathLen += Math.hypot(points[i].x - points[i-1].x, points[i].y - points[i-1].y);
  }
  const netDisp = Math.hypot(points[points.length-1].x - points[0].x, points[points.length-1].y - points[0].y);
  const xs = points.map(p => p.x);
  const ys = points.map(p => p.y);
  const xSpan = Math.max(...xs) - Math.min(...xs);
  const ySpan = Math.max(...ys) - Math.min(...ys);
  const bboxDiag = Math.hypot(xSpan, ySpan);

  let dirChanges = 0;
  if (points.length >= 3) {
    const vectors = [];
    for (let i = 1; i < points.length; i++) {
      const dx = points[i].x - points[i-1].x;
      const dy = points[i].y - points[i-1].y;
      const mag = Math.hypot(dx, dy);
      if (mag > 1e-6) vectors.push({x: dx/mag, y: dy/mag});
    }
    for (let i = 1; i < vectors.length; i++) {
      const dot = vectors[i-1].x * vectors[i].x + vectors[i-1].y * vectors[i].y;
      if (dot < 0.2) dirChanges++;
    }
  }
  return { pathLen, netDisp, xSpan, ySpan, bboxDiag, dirChanges };
};

const ENABLE_UNKNOWN_STATE = true;

const createV2Diagnostics = () => ({
  lastLoggedAtMs: 0,
  processCount: 0,
  frontFaceMissing: 0,
  frontPoseMissing: 0,
  faceSeenFalse: 0,
  poseSeenFalse: 0,
  calibrationNotReady: 0,
  vectorReady: 0,
  vectorBlocked: 0,
  inferenceRuns: 0,
});

export function StudySession() {
  const [isRunning, setIsRunning] = useState(false);
  const [seconds, setSeconds] = useState(0);
  const [sessionId, setSessionId] = useState<number | null>(null);

  const [currentState, setCurrentState] = useState<string>("idle");
  const [debugData, setDebugData] = useState<any>({});

  const [showCameras, setShowCameras] = useState(false);
  const [showChart, setShowChart] = useState(true);
  const [showDebug, setShowDebug] = useState(false);

  const alarmEnabledRef = useRef(localStorage.getItem("focus_alarm_enabled") === "true");
  const audioCtxRef = useRef<AudioContext | null>(null);

  const playBeep = () => {
    try {
      if (!audioCtxRef.current) {
        audioCtxRef.current = new (window.AudioContext || (window as any).webkitAudioContext)();
      }
      const ctx = audioCtxRef.current;
      if (ctx.state === 'suspended') ctx.resume();

      const osc = ctx.createOscillator();
      const gain = ctx.createGain();
      osc.connect(gain);
      gain.connect(ctx.destination);
      
      osc.type = 'triangle';
      osc.frequency.setValueAtTime(600, ctx.currentTime);
      gain.gain.setValueAtTime(0.1, ctx.currentTime);
      
      osc.start();
      gain.gain.exponentialRampToValueAtTime(0.00001, ctx.currentTime + 0.3);
      osc.stop(ctx.currentTime + 0.3);
    } catch (e) {
      console.warn("Audio playback failed", e);
    }
  };

  useEffect(() => {
    if (isRunning && alarmEnabledRef.current && currentState !== "focus" && currentState !== "idle" && currentState !== "gaze_down") {
      playBeep();
    }
  }, [currentState, isRunning]);

  const timelineRef = useRef<{t: number, state: string}[]>([]);
  const inferenceIntervalId = useRef<number | null>(null);
  const startTimeRef = useRef<number | null>(null);
  
  // NATIVE AI ENGINE REFS
  const pipelineRef = useRef<FrontV2FeaturePipeline | null>(null);
  const handTrackingBufferRef = useRef<any[]>([]);
  const missingFramesRef = useRef(0);
  const stateHistoryRef = useRef<string[]>([]);
  const v2DiagnosticsRef = useRef(createV2Diagnostics());
  
  const faceVideoRef = useRef<HTMLVideoElement>(null);
  const deskVideoRef = useRef<HTMLVideoElement>(null);
  const faceCanvasRef = useRef<HTMLCanvasElement>(null);
  const deskCanvasRef = useRef<HTMLCanvasElement>(null);
  
  const animationFrameId = useRef<number | null>(null);
  const lastInferenceTime = useRef<number>(0);

  const frontFaceRef = useRef<FaceLandmarker | null>(null);
  const deskFaceRef = useRef<FaceLandmarker | null>(null);
  const frontPoseRef = useRef<PoseLandmarker | null>(null);
  const deskPoseRef = useRef<PoseLandmarker | null>(null);
  
  const [modelsLoaded, setModelsLoaded] = useState(false);
  const onnxSessionRef = useRef<ort.InferenceSession | null>(null);

  const liveChartData = useMemo(() => {
    if (!isRunning || timelineRef.current.length === 0) return [];
    const totalSecs = timelineRef.current.length;
    const bucketSize = Math.max(1, Math.floor(totalSecs / 60));

    const bucketedData = [];
    for (let i = 0; i < totalSecs; i += bucketSize) {
      const chunk = timelineRef.current.slice(i, i + bucketSize);
      const avgScore = chunk.reduce((sum, val) => sum + (STATE_WEIGHTS[val.state] ?? 100), 0) / chunk.length;
      const tIndex = chunk[chunk.length - 1].t; 
      const mins = Math.floor(tIndex / 60);
      const secs = tIndex % 60;
      bucketedData.push({
        time: `${mins}:${String(secs).padStart(2, "0")}`,
        score: Math.round(avgScore),
      });
    }
    return bucketedData;
  }, [seconds, isRunning]);
  
  useEffect(() => {
    const initModels = async () => {
      try {
        const vision = await FilesetResolver.forVisionTasks(
          "https://cdn.jsdelivr.net/npm/@mediapipe/tasks-vision@0.10.14/wasm"
        );

        const faceOptions = {
          baseOptions: {
            modelAssetPath: "/face_landmarker.task", 
            delegate: "GPU" as const,
          },
          outputFacialTransformationMatrixes: true,
          runningMode: "VIDEO" as const,
          numFaces: 1, 
        };

        const poseOptions = {
          baseOptions: {
            modelAssetPath: "/pose_landmarker_heavy.task", 
            delegate: "GPU" as const,
          },
          runningMode: "VIDEO" as const,
          numPoses: 1, 
        };

        frontFaceRef.current = await FaceLandmarker.createFromOptions(vision, faceOptions);
        deskFaceRef.current = await FaceLandmarker.createFromOptions(vision, faceOptions);
        frontPoseRef.current = await PoseLandmarker.createFromOptions(vision, poseOptions);
        deskPoseRef.current = await PoseLandmarker.createFromOptions(vision, poseOptions);

        ort.env.wasm.wasmPaths = "https://cdn.jsdelivr.net/npm/onnxruntime-web/dist/";
        
        onnxSessionRef.current = await ort.InferenceSession.create("/focus_classifier_3class_b.onnx", {
          executionProviders: ["wasm"], 
        });

        setModelsLoaded(true);
        console.log("All 4 MediaPipe Models and ONNX Loaded!");
      } catch (error) {
        console.error("Failed to load models:", error);
      }
    };

    initModels();
  }, []);

  const formatTime = (totalSeconds: number) => {
    const hours = Math.floor(totalSeconds / 3600);
    const minutes = Math.floor((totalSeconds % 3600) / 60);
    const secs = totalSeconds % 60;
    return `${hours.toString().padStart(2, "0")}:${minutes
      .toString()
      .padStart(2, "0")}:${secs.toString().padStart(2, "0")}`;
  };

  const runInference = async () => {
    animationFrameId.current = requestAnimationFrame(runInference);

    if (!faceVideoRef.current || !deskVideoRef.current) return;
    if (!faceCanvasRef.current || !deskCanvasRef.current) return;
    if (!pipelineRef.current) return;

    const faceVideo = faceVideoRef.current;
    const deskVideo = deskVideoRef.current;

    if (faceVideo.readyState < 2 || deskVideo.readyState < 2) return;
    if (!frontFaceRef.current || !frontPoseRef.current || !deskFaceRef.current || !deskPoseRef.current) return;

    try {
      const nowMs = performance.now();
      if (startTimeRef.current) {
         setSeconds(Math.floor((nowMs - startTimeRef.current) / 1000)); 
      }

      const faceCanvas = faceCanvasRef.current;
      const deskCanvas = deskCanvasRef.current;
      if (faceVideo.videoWidth > 0) {
        faceCanvas.width = faceVideo.videoWidth; faceCanvas.height = faceVideo.videoHeight;
        deskCanvas.width = deskVideo.videoWidth; deskCanvas.height = deskVideo.videoHeight;
      }

      const frontFaceRes = frontFaceRef.current.detectForVideo(faceVideo, nowMs);
      const frontPoseRes = frontPoseRef.current.detectForVideo(faceVideo, nowMs);
      const deskFaceRes = deskFaceRef.current.detectForVideo(deskVideo, nowMs);
      const deskPoseRes = deskPoseRef.current.detectForVideo(deskVideo, nowMs);

      const faceCtx = faceCanvas.getContext("2d");
      if (faceCtx) {
        faceCtx.clearRect(0, 0, faceCanvas.width, faceCanvas.height);
        if (frontFaceRes.faceLandmarks && frontFaceRes.faceLandmarks.length > 0) {
          faceCtx.fillStyle = "#38bdf8";
          const lm = frontFaceRes.faceLandmarks[0];
          for (let i = 0; i < lm.length; i += 5) {
            faceCtx.beginPath();
            faceCtx.arc(lm[i].x * faceCanvas.width, lm[i].y * faceCanvas.height, 1.2, 0, Math.PI * 2);
            faceCtx.fill();
          }
        }
      }

      const deskCtx = deskCanvas.getContext("2d");
      if (deskCtx) {
        deskCtx.clearRect(0, 0, deskCanvas.width, deskCanvas.height);
        if (deskPoseRes.landmarks && deskPoseRes.landmarks.length > 0) {
          deskCtx.strokeStyle = "#facc15";
          deskCtx.lineWidth = 2;
          const lm = deskPoseRes.landmarks[0];
          [15, 16].forEach((idx) => {
            if (lm[idx]) {
              deskCtx.beginPath();
              deskCtx.arc(lm[idx].x * deskCanvas.width, lm[idx].y * deskCanvas.height, 5, 0, Math.PI * 2);
              deskCtx.stroke();
            }
          });
        }
      }

      if (nowMs - lastInferenceTime.current >= 1000) {
        lastInferenceTime.current = nowMs;

        if (onnxSessionRef.current) {
            const frontFaceLm = frontFaceRes.faceLandmarks?.[0] ?? null;
            const frontPoseLm = frontPoseRes.landmarks?.[0] ?? null;
            const v2Diagnostics = v2DiagnosticsRef.current;
            v2Diagnostics.processCount++;
            if (frontFaceLm === null) v2Diagnostics.frontFaceMissing++;
            if (frontPoseLm === null) v2Diagnostics.frontPoseMissing++;

            // 1. GENERATE PERFECT 34-FEATURE VECTOR
            const rawMetrics = extractFrontMeasurements(frontFaceLm as any, frontPoseLm as any);
            const featureResult = pipelineRef.current.process(nowMs, rawMetrics);
            if (!rawMetrics.faceSeen) v2Diagnostics.faceSeenFalse++;
            if (!rawMetrics.poseSeen) v2Diagnostics.poseSeenFalse++;
            if (!featureResult.calibrationValid) v2Diagnostics.calibrationNotReady++;
            if (featureResult.vector) v2Diagnostics.vectorReady++;
            else v2Diagnostics.vectorBlocked++;

            // 2. ISOLATED HAND TRACKING FOR OVERHEAD ACTIVITIES
            handTrackingBufferRef.current.push({
                rightWrist: deskPoseRes.landmarks?.[0]?.[16] ?? frontPoseRes.landmarks?.[0]?.[16] ?? null,
                leftWrist: deskPoseRes.landmarks?.[0]?.[15] ?? frontPoseRes.landmarks?.[0]?.[15] ?? null,
            });
            if (handTrackingBufferRef.current.length > 10) handTrackingBufferRef.current.shift();

            let page_turn = false, pen_fidget = false, restless_hand = false;
            
            if (handTrackingBufferRef.current.length === 10) {
                const rPoints = handTrackingBufferRef.current.map(f => f.rightWrist).filter(w => w && w.visibility > 0.5);
                const lPoints = handTrackingBufferRef.current.map(f => f.leftWrist).filter(w => w && w.visibility > 0.5);

                const classifyHand = (points: any[]) => {
                    const feat = getHandFeatures(points);
                    if (!feat) return null;
                    if (feat.pathLen >= ANALYZE_CONFIG.page_turn_min_path_len &&
                        feat.netDisp >= ANALYZE_CONFIG.page_turn_min_net_disp &&
                        feat.xSpan >= ANALYZE_CONFIG.page_turn_min_x_span &&
                        feat.ySpan <= ANALYZE_CONFIG.page_turn_max_y_span &&
                        feat.dirChanges <= ANALYZE_CONFIG.page_turn_max_dir_changes) return "page_turn";
                    if (feat.pathLen >= ANALYZE_CONFIG.pen_fidget_min_path_len &&
                        feat.bboxDiag <= ANALYZE_CONFIG.pen_fidget_max_bbox_diag &&
                        feat.dirChanges >= ANALYZE_CONFIG.pen_fidget_min_dir_changes) return "pen_fidget";
                    if (feat.pathLen >= ANALYZE_CONFIG.restless_hand_min_path_len &&
                        feat.bboxDiag >= ANALYZE_CONFIG.restless_hand_min_bbox_diag &&
                        feat.dirChanges >= ANALYZE_CONFIG.restless_hand_min_dir_changes) return "restless_hand";
                    return null;
                };

                const rAction = classifyHand(rPoints);
                const lAction = classifyHand(lPoints);

                if (rAction === "page_turn" || lAction === "page_turn") page_turn = true;
                if (rAction === "pen_fidget" || lAction === "pen_fidget") pen_fidget = true;
                if (rAction === "restless_hand" || lAction === "restless_hand") restless_hand = true;

                if (page_turn || pen_fidget || restless_hand) {
                    handTrackingBufferRef.current = []; 
                }
            }

            // 3. EXECUTE MACHINE LEARNING MODEL
            let aiPrediction = "unknown";
            let aiConfidence = 0.0;

            if (featureResult.vector) {
              try {
                  const inputName = onnxSessionRef.current.inputNames[0];
                   let results;
                   try {
                       const tensor32 = new ort.Tensor("float32", featureResult.vector, [1, 34]);
                       v2Diagnostics.inferenceRuns++;
                       results = await onnxSessionRef.current.run({ [inputName]: tensor32 });
                   } catch (typeError) {
                       const features64 = new Float64Array(featureResult.vector);
                       const tensor64 = new ort.Tensor("float64", features64, [1, 34]);
                       v2Diagnostics.inferenceRuns++;
                       results = await onnxSessionRef.current.run({ [inputName]: tensor64 });
                  }
                  
                  const labelData = results[onnxSessionRef.current.outputNames[0]]?.data;
                  if (labelData && labelData.length > 0) {
                      const rawLabel = String(labelData[0]);
                      if (rawLabel.includes("focus")) aiPrediction = "focus";
                      else if (rawLabel.includes("gaze_side")) aiPrediction = "gaze_side";
                      else if (rawLabel.includes("drowsy")) aiPrediction = "drowsy";
                      else aiPrediction = rawLabel;

                      if (onnxSessionRef.current.outputNames.length > 1) {
                          const probData = results[onnxSessionRef.current.outputNames[1]]?.data;
                          if (probData) {
                              try {
                                  const probArray = Array.from(probData as any) as number[];
                                  aiConfidence = probArray.length > 0 ? Math.max(...probArray) : 0.99;
                              } catch (e) {
                                  aiConfidence = 0.99; 
                              }
                          } else {
                              aiConfidence = 0.99;
                          }
                      } else {
                          aiConfidence = 0.99;
                      }
                  }
               } catch (err) {
                   console.warn("ONNX Execution Error:", err);
               }
            }

            if (nowMs - v2Diagnostics.lastLoggedAtMs >= 10_000) {
                v2Diagnostics.lastLoggedAtMs = nowMs;
                const rate = (count: number) => Number(
                    ((count / Math.max(v2Diagnostics.processCount, 1)) * 100).toFixed(2),
                );
                console.info("[V2_DIAG]", {
                    processCount: v2Diagnostics.processCount,
                    frontFaceMissing: v2Diagnostics.frontFaceMissing,
                    frontFaceMissingRate: rate(v2Diagnostics.frontFaceMissing),
                    frontPoseMissing: v2Diagnostics.frontPoseMissing,
                    frontPoseMissingRate: rate(v2Diagnostics.frontPoseMissing),
                    faceSeenFalse: v2Diagnostics.faceSeenFalse,
                    poseSeenFalse: v2Diagnostics.poseSeenFalse,
                    calibrationNotReady: v2Diagnostics.calibrationNotReady,
                    vectorReady: v2Diagnostics.vectorReady,
                    vectorReadyRate: rate(v2Diagnostics.vectorReady),
                    vectorBlocked: v2Diagnostics.vectorBlocked,
                    vectorBlockedRate: rate(v2Diagnostics.vectorBlocked),
                    inferenceRuns: v2Diagnostics.inferenceRuns,
                    inferenceRunRate: rate(v2Diagnostics.inferenceRuns),
                });
            }

            // 4. HYBRID DECISION ENGINE
            if (!rawMetrics.faceSeen && !rawMetrics.poseSeen) missingFramesRef.current++;
            else if (!rawMetrics.faceSeen && rawMetrics.poseSeen) missingFramesRef.current++;
            else missingFramesRef.current = 0;

            const predictionObj = (aiPrediction !== "unknown" && aiPrediction !== "absent") ? { 
                state: aiPrediction as any, 
                confidence: aiConfidence 
            } : null;

            const bad_posture = (rawMetrics.shoulderSlope ?? 0) >= 0.12 || (rawMetrics.poseHeadTiltRatio ?? 0) >= 0.18;
            const gaze_down = (rawMetrics.irisYRatio ?? 0.5) >= 0.62;

            const decision = resolveHybridDecision({
                signal: {
                    personPresent: missingFramesRef.current < 5,
                    faceSeen: rawMetrics.faceSeen,
                    poseSeen: rawMetrics.poseSeen,
                    faceValidRatio: featureResult.values.face_valid_ratio ?? 0, 
                    poseValidRatio: featureResult.values.pose_valid_ratio ?? 0, 
                    calibrationValid: featureResult.calibrationValid
                },
                prediction: predictionObj,
                continuousEyeClosedSec: featureResult.values.continuous_eye_closed_sec ?? 0, 
                gazeDownRuleMatched: gaze_down || (rawMetrics.faceHeadDownRatio ?? 0) > 0.72, 
                badPosture: bad_posture,
                overheadActivity: page_turn ? "page_turn" : pen_fidget ? "pen_fidget" : restless_hand ? "restless_hand" : null
            });

            let finalState = decision.state;
            let decisionSource: string = decision.decisionSource;

            // Anti-flicker filter
            stateHistoryRef.current.push(finalState);
            if (stateHistoryRef.current.length > 5) stateHistoryRef.current.shift(); 
            
            if (!ENABLE_UNKNOWN_STATE && finalState === "unknown") {
                finalState = "focus";
                decisionSource = "unknown_state_disabled";
            }
            if (finalState !== "focus" && finalState !== "absent") { 
                const requiredSec = FILTER_CONFIG[finalState] || 1;
                if (requiredSec > 1) {
                    const recentStates = stateHistoryRef.current.slice(-requiredSec);
                    const isMaintained = recentStates.length === requiredSec && 
                                         recentStates.every(state => state === finalState);
                    if (!isMaintained) {
                        finalState = "focus";
                        decisionSource = `filtered_by_${requiredSec}sec_rule`;
                    }
                }
            }

            const predictedState = finalState;
            const currentT = startTimeRef.current ? Math.floor((nowMs - startTimeRef.current) / 1000) : 0;
            const isSleepingOnDesk = !rawMetrics.faceSeen && rawMetrics.poseSeen && finalState === "drowsy";

            const timelineEntry = {
                t: currentT,
                state: finalState,
                model_state: aiPrediction,
                model_confidence: Number(aiConfidence.toFixed(4)),
                rule_state: decision.ruleState || finalState,
                decision_source: decisionSource,
                states: [finalState],
                flags: {
                    face_seen: rawMetrics.faceSeen,
                    gaze_side: finalState === "gaze_side",
                    gaze_down: gaze_down,
                    bad_posture: bad_posture,
                    eye_closed: (featureResult.values.continuous_eye_closed_sec ?? 0) > 0,
                    blink: (featureResult.values.continuous_eye_closed_sec ?? 0) > 0, 
                    long_eye_closure: (featureResult.values.continuous_eye_closed_sec ?? 0) > 5,
                    head_down: (rawMetrics.faceHeadDownRatio ?? 0) > 0.72,
                    head_tilt: (rawMetrics.faceHeadTiltRatio ?? 0) > 0.12,
                    raw_drowsy: finalState === "drowsy" || isSleepingOnDesk,
                    drowsy: finalState === "drowsy",
                    sleep_suspect: isSleepingOnDesk,
                    page_turn: page_turn, 
                    pen_fidget: pen_fidget, 
                    restless_hand: restless_hand, 
                    unknown: finalState === "unknown",
                    absent: finalState === "absent"
                }
            };

            timelineRef.current.push(timelineEntry);
            setCurrentState(predictedState);
            
            setDebugData({
              timestamp: Date.now(),
              ai_tracking: {
                front_faces: rawMetrics.faceSeen ? 1 : 0,
                desk_faces: 0,
                front_poses: rawMetrics.poseSeen ? 1 : 0,
                desk_poses: 0
              },
              onnx_prediction: predictedState,
              timeline_length: timelineRef.current.length,
              latest_payload: timelineRef.current[timelineRef.current.length - 1] || null
            });
        }
      }
    } catch (error) {
      console.warn("AI Inference skipped a frame due to an error:", error);
    }
  };

  const handleStart = async () => {
    const userId = localStorage.getItem("user_id");
    if (!userId) {
      alert("로그인이 필요합니다.");
      return;
    }
    if (isRunning) return;

    try {
      const response = await fetch(`${import.meta.env.VITE_API_BASE_URL}/sessions/`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ user_id: parseInt(userId, 10) }),
      });

      if (!response.ok) throw new Error("세션 생성 실패");
      const data = await response.json();
      setSessionId(data.id);
      
      timelineRef.current = [];
      handTrackingBufferRef.current = [];
      missingFramesRef.current = 0;
      v2DiagnosticsRef.current = createV2Diagnostics();

      // INITIALIZE THE 34-FEATURE PIPELINE
      pipelineRef.current = new FrontV2FeaturePipeline({
        calibrationMinSamples: 5,
        calibrationWindowSamples: 30,
        temporalWindowMs: 10000,
        qualityWindowSamples: 10,
      });

      const { faceStream, deskStream } = await setupDualCameras();
      if (faceVideoRef.current) faceVideoRef.current.srcObject = faceStream;
      if (deskVideoRef.current) deskVideoRef.current.srcObject = deskStream;
      
      startTimeRef.current = performance.now();
      setIsRunning(true);
      lastInferenceTime.current = performance.now(); 
      animationFrameId.current = requestAnimationFrame(runInference);

    } catch (error) {
      console.error("Failed to start session:", error);
      alert("세션 시작에 실패했습니다.");
    }
  };

  const handleStop = async () => {
    if (!sessionId) return;

    try {
      if (inferenceIntervalId.current) clearInterval(inferenceIntervalId.current);
      
      if (faceVideoRef.current?.srcObject) {
        (faceVideoRef.current.srcObject as MediaStream).getTracks().forEach(t => t.stop());
      }
      if (deskVideoRef.current?.srcObject) {
        (deskVideoRef.current.srcObject as MediaStream).getTracks().forEach(t => t.stop());
      }
      if (animationFrameId.current) cancelAnimationFrame(animationFrameId.current);

      if (timelineRef.current.length > 0) {
        const timelineResponse = await fetch(`${import.meta.env.VITE_API_BASE_URL}/sessions/${sessionId}/timeline`, {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ timeline: timelineRef.current }), 
        });
        
        if (!timelineResponse.ok) {
            const errorData = await timelineResponse.json();
            console.error("Backend rejected the timeline:", errorData);
            throw new Error("Timeline database insertion failed");
        }
      }
      const finalDuration = startTimeRef.current 
        ? Math.floor((performance.now() - startTimeRef.current) / 1000) 
        : seconds;

      await fetch(`${import.meta.env.VITE_API_BASE_URL}/sessions/${sessionId}`, {
        method: "PATCH",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ 
            status: "completed", 
            end_time: new Date().toISOString(),
            duration_sec: finalDuration 
        }),
      });

      setIsRunning(false);
      setSeconds(0);
      setSessionId(null);
      alert("세션 종료 및 데이터 저장 성공!");
    } catch (error) {
      console.error("Pipeline error:", error);
      alert("세션 종료 중 오류가 발생했습니다.");
    }
  };

  const isDistracted = isRunning && alarmEnabledRef.current && currentState !== "focus" && currentState !== "idle" && currentState !== "gaze_down";

  return (
    <div className={`min-h-screen p-8 transition-colors duration-700 ${isDistracted ? 'bg-red-50 border-8 border-red-500/30' : 'bg-gradient-to-br from-accent/20 to-white border-8 border-transparent'}`}>
      
      {isRunning && (
        <div className="fixed right-6 top-1/2 -translate-y-1/2 bg-white/90 backdrop-blur-md rounded-2xl border border-border p-3 shadow-lg flex flex-col gap-3 z-50">
          <div className="flex items-center justify-center p-2 border-b border-border/50 mb-1">
            <Settings2 className="w-5 h-5 text-muted-foreground" />
          </div>
          
          <button 
            onClick={() => setShowCameras(!showCameras)} 
            className={`p-3 rounded-xl flex flex-col items-center gap-1.5 transition-all ${showCameras ? 'bg-primary/10 text-primary shadow-sm' : 'hover:bg-accent text-muted-foreground'}`}
            title="카메라 뷰 토글"
          >
            <Camera className="w-5 h-5" />
            <span className="text-[10px] font-bold">카메라</span>
          </button>
          
          <button 
            onClick={() => setShowChart(!showChart)} 
            className={`p-3 rounded-xl flex flex-col items-center gap-1.5 transition-all ${showChart ? 'bg-primary/10 text-primary shadow-sm' : 'hover:bg-accent text-muted-foreground'}`}
            title="실시간 차트 토글"
          >
            <TrendingUp className="w-5 h-5" />
            <span className="text-[10px] font-bold">차트</span>
          </button>
          
          <button 
            onClick={() => setShowDebug(!showDebug)} 
            className={`p-3 rounded-xl flex flex-col items-center gap-1.5 transition-all ${showDebug ? 'bg-slate-800 text-emerald-400 shadow-sm' : 'hover:bg-accent text-muted-foreground'}`}
            title="AI 디버그 모드 토글"
          >
            <Activity className="w-5 h-5" />
            <span className="text-[10px] font-bold">디버그</span>
          </button>
        </div>
      )}
      
      <div className="max-w-4xl mx-auto">
        <h1 className="text-3xl font-bold text-foreground mb-8">학습 세션</h1>

        <div className={`flex gap-4 mb-6 ${(!isRunning || !showCameras) ? 'hidden' : ''}`}>
          
          <div className="w-1/2 relative rounded-xl overflow-hidden border-2 border-primary/20 bg-black shadow-sm">
             <span className="absolute top-2 left-2 bg-black/60 text-white text-xs px-2 py-1 rounded z-10">얼굴 캠</span>
             <video ref={faceVideoRef} autoPlay playsInline muted className="w-full transform scale-x-[-1]" />
             <canvas ref={faceCanvasRef} className="absolute inset-0 w-full h-full transform scale-x-[-1] pointer-events-none" />
          </div>

          <div className="w-1/2 relative rounded-xl overflow-hidden border-2 border-primary/20 bg-black shadow-sm">
             <span className="absolute top-2 left-2 bg-black/60 text-white text-xs px-2 py-1 rounded z-10">책상 캠</span>
             <video ref={deskVideoRef} autoPlay playsInline muted className="w-full" />
             <canvas ref={deskCanvasRef} className="absolute inset-0 w-full h-full pointer-events-none" />
          </div>
          
        </div>

        <div className="bg-white rounded-2xl border border-border p-12 mb-6 text-center shadow-lg">
          {!isRunning ? (
            <div className="space-y-6">
              <div className="w-24 h-24 bg-accent rounded-full flex items-center justify-center mx-auto mb-4">
                <Play className="w-12 h-12 text-primary" />
              </div>
              <h2 className="text-2xl font-semibold text-foreground">
                학습을 시작할 준비가 되셨나요?
              </h2>
              <button
                onClick={handleStart}
                className="px-8 py-4 bg-primary text-primary-foreground rounded-lg hover:bg-primary/90 transition-colors text-lg"
              >
                세션 시작
              </button>
            </div>
          ) : (
            <div className="space-y-8">
              <div>
                <div className="text-7xl font-bold text-primary mb-4 font-mono">
                  {formatTime(seconds)}
                </div>
              </div>

              <button
                onClick={handleStop}
                className="flex items-center gap-2 px-6 py-3 bg-destructive text-destructive-foreground rounded-lg hover:bg-destructive/90 transition-colors mx-auto"
              >
                <Square className="w-5 h-5" />
                <span>세션 종료</span>
              </button>
            </div>
          )}
        </div>

        {isRunning && showChart && liveChartData.length > 0 && (
          <details className="p-6 bg-white rounded-xl border border-border text-left mb-6 group cursor-pointer shadow-sm" open>
            <summary className="font-semibold text-foreground flex items-center gap-2 outline-none">
              <TrendingUp className="w-5 h-5 text-primary" />
              실시간 집중도 분석
              <span className="ml-auto text-xs text-muted-foreground group-open:hidden">클릭하여 펼치기</span>
            </summary>
            
            <div className="mt-6 pt-4 border-t border-border cursor-default" onClick={(e) => e.preventDefault()}>
              <ResponsiveContainer width="100%" height={250}>
                <AreaChart data={liveChartData}>
                  <defs>
                    <linearGradient id="liveFocusGradient" x1="0" y1="0" x2="0" y2="1">
                      <stop offset="5%" stopColor="#1a667a" stopOpacity={0.3} />
                      <stop offset="95%" stopColor="#1a667a" stopOpacity={0} />
                    </linearGradient>
                  </defs>
                  <CartesianGrid strokeDasharray="3 3" stroke="#f0f0f0" />
                  <XAxis dataKey="time" stroke="#888" fontSize={12} tickLine={false} dy={10} />
                  <YAxis stroke="#888" fontSize={12} domain={[0, 100]} ticks={[0, 25, 50, 75, 100]} tickLine={false} dx={-5} />
                  <Tooltip 
                    contentStyle={{ backgroundColor: "#fff", border: "1px solid #e5e5e5", borderRadius: "8px" }} 
                    formatter={(value: number) => [`${value}%`, "집중도"]} 
                  />
                  <Area type="monotone" dataKey="score" stroke="#1a667a" strokeWidth={3} fillOpacity={1} fill="url(#liveFocusGradient)" isAnimationActive={false} />
                </AreaChart>
              </ResponsiveContainer> 
            </div>
          </details>
        )}

        {isRunning && showDebug && (
          <details className="p-6 bg-slate-900 rounded-xl border border-slate-700 text-left mb-6 group cursor-pointer">
            <summary className="font-semibold text-slate-300 flex items-center gap-2 outline-none">
              <Activity className="w-5 h-5 text-emerald-400" />
              AI Model Debug Data
              <span className="ml-auto text-xs opacity-50 group-open:hidden">Click to expand</span>
            </summary>
            <div className="mt-4 pt-4 border-t border-slate-700">
              <pre className="text-xs text-emerald-400 font-mono overflow-x-auto">
                {JSON.stringify(debugData, null, 2)}
              </pre>
            </div>
          </details>
        )}

        <div className="p-6 bg-accent/30 rounded-xl border border-primary/20">
          <h3 className="font-semibold mb-3 text-primary">학습 팁</h3>
          <ul className="space-y-2 text-sm text-muted-foreground">
            <li>• 50분 학습 후 5-10분 휴식을 취하세요</li>
            <li>• 수분을 충분히 섭취하고 바른 자세를 유지하세요</li>
          </ul> 
        </div>
      </div>
    </div>
  );
}
