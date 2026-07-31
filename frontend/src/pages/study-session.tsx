import { useState, useEffect, useRef, useMemo } from "react";
import { Play, Square, Activity, TrendingUp, Camera, Settings2 } from "lucide-react";
import { setupDualCameras } from "@/utils/dualCamManager"; 
import { FaceLandmarker, PoseLandmarker, FilesetResolver } from "@mediapipe/tasks-vision";
import * as ort from "onnxruntime-web";
import {
  AreaChart, Area, XAxis, YAxis, CartesianGrid, Tooltip, ResponsiveContainer
} from "recharts";

// Add the State Weights for the Real-Time Chart
const STATE_WEIGHTS: Record<string, number> = {
  "focus": 100, "bad_posture": 60, "gaze_away": 40, "gaze_side": 40,
  "gaze_down": 40, "unknown": 50, "present_unknown": 50,
  "drowsy": 20, "sleep_suspect": 20, "absent": 0,
};

const FILTER_CONFIG: Record<string, number> = {
  gaze_side: 2,
  gaze_down: 2,
  bad_posture: 2,
  absent: 4,
};

// EXACT PARITY CONFIG (Matched to analyze.py)
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

  ear_baseline_ratio: 0.58,
  ear_reopen_baseline_ratio: 0.72,
  drowsy_ear_threshold: 0.16,
  drowsy_ear_reopen_threshold: 0.20,
  face_head_down_threshold: 0.72,
  face_head_down_offset: 0.10,
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

export function StudySession() {
  const [isRunning, setIsRunning] = useState(false);
  const [seconds, setSeconds] = useState(0);
  const [sessionId, setSessionId] = useState<number | null>(null);

  const [currentState, setCurrentState] = useState<string>("idle");
  const [debugData, setDebugData] = useState<any>({});

  // --- NEW: UI Toggle States ---
  const [showCameras, setShowCameras] = useState(true);
  const [showChart, setShowChart] = useState(true);
  const [showDebug, setShowDebug] = useState(false);

  // NEW: Read the alarm setting and prepare an Audio Context
  const alarmEnabledRef = useRef(localStorage.getItem("focus_alarm_enabled") === "true");
  const audioCtxRef = useRef<AudioContext | null>(null);

  // NEW: A zero-dependency function to synthesize a system beep
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
      osc.frequency.setValueAtTime(600, ctx.currentTime); // Pitch
      gain.gain.setValueAtTime(0.1, ctx.currentTime); // Volume
      
      osc.start();
      gain.gain.exponentialRampToValueAtTime(0.00001, ctx.currentTime + 0.3);
      osc.stop(ctx.currentTime + 0.3);
    } catch (e) {
      console.warn("Audio playback failed", e);
    }
  };

  // NEW: Monitor state changes and fire the alarm!
  useEffect(() => {
    if (isRunning && alarmEnabledRef.current && currentState !== "focus" && currentState !== "idle") {
      playBeep();
    }
  }, [currentState, isRunning]);

  // Array to hold the timeline data for the database
  const timelineRef = useRef<{t: number, state: string}[]>([]);
  
  // 10-second sliding window for temporal AI features (like drowsiness)
  const temporalBufferRef = useRef<any[]>([]);
  const inferenceIntervalId = useRef<number | null>(null);

  const startTimeRef = useRef<number | null>(null);

  // Update the types to accept the new exact-parity variables
  const calibrationBufferRef = useRef<{
    ear: number; 
    rEar: number; 
    lEar: number; 
    headDown: number; 
    eyeWidth: number;
  }[]>([]);

  // Start with system defaults so inference can begin immediately
  const personalThresholdsRef = useRef<{
    ear: number; rClose: number; rReopen: number; 
    lClose: number; lReopen: number; headDown: number; eyeWidth: number;
  }>({
    ear: 0.25,
    rClose: ANALYZE_CONFIG.drowsy_ear_threshold,
    rReopen: ANALYZE_CONFIG.drowsy_ear_reopen_threshold,
    lClose: ANALYZE_CONFIG.drowsy_ear_threshold,
    lReopen: ANALYZE_CONFIG.drowsy_ear_reopen_threshold,
    headDown: ANALYZE_CONFIG.face_head_down_threshold,
    eyeWidth: 9999 // Safely high default so posture fallback doesn't false-trigger early
  });
  
  // Tracks the current state of each eye to prevent flickering (Hysteresis)
  const eyeStateRef = useRef({ rightClosed: false, leftClosed: false });

  //2. 히스토리 저장용 Ref(Ref for saving history)
  const stateHistoryRef = useRef<string[]>([]);
  // ----------------------------------------- 여기까지 추가
  
  // Refs for our video elements
  const faceVideoRef = useRef<HTMLVideoElement>(null);
  const deskVideoRef = useRef<HTMLVideoElement>(null);

  // Canvas refs for drawing the landmarks
  const faceCanvasRef = useRef<HTMLCanvasElement>(null);
  const deskCanvasRef = useRef<HTMLCanvasElement>(null);
  
  // Replace inferenceIntervalId with an animation frame ID and a timestamp tracker
  const animationFrameId = useRef<number | null>(null);
  const lastInferenceTime = useRef<number>(0);

  const frontFaceRef = useRef<FaceLandmarker | null>(null);
  const frontPoseRef = useRef<PoseLandmarker | null>(null);
  const deskFaceRef = useRef<FaceLandmarker | null>(null);
  const deskPoseRef = useRef<PoseLandmarker | null>(null);
  const [modelsLoaded, setModelsLoaded] = useState(false);

  // ONNX Model Ref
  const onnxSessionRef = useRef<ort.InferenceSession | null>(null);

  // NEW: Real-time chart data processor
  const liveChartData = useMemo(() => {
    if (!isRunning || timelineRef.current.length === 0) return [];
    
    const totalSecs = timelineRef.current.length;
    // Cap the graph at 60 data points to ensure it remains highly performant during long sessions
    const bucketSize = Math.max(1, Math.floor(totalSecs / 60));

    const bucketedData = [];
    for (let i = 0; i < totalSecs; i += bucketSize) {
      const chunk = timelineRef.current.slice(i, i + bucketSize);
      // Calculate average score for this time bucket
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
  
  // Load MediaPipe models on component mount
  useEffect(() => {
    const initModels = async () => {
      try {
        const vision = await FilesetResolver.forVisionTasks(
          "https://cdn.jsdelivr.net/npm/@mediapipe/tasks-vision@0.10.14/wasm"
        );

        const faceOptions = {
          baseOptions: {
            modelAssetPath: "/face_landmarker.task", // Full Local Face Model
            delegate: "GPU" as const,
          },
          outputFacialTransformationMatrixes: true,
          runningMode: "VIDEO" as const,
          numFaces: 1,
        };

        const poseOptions = {
          baseOptions: {
            modelAssetPath: "/pose_landmarker.task", // Full Local Pose Model
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
        onnxSessionRef.current = await ort.InferenceSession.create("/focus_classifier.onnx", {
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

    const faceVideo = faceVideoRef.current;
    const deskVideo = deskVideoRef.current;

    if (faceVideo.readyState < 2 || deskVideo.readyState < 2) return;

    // Use the 4 new independent models!
    if (!frontFaceRef.current || !frontPoseRef.current || !deskFaceRef.current || !deskPoseRef.current) return;

    try {
      const nowMs = performance.now();

      if (startTimeRef.current) {
         const elapsedRealSeconds = Math.floor((nowMs - startTimeRef.current) / 1000);
         // React will automatically ignore this if the second hasn't actually changed
         setSeconds(elapsedRealSeconds); 
      }

      const faceCanvas = faceCanvasRef.current;
      const deskCanvas = deskCanvasRef.current;

      if (faceVideo.videoWidth > 0) {
        faceCanvas.width = faceVideo.videoWidth; faceCanvas.height = faceVideo.videoHeight;
        deskCanvas.width = deskVideo.videoWidth; deskCanvas.height = deskVideo.videoHeight;
      }

      // 1. Run all 4 independent trackers
      const frontFaceRes = frontFaceRef.current.detectForVideo(faceVideo, nowMs);
      const frontPoseRes = frontPoseRef.current.detectForVideo(faceVideo, nowMs);
      const deskFaceRes = deskFaceRef.current.detectForVideo(deskVideo, nowMs);
      const deskPoseRes = deskPoseRef.current.detectForVideo(deskVideo, nowMs);

      // 2. Draw Face Landmarks (Cyan) using the Front Camera data
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

      // 3. Draw Posture Landmarks (Yellow wrists) using the Desk Camera data
      const deskCtx = deskCanvas.getContext("2d");
      if (deskCtx) {
        deskCtx.clearRect(0, 0, deskCanvas.width, deskCanvas.height);
        if (deskPoseRes.landmarks && deskPoseRes.landmarks.length > 0) {
          const lm = deskPoseRes.landmarks[0];
          deskCtx.strokeStyle = "#facc15";
          deskCtx.lineWidth = 2;
          
          [15, 16].forEach((idx) => {
            if (lm[idx]) {
              deskCtx.beginPath();
              deskCtx.arc(lm[idx].x * deskCanvas.width, lm[idx].y * deskCanvas.height, 5, 0, Math.PI * 2);
              deskCtx.stroke();
            }
          });
        }
      }

      // Throttled Database & ONNX Logic (1 FPS)
      if (nowMs - lastInferenceTime.current >= 1000) {
        lastInferenceTime.current = nowMs;
        let predictedState = "focus";

        if (onnxSessionRef.current) {
            const features = new Float32Array(16);
            features[0] = 1.0; features[1] = 1.0; 
            
            let face_seen = 0, gaze_side = 0, gaze_down = 0, bad_posture = 0;
            let eye_closed = 0, blink = 0, long_eye_closure = 0, head_down = 0, head_tilt = 0, drowsy = 0;
            let page_turn = 0, pen_fidget = 0, restless_hand = 0;

            // =====================================
            // FALLBACK ROUTING ENGINE
            // =====================================
            // Prefer Front Cam for Face, fallback to Desk Cam (e.g. sleeping on desk)
            const bestFaceLm = (frontFaceRes.faceLandmarks && frontFaceRes.faceLandmarks.length > 0) 
                ? frontFaceRes.faceLandmarks[0] 
                : ((deskFaceRes.faceLandmarks && deskFaceRes.faceLandmarks.length > 0) ? deskFaceRes.faceLandmarks[0] : null);

            // Prefer Front Cam for Shoulders (Posture), fallback to Desk
            const bestShoulderLm = (frontPoseRes.landmarks && frontPoseRes.landmarks.length > 0)
                ? frontPoseRes.landmarks[0]
                : ((deskPoseRes.landmarks && deskPoseRes.landmarks.length > 0) ? deskPoseRes.landmarks[0] : null);

            // Prefer Desk Cam for Wrists (Fidgeting), fallback to Front
            const bestWristLm = (deskPoseRes.landmarks && deskPoseRes.landmarks.length > 0)
                ? deskPoseRes.landmarks[0]
                : ((frontPoseRes.landmarks && frontPoseRes.landmarks.length > 0) ? frontPoseRes.landmarks[0] : null);
            // =====================================
            
            // --- FACE MATH ---
            if (bestFaceLm) {
                face_seen = 1.0;
                const getDist = (p1: number, p2: number) => Math.hypot(bestFaceLm[p1].x - bestFaceLm[p2].x, bestFaceLm[p1].y - bestFaceLm[p2].y);
                
                const rightEar = (getDist(159, 145) + getDist(158, 153)) / (2.0 * getDist(33, 133) + 1e-6);
                const leftEar = (getDist(386, 374) + getDist(385, 380)) / (2.0 * getDist(362, 263) + 1e-6);
                
                const currentEar = (rightEar + leftEar) / 2.0;
                const eyeMidY = (bestFaceLm[33].y + bestFaceLm[263].y) / 2.0;
                const faceHeight = bestFaceLm[152].y - eyeMidY;
                const currentHeadDown = faceHeight > 1e-6 ? ((bestFaceLm[1].y - eyeMidY) / faceHeight) : 0;
                
                // Declare eyeWidth here so it's accessible to both FACE MATH and POSE MATH
                const currentEyeWidth = Math.abs(bestFaceLm[263].x - bestFaceLm[33].x);

                // --- CALIBRATION LOGIC (Silent Background Refinement) ---
            if (calibrationBufferRef.current.length < 30) {
                if (currentEar > 0.10) {
                    calibrationBufferRef.current.push({ 
                        ear: currentEar, 
                        rEar: rightEar, 
                        lEar: leftEar, 
                        headDown: currentHeadDown, 
                        eyeWidth: currentEyeWidth 
                    });
                }

                // Continuously refine the baseline if we have at least a few valid frames
                if (calibrationBufferRef.current.length >= 5) {
                    const getBaseline = (vals: number[]) => {
                        const valid = vals.filter(v => v > 0).sort((a, b) => a - b);
                        if (!valid.length) return 0.25;
                        const upperCount = Math.max(1, Math.round(valid.length * 0.35));
                        const upperThird = valid.slice(-upperCount);
                        const mid = Math.floor(upperThird.length / 2);
                        return upperThird.length % 2 !== 0 ? upperThird[mid] : (upperThird[mid - 1] + upperThird[mid]) / 2.0;
                    };

                    const rBase = getBaseline(calibrationBufferRef.current.map(v => v.rEar || v.ear));
                    const lBase = getBaseline(calibrationBufferRef.current.map(v => v.lEar || v.ear));
                    const avgHeadDown = calibrationBufferRef.current.reduce((acc, val) => acc + val.headDown, 0) / calibrationBufferRef.current.length;
                    const avgEyeWidth = calibrationBufferRef.current.reduce((acc, val) => acc + val.eyeWidth, 0) / calibrationBufferRef.current.length;

                    let rClose = Math.min(ANALYZE_CONFIG.drowsy_ear_threshold, rBase * ANALYZE_CONFIG.ear_baseline_ratio);
                    let rReopen = Math.min(ANALYZE_CONFIG.drowsy_ear_reopen_threshold, rBase * ANALYZE_CONFIG.ear_reopen_baseline_ratio);
                    rReopen = Math.max(rReopen, rClose + 0.01);

                    let lClose = Math.min(ANALYZE_CONFIG.drowsy_ear_threshold, lBase * ANALYZE_CONFIG.ear_baseline_ratio);
                    let lReopen = Math.min(ANALYZE_CONFIG.drowsy_ear_reopen_threshold, lBase * ANALYZE_CONFIG.ear_reopen_baseline_ratio);
                    lReopen = Math.max(lReopen, lClose + 0.01);

                    personalThresholdsRef.current = {
                        ear: (rBase + lBase) / 2,
                        rClose, rReopen, lClose, lReopen,
                        headDown: Math.max(ANALYZE_CONFIG.face_head_down_threshold, avgHeadDown + ANALYZE_CONFIG.face_head_down_offset),
                        eyeWidth: avgEyeWidth * 1.25
                    };
                }
            }

                // --- HYSTERESIS EVALUATION ---
                if (personalThresholdsRef.current) {
                    const tRef = personalThresholdsRef.current;
                    
                    if (eyeStateRef.current.rightClosed) eyeStateRef.current.rightClosed = rightEar < tRef.rReopen;
                    else eyeStateRef.current.rightClosed = rightEar <= tRef.rClose;
                    
                    if (eyeStateRef.current.leftClosed) eyeStateRef.current.leftClosed = leftEar < tRef.lReopen;
                    else eyeStateRef.current.leftClosed = leftEar <= tRef.lClose;

                    if (eyeStateRef.current.rightClosed && eyeStateRef.current.leftClosed) {
                        eye_closed = 1.0; blink = 1.0;
                    }
                    if (currentHeadDown >= tRef.headDown) {
                        head_down = 1.0;
                    }
                }

                if (bestFaceLm.length > 473) {
                    const getRatioX = (iris: number, c1: number, c2: number) => {
                        const minX = Math.min(bestFaceLm[c1].x, bestFaceLm[c2].x);
                        const maxX = Math.max(bestFaceLm[c1].x, bestFaceLm[c2].x);
                        return (bestFaceLm[iris].x - minX) / (maxX - minX + 1e-6);
                    };
                    const getRatioY = (iris: number, c1: number, c2: number) => {
                        const minY = Math.min(bestFaceLm[c1].y, bestFaceLm[c2].y);
                        const maxY = Math.max(bestFaceLm[c1].y, bestFaceLm[c2].y);
                        return (bestFaceLm[iris].y - minY) / (maxY - minY + 1e-6);
                    };

                    const avgX = (getRatioX(468, 33, 133) + getRatioX(473, 362, 263)) / 2.0;
                    const avgY = (getRatioY(468, 159, 145) + getRatioY(473, 386, 374)) / 2.0;

                    if (avgX <= 0.35 || avgX >= 0.65) gaze_side = 1.0;
                    if (avgY >= 0.62) gaze_down = 1.0;
                }
                
                // Use the globally scoped currentEyeWidth here
                if (currentEyeWidth > 1e-6 && (Math.abs(bestFaceLm[33].y - bestFaceLm[263].y) / currentEyeWidth >= 0.12)) head_tilt = 1.0;
            } 
                
            
            // --- POSE MATH ---
            // If shoulders are visible with decent confidence, use standard vector math
            if (bestShoulderLm && bestShoulderLm[11] && bestShoulderLm[11].visibility > 0.5) {
                const shoulderWidth = Math.abs(bestShoulderLm[12].x - bestShoulderLm[11].x);
                const shoulderMidX = (bestShoulderLm[11].x + bestShoulderLm[12].x) / 2.0;
                
                if (Math.abs(bestShoulderLm[11].y - bestShoulderLm[12].y) >= 0.12) bad_posture = 1.0;
                if (shoulderWidth > 1e-6 && Math.abs(bestShoulderLm[0].x - shoulderMidX) / shoulderWidth >= 0.18) bad_posture = 1.0;
            } else if (bestFaceLm && personalThresholdsRef.current) {
                // FALLBACK: Head-only posture tracking when body is hidden
                const fallbackEyeWidth = Math.abs(bestFaceLm[263].x - bestFaceLm[33].x);
                
                // 1. Turtle Neck: Face is significantly closer to the screen than baseline
                if (fallbackEyeWidth >= personalThresholdsRef.current.eyeWidth) {
                    bad_posture = 1.0;
                }
                // 2. Severe Slouch: Eyes are heavily tilted off the horizontal axis
                if (fallbackEyeWidth > 1e-6 && (Math.abs(bestFaceLm[33].y - bestFaceLm[263].y) / fallbackEyeWidth >= 0.15)) {
                    bad_posture = 1.0;
                }
            }

            // --- TEMPORAL MATH ---
            temporalBufferRef.current.push({
                eye_closed: eye_closed === 1.0,
                rightWrist: bestWristLm && bestWristLm[16] ? { 
                    x: bestWristLm[16].x, y: bestWristLm[16].y, visibility: bestWristLm[16].visibility || 1.0 
                } : null,
                leftWrist: bestWristLm && bestWristLm[15] ? { 
                    x: bestWristLm[15].x, y: bestWristLm[15].y, visibility: bestWristLm[15].visibility || 1.0 
                } : null
            });
            if (temporalBufferRef.current.length > 10) temporalBufferRef.current.shift();

            if (temporalBufferRef.current.length === 10) {
                if (temporalBufferRef.current.every((frame: any) => frame.eye_closed)) long_eye_closure = 1.0;
                
                // Extract valid frames for each hand
                const rPoints = temporalBufferRef.current.map(f => f.rightWrist).filter(w => w && w.visibility > 0.5);
                const lPoints = temporalBufferRef.current.map(f => f.leftWrist).filter(w => w && w.visibility > 0.5);

                const classifyHand = (points: {x: number, y: number}[]) => {
                    const features = getHandFeatures(points);
                    if (!features) return null;
                    
                    if (features.pathLen >= ANALYZE_CONFIG.page_turn_min_path_len &&
                        features.netDisp >= ANALYZE_CONFIG.page_turn_min_net_disp &&
                        features.xSpan >= ANALYZE_CONFIG.page_turn_min_x_span &&
                        features.ySpan <= ANALYZE_CONFIG.page_turn_max_y_span &&
                        features.dirChanges <= ANALYZE_CONFIG.page_turn_max_dir_changes) return "page_turn";
                        
                    if (features.pathLen >= ANALYZE_CONFIG.pen_fidget_min_path_len &&
                        features.bboxDiag <= ANALYZE_CONFIG.pen_fidget_max_bbox_diag &&
                        features.dirChanges >= ANALYZE_CONFIG.pen_fidget_min_dir_changes) return "pen_fidget";
                        
                    if (features.pathLen >= ANALYZE_CONFIG.restless_hand_min_path_len &&
                        features.bboxDiag >= ANALYZE_CONFIG.restless_hand_min_bbox_diag &&
                        features.dirChanges >= ANALYZE_CONFIG.restless_hand_min_dir_changes) return "restless_hand";
                        
                    return null;
                };

                const rAction = classifyHand(rPoints);
                const lAction = classifyHand(lPoints);

                if (rAction === "page_turn" || lAction === "page_turn") page_turn = 1.0;
                if (rAction === "pen_fidget" || lAction === "pen_fidget") pen_fidget = 1.0;
                if (rAction === "restless_hand" || lAction === "restless_hand") restless_hand = 1.0;

                if (page_turn || pen_fidget || restless_hand) {
                    temporalBufferRef.current = []; // Flush buffer to prevent action echoing
                }
             }
            // Map the calculated flags into the exact tensor array
            features[2] = face_seen;
            features[3] = gaze_side;
            features[4] = gaze_down;
            features[5] = bad_posture;
            features[6] = eye_closed;
            features[7] = blink;
            features[8] = long_eye_closure; 
            features[9] = head_down;
            features[10] = head_tilt;
            features[11] = (long_eye_closure && head_down) ? 1.0 : 0.0; // Drowsy proxy
            features[12] = page_turn; // page_turn (Requires temporal history buffer)
            features[13] = pen_fidget; // pen_fidget (Requires temporal history buffer)
            features[14] = restless_hand; // restless_hand (Requires temporal history buffer)
            features[15] = 0.0; // unknown

            try {
                // Create the [1, 16] Tensor
                const tensor = new ort.Tensor("float32", features, [1, 16]);
                
                const inputName = onnxSessionRef.current.inputNames[0];
                const feeds = { [inputName]: tensor };
                
                // Run the edge AI!
                const results = await onnxSessionRef.current.run(feeds);
                
                // 1. Extract ONNX Outputs
                const labelData = results[onnxSessionRef.current.outputNames[0]].data;
                const probData = results[onnxSessionRef.current.outputNames[1]].data;
                
                let aiPrediction = "unknown";
                let aiConfidence = 0.0;
                
                if (labelData && labelData.length > 0) {
                    aiPrediction = String(labelData[0]);
                    // Explicitly cast to Float32Array so TypeScript knows these are numbers
                    const probabilities = probData as Float32Array;
                    aiConfidence = Math.max(...probabilities); 
                }

                // 2. Apply Rule-Based Overrides (matching analyze.py logic)
                let finalState = aiPrediction;
                let decisionSource = "model";

                // Check if we see a body even if the face is hidden
                const pose_seen = (bestShoulderLm || bestWristLm) ? 1.0 : 0.0;

                if (face_seen === 0.0 && pose_seen === 0.0) {
                    finalState = "absent";
                    decisionSource = "rule_absent";
                } else if (face_seen === 0.0 && pose_seen === 1.0) {
                    finalState = "unknown"; 
                    decisionSource = "rule_face_hidden";
                } else if (long_eye_closure === 1.0) {
                    // NEW: Expose Drowsiness to the UI
                    finalState = "drowsy";
                    decisionSource = "rule_drowsy";
                } else if (bad_posture === 1.0 && aiPrediction !== "gaze_side" && aiPrediction !== "gaze_down") {
                    finalState = "bad_posture";
                    decisionSource = "rule_bad_posture";
                } else if (page_turn === 1.0) {
                    // NEW: Expose Hand Actions to the UI
                    finalState = "page_turn";
                    decisionSource = "rule_hand_action";
                } else if (pen_fidget === 1.0) {
                    // NEW: Expose Hand Actions to the UI
                    finalState = "pen_fidget";
                    decisionSource = "rule_hand_action";
                } else if (restless_hand === 1.0) {
                    // NEW: Expose Hand Actions to the UI
                    finalState = "restless_hand";
                    decisionSource = "rule_hand_action";
                } else if (aiConfidence < 0.65) { 
                    finalState = "unknown";
                    decisionSource = "rule";
                }

                // 분석 로직 수정(Modifying Analysis Logic)
                stateHistoryRef.current.push(finalState);
                
                if (stateHistoryRef.current.length > 5) {
                    stateHistoryRef.current.shift(); 
                }
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
                // ----------------------------------------- 여기까지 추가

                predictedState = finalState;

                // 3. Format the JSON payload exactly like analyze.py
                const currentT = startTimeRef.current ? Math.floor((nowMs - startTimeRef.current) / 1000) : 0;
                const timelineEntry = {
                    t: currentT,
                    state: finalState,
                    model_state: aiPrediction,
                    model_confidence: Number(aiConfidence.toFixed(4)),
                    rule_state: finalState,
                    decision_source: decisionSource,
                    states: [finalState],
                    flags: {
                        face_seen: Boolean(face_seen),
                        gaze_side: Boolean(gaze_side),
                        gaze_down: Boolean(gaze_down),
                        bad_posture: Boolean(bad_posture),
                        eye_closed: Boolean(eye_closed),
                        blink: Boolean(blink),
                        long_eye_closure: Boolean(long_eye_closure),
                        head_down: Boolean(head_down),
                        head_tilt: Boolean(head_tilt),
                        raw_drowsy: Boolean(drowsy),
                        drowsy: Boolean(drowsy),
                        page_turn: Boolean(page_turn), 
                        pen_fidget: Boolean(pen_fidget), 
                        restless_hand: Boolean(restless_hand), 
                        unknown: finalState === "unknown",
                        absent: finalState === "absent"
                    }
                };

                // Push the perfectly formatted JSON to the timeline array
                timelineRef.current.push(timelineEntry);

            } catch (err) {
                console.error("ONNX Inference Detailed Error:", err);
            }
        }
            
            setCurrentState(predictedState);
            setDebugData({
              timestamp: Date.now(),
              ai_tracking: {
                front_faces: frontFaceRes.faceLandmarks ? frontFaceRes.faceLandmarks.length : 0,
                desk_faces: deskFaceRes.faceLandmarks ? deskFaceRes.faceLandmarks.length : 0,
                front_poses: frontPoseRes.landmarks ? frontPoseRes.landmarks.length : 0,
                desk_poses: deskPoseRes.landmarks ? deskPoseRes.landmarks.length : 0
              },
              onnx_prediction: predictedState,
              timeline_length: timelineRef.current.length,
              // FIX: Grab the last item pushed to the array to avoid scope errors!
              latest_payload: timelineRef.current[timelineRef.current.length - 1] || null
            });
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
      
      // Reset timeline array for a new session
      timelineRef.current = [];
      calibrationBufferRef.current = [];
      personalThresholdsRef.current = {
        ear: 0.25,
        rClose: ANALYZE_CONFIG.drowsy_ear_threshold,
        rReopen: ANALYZE_CONFIG.drowsy_ear_reopen_threshold,
        lClose: ANALYZE_CONFIG.drowsy_ear_threshold,
        lReopen: ANALYZE_CONFIG.drowsy_ear_reopen_threshold,
        headDown: ANALYZE_CONFIG.face_head_down_threshold,
        eyeWidth: 9999 
      };

      const { faceStream, deskStream } = await setupDualCameras();
      if (faceVideoRef.current) faceVideoRef.current.srcObject = faceStream;
      if (deskVideoRef.current) deskVideoRef.current.srcObject = deskStream;
      
      startTimeRef.current = performance.now();
      setIsRunning(true);
      lastInferenceTime.current = performance.now(); // Reset timer
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

      // Step 1: Upload the FULL timeline (with flags!) so the backend AI scripts can generate feedback
      if (timelineRef.current.length > 0) {
        const timelineResponse = await fetch(`${import.meta.env.VITE_API_BASE_URL}/sessions/${sessionId}/timeline`, {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ timeline: timelineRef.current }), // Send the full rich array
        });
        
        if (!timelineResponse.ok) {
            const errorData = await timelineResponse.json();
            console.error("Backend rejected the timeline:", errorData);
            throw new Error("Timeline database insertion failed");
        }
      }
      // Calculate the exact final real-world duration
      const finalDuration = startTimeRef.current 
        ? Math.floor((performance.now() - startTimeRef.current) / 1000) 
        : seconds;

      // Step 2: Mark the session as completed SECOND to trigger the SQS worker.
      await fetch(`${import.meta.env.VITE_API_BASE_URL}/sessions/${sessionId}`, {
        method: "PATCH",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ 
            status: "completed", 
            end_time: new Date().toISOString(),
            duration_sec: finalDuration // Pass the real-world time
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

  // NEW: Determine if we should currently be flashing red
  const isDistracted = isRunning && alarmEnabledRef.current && currentState !== "focus" && currentState !== "idle";

  return (
    // FIX: Replaced the static wrapper with a dynamic one
    <div className={`min-h-screen p-8 transition-colors duration-700 ${isDistracted ? 'bg-red-50 border-8 border-red-500/30' : 'bg-gradient-to-br from-accent/20 to-white border-8 border-transparent'}`}>
      
      {/* --- NEW: FLOATING CONTROL PANEL --- */}
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

        {/* Re-styled Camera Preview Elements */}
        <div className={`flex gap-4 mb-6 ${(!isRunning || !showCameras) ? 'hidden' : ''}`}>
          
          {/* FACE CAM */}
          <div className="w-1/2 relative rounded-xl overflow-hidden border-2 border-primary/20 bg-black shadow-sm">
             <span className="absolute top-2 left-2 bg-black/60 text-white text-xs px-2 py-1 rounded z-10">얼굴 캠</span>
             <video ref={faceVideoRef} autoPlay playsInline muted className="w-full transform scale-x-[-1]" />
             {/* The canvas sits directly on top of the video */}
             <canvas ref={faceCanvasRef} className="absolute inset-0 w-full h-full transform scale-x-[-1] pointer-events-none" />
          </div>

          {/* DESK CAM */}
          <div className="w-1/2 relative rounded-xl overflow-hidden border-2 border-primary/20 bg-black shadow-sm">
             <span className="absolute top-2 left-2 bg-black/60 text-white text-xs px-2 py-1 rounded z-10">책상 캠</span>
             <video ref={deskVideoRef} autoPlay playsInline muted className="w-full" />
             <canvas ref={deskCanvasRef} className="absolute inset-0 w-full h-full pointer-events-none" />
          </div>
          
        </div>

        {/* ... (The rest of the UI remains identical) ... */}

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

        {/* --- NEW: REAL-TIME FOCUS CHART DROPDOWN --- */}
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

        {/* --- NEW: DEBUG DROPDOWN FOR AI MODEL --- */}
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
