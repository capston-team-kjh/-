import { useState, useEffect, useRef } from "react";
import { Play, Square, Activity } from "lucide-react";
import { setupDualCameras } from "@/utils/dualCamManager"; 
import { FaceLandmarker, PoseLandmarker, FilesetResolver } from "@mediapipe/tasks-vision";
import * as ort from "onnxruntime-web";

// 상태 최소 지속 시간(초/State minimum duration in seconds)
const SPLICING_INTERVAL_SECONDS = 300;
const FILTER_CONFIG: Record<string, number> = {
  gaze_side: 2,
  gaze_down: 2,
  bad_posture: 2,
};
const ENABLE_UNKNOWN_STATE = true;
// ----------------------------------------- 여기까지 추가

export function StudySession() {
  const [isRunning, setIsRunning] = useState(false);
  const [seconds, setSeconds] = useState(0);
  const [sessionId, setSessionId] = useState<number | null>(null);
  
  const [currentState, setCurrentState] = useState<string>("idle");
  const [debugData, setDebugData] = useState<any>({});
  
  // NEW: Array to hold the timeline data for the database
  const timelineRef = useRef<{t: number, state: string}[]>([]);
  
  // NEW: 10-second sliding window for temporal AI features (like drowsiness)
  const temporalBufferRef = useRef<any[]>([]);
  const inferenceIntervalId = useRef<number | null>(null);
  
  //2. 히스토리 저장용 Ref(Ref for saving history)
  const stateHistoryRef = useRef<string[]>([]);
  // ----------------------------------------- 여기까지 추가
  
  // Refs for our video elements
  const faceVideoRef = useRef<HTMLVideoElement>(null);
  const deskVideoRef = useRef<HTMLVideoElement>(null);

  // NEW: Canvas refs for drawing the landmarks
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

  // NEW: ONNX Model Ref
  const onnxSessionRef = useRef<ort.InferenceSession | null>(null);

  // NEW: Load MediaPipe models on component mount
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

  useEffect(() => {
    let interval: number | undefined;
    if (isRunning) {
      interval = window.setInterval(() => {
        setSeconds((s) => s + 1);
      }, 1000);
    }
    return () => clearInterval(interval);
  }, [isRunning]);

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
                
                // Matches AnalyzeConfig: drowsy_ear_threshold = 0.16
                if (((rightEar + leftEar) / 2.0) <= 0.16) { 
                    eye_closed = 1.0; blink = 1.0; 
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

                    // Matches AnalyzeConfig: gaze_side_left_threshold = 0.35, gaze_side_right_threshold = 0.65
                    if (avgX <= 0.35 || avgX >= 0.65) gaze_side = 1.0;
                    // Matches AnalyzeConfig: gaze_down_threshold = 0.62
                    if (avgY >= 0.62) gaze_down = 1.0;
                }
                
                const eyeMidY = (bestFaceLm[33].y + bestFaceLm[263].y) / 2.0;
                const faceHeight = bestFaceLm[152].y - eyeMidY;
                const eyeWidth = Math.abs(bestFaceLm[263].x - bestFaceLm[33].x);
                
                // Matches AnalyzeConfig: face_head_down_threshold = 0.72
                if (faceHeight > 1e-6 && ((bestFaceLm[1].y - eyeMidY) / faceHeight >= 0.72)) head_down = 1.0;
                // Matches AnalyzeConfig: drowsy_head_tilt_threshold = 0.12
                if (eyeWidth > 1e-6 && (Math.abs(bestFaceLm[33].y - bestFaceLm[263].y) / eyeWidth >= 0.12)) head_tilt = 1.0;
            }
            
            // --- POSE MATH ---
            if (bestShoulderLm) {
                const shoulderWidth = Math.abs(bestShoulderLm[12].x - bestShoulderLm[11].x);
                const shoulderMidX = (bestShoulderLm[11].x + bestShoulderLm[12].x) / 2.0;
                
                // Matches AnalyzeConfig: posture_shoulder_threshold = 0.12
                if (Math.abs(bestShoulderLm[11].y - bestShoulderLm[12].y) >= 0.12) bad_posture = 1.0;
                // Matches AnalyzeConfig: posture_tilt_threshold = 0.18
                if (shoulderWidth > 1e-6 && Math.abs(bestShoulderLm[0].x - shoulderMidX) / shoulderWidth >= 0.18) bad_posture = 1.0;
            }

            // --- TEMPORAL MATH ---
            temporalBufferRef.current.push({
                eye_closed: eye_closed === 1.0,
                rightWrist: bestWristLm && bestWristLm[16] ? { x: bestWristLm[16].x, y: bestWristLm[16].y } : null
            });
            if (temporalBufferRef.current.length > 10) temporalBufferRef.current.shift();

            if (temporalBufferRef.current.length === 10) {
                if (temporalBufferRef.current.every((frame: any) => frame.eye_closed)) long_eye_closure = 1.0;
                
                let totalPathLen = 0.0;
                let validFrames = 0;
                const xs: number[] = []; const ys: number[] = [];
                const vectors: {x: number, y: number}[] = [];
                
                for (let i = 1; i < temporalBufferRef.current.length; i++) {
                    const prev = temporalBufferRef.current[i-1].rightWrist;
                    const curr = temporalBufferRef.current[i].rightWrist;
                    if (prev && curr) {
                        const dx = curr.x - prev.x;
                        const dy = curr.y - prev.y;
                        const mag = Math.hypot(dx, dy);
                        
                        totalPathLen += mag;
                        xs.push(curr.x); ys.push(curr.y);
                        
                        // Exact python dot-product vector tracking for direction changes
                        if (mag > 1e-6) vectors.push({ x: dx / mag, y: dy / mag });
                        validFrames++;
                    }
                }

                if (validFrames >= 7) {
                    const first = temporalBufferRef.current[0].rightWrist || temporalBufferRef.current[1].rightWrist;
                    const last = temporalBufferRef.current[9].rightWrist;
                    const netDisp = Math.hypot(last.x - first.x, last.y - first.y);
                    const xSpan = Math.max(...xs) - Math.min(...xs);
                    const ySpan = Math.max(...ys) - Math.min(...ys);
                    const bboxDiag = Math.hypot(xSpan, ySpan);
                    
                    let dirChanges = 0;
                    for (let i = 1; i < vectors.length; i++) {
                        const dot = (vectors[i-1].x * vectors[i].x) + (vectors[i-1].y * vectors[i].y);
                        if (dot < 0.2) dirChanges++;
                    }
                    
                    // Matches AnalyzeConfig Exact Thresholds
                    if (totalPathLen >= 0.18 && netDisp >= 0.14 && xSpan >= 0.12 && ySpan <= 0.10 && dirChanges <= 2) {
                        page_turn = 1.0; 
                    } 
                    else if (totalPathLen >= 0.18 && bboxDiag <= 0.12 && dirChanges >= 3) {
                        pen_fidget = 1.0; 
                    } 
                    else if (totalPathLen >= 0.28 && bboxDiag >= 0.18 && dirChanges >= 2) {
                        restless_hand = 1.0; 
                    }
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
                } else if (bad_posture === 1.0 && aiPrediction !== "gaze_side" && aiPrediction !== "gaze_down") {
                    // FIX: Only enforce the posture penalty if the AI doesn't detect you looking away
                    finalState = "bad_posture";
                    decisionSource = "rule_bad_posture";
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
                const currentT = timelineRef.current.length + 1;
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
              timeline_length: timelineRef.current.length
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

      const { faceStream, deskStream } = await setupDualCameras();
      if (faceVideoRef.current) faceVideoRef.current.srcObject = faceStream;
      if (deskVideoRef.current) deskVideoRef.current.srcObject = deskStream;

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

      // 1. End the session in `focus_sessions`
      await fetch(`${import.meta.env.VITE_API_BASE_URL}/sessions/${sessionId}`, {
        method: "PATCH",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ status: "completed", end_time: new Date().toISOString() }),
      });

      // 2. NEW: Bulk upload our accumulated timeline data to `analysis_timeline`
      if (timelineRef.current.length > 0) {
        await fetch(`${import.meta.env.VITE_API_BASE_URL}/sessions/${sessionId}/timeline`, {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ timeline: timelineRef.current }),
        });
      }

      setIsRunning(false);
      setSeconds(0);
      setSessionId(null);
      alert("세션 종료 및 데이터 저장 성공!");
    } catch (error) {
      console.error("Pipeline error:", error);
      alert("세션 종료 중 오류가 발생했습니다.");
    }
  };

  return (
    <div className="min-h-screen bg-gradient-to-br from-accent/20 to-white p-8">
      <div className="max-w-4xl mx-auto">
        <h1 className="text-3xl font-bold text-foreground mb-8">학습 세션</h1>

        {/* Re-styled Camera Preview Elements */}
        <div className={`flex gap-4 mb-6 ${!isRunning ? 'hidden' : ''}`}>
          
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
                <div className="text-xl font-medium text-muted-foreground">
                  현재 상태: <span className="font-bold text-primary">{currentState.toUpperCase()}</span>
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

        {/* --- NEW: DEBUG DROPDOWN FOR AI MODEL --- */}
        {isRunning && (
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
