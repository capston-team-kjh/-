import { useState, useEffect, useRef } from "react";
import { Play, Square, Activity } from "lucide-react";
import { setupDualCameras } from "@/utils/dualCamManager"; 
import { FaceLandmarker, PoseLandmarker, FilesetResolver } from "@mediapipe/tasks-vision";
import * as ort from "onnxruntime-web";
import { ProductionDecision, toTimelinePoint, validateFeatures, validateProbabilities, MODEL_CLASSES, MODEL_SHA256 } from "@/ai/production-decision.mjs";

export function StudySession() {
  const [isRunning, setIsRunning] = useState(false);
  const [seconds, setSeconds] = useState(0);
  const [sessionId, setSessionId] = useState<number | null>(null);
  
  const [currentState, setCurrentState] = useState<string>("idle");
  const [debugData, setDebugData] = useState<any>({});
  const decisionRef = useRef(new ProductionDecision());
  const [calibrating, setCalibrating] = useState(true);
  const [modelWarning, setModelWarning] = useState("");
  
  // NEW: Array to hold the timeline data for the database
  const timelineRef = useRef<{t: number, state: string}[]>([]);
  
  // NEW: 10-second sliding window for temporal AI features (like drowsiness)
  const temporalBufferRef = useRef<any[]>([]);
  const inferenceIntervalId = useRef<number | null>(null);
  
  // Refs for our video elements
  const faceVideoRef = useRef<HTMLVideoElement>(null);
  const deskVideoRef = useRef<HTMLVideoElement>(null);

  // NEW: Canvas refs for drawing the landmarks
  const faceCanvasRef = useRef<HTMLCanvasElement>(null);
  const deskCanvasRef = useRef<HTMLCanvasElement>(null);
  
  // Replace inferenceIntervalId with an animation frame ID and a timestamp tracker
  const animationFrameId = useRef<number | null>(null);
  const lastInferenceTime = useRef<number>(0);
  const inferenceBusy = useRef(false);
  const lastFrontFrameTime = useRef(-1);

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

        try {
          ort.env.wasm.wasmPaths = "https://cdn.jsdelivr.net/npm/onnxruntime-web@1.27.0/dist/";
          const response = await fetch("/focus_classifier.onnx");
          if (!response.ok) throw new Error("Model fetch failed");
          const bytes = await response.arrayBuffer();
          const digest = await crypto.subtle.digest("SHA-256", bytes);
          const hash = Array.from(new Uint8Array(digest), x => x.toString(16).padStart(2, "0")).join("");
          if (hash !== MODEL_SHA256) throw new Error("Production model hash mismatch");
          const session = await ort.InferenceSession.create(bytes, { executionProviders: ["wasm"] });
          if (session.inputNames.join() !== "float_input" || session.outputNames.join() !== "label,probabilities") {
            await session.release();
            throw new Error("Production model IO mismatch");
          }
          onnxSessionRef.current = session;
        } catch (error) {
          console.error("ONNX unavailable; MediaPipe decisions remain active", error);
          setModelWarning("AI 모델을 불러오지 못했습니다. 카메라 규칙으로만 판정합니다.");
        }

        setModelsLoaded(true);
        console.log("MediaPipe ready; ONNX available:", Boolean(onnxSessionRef.current));
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
    if (inferenceBusy.current) return;

    if (!faceVideoRef.current || !deskVideoRef.current) return;
    if (!faceCanvasRef.current || !deskCanvasRef.current) return;

    const faceVideo = faceVideoRef.current;
    const deskVideo = deskVideoRef.current;

    if (faceVideo.readyState < 2 || deskVideo.readyState < 2) return;

    // Use the 4 new independent models!
    if (!frontFaceRef.current || !frontPoseRef.current || !deskFaceRef.current || !deskPoseRef.current) return;

    try {
      const nowMs = performance.now();
      if (nowMs - lastInferenceTime.current < 1000) return;
      const frontTrack = (faceVideo.srcObject as MediaStream | null)?.getVideoTracks()[0];
      const freshFront = frontTrack?.readyState === "live" && !frontTrack.muted
        && faceVideo.currentTime > lastFrontFrameTime.current;
      lastFrontFrameTime.current = faceVideo.currentTime;
      const faceCanvas = faceCanvasRef.current;
      const deskCanvas = deskCanvasRef.current;

      if (faceVideo.videoWidth > 0) {
        faceCanvas.width = faceVideo.videoWidth; faceCanvas.height = faceVideo.videoHeight;
        deskCanvas.width = deskVideo.videoWidth; deskCanvas.height = deskVideo.videoHeight;
      }

      // 1. Run all 4 independent trackers
      const frontFaceRes = freshFront ? frontFaceRef.current.detectForVideo(faceVideo, nowMs) : { faceLandmarks: [] };
      const frontPoseRes = freshFront ? frontPoseRef.current.detectForVideo(faceVideo, nowMs) : { landmarks: [] };
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
        if (nowMs - lastInferenceTime.current > 1500) temporalBufferRef.current = [];
        inferenceBusy.current = true;
        try {
        lastInferenceTime.current = nowMs;
        let predictedState = "unknown";
        let diagnostics: any = {};

        {
            const features = new Float32Array(16);
            features[0] = 1.0; features[1] = 1.0; 
            
            let face_seen = 0, gaze_side = 0, gaze_down = 0, bad_posture = 0;
            let eye_closed = 0, blink = 0, long_eye_closure = 0, head_down = 0, head_tilt = 0, drowsy = 0;
            let page_turn = 0, pen_fidget = 0, restless_hand = 0;
            let measuredEar = NaN, measuredIrisY = NaN, measuredHead = NaN;

            // =====================================
            // FALLBACK ROUTING ENGINE
            // =====================================
            // Front camera exclusively supplies face, iris, and head evidence.
            const bestFaceLm = (frontFaceRes.faceLandmarks && frontFaceRes.faceLandmarks.length > 0) 
                ? frontFaceRes.faceLandmarks[0] 
                : null;

            // Front camera exclusively supplies posture evidence.
            const bestShoulderLm = (frontPoseRes.landmarks && frontPoseRes.landmarks.length > 0)
                ? frontPoseRes.landmarks[0]
                : null;

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
                measuredEar = (rightEar + leftEar) / 2;
                
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
                    measuredIrisY = avgY;

                    // Matches AnalyzeConfig: gaze_side_left_threshold = 0.35, gaze_side_right_threshold = 0.65
                    if (avgX <= 0.35 || avgX >= 0.65) gaze_side = 1.0;
                    // Matches AnalyzeConfig: gaze_down_threshold = 0.62
                    if (avgY >= 0.62) gaze_down = 1.0;
                }
                
                const eyeMidY = (bestFaceLm[33].y + bestFaceLm[263].y) / 2.0;
                const faceHeight = bestFaceLm[152].y - eyeMidY;
                const eyeWidth = Math.abs(bestFaceLm[263].x - bestFaceLm[33].x);
                measuredHead = faceHeight > 1e-6 ? (bestFaceLm[1].y - eyeMidY) / faceHeight : NaN;
                
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
                    const netDisp = first && last ? Math.hypot(last.x - first.x, last.y - first.y) : 0;
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
                let probabilities: Float32Array | null = null;
                if (onnxSessionRef.current && [measuredEar, measuredIrisY, measuredHead].every(Number.isFinite)) {
                  try {
                    validateFeatures(features);
                    const results = await onnxSessionRef.current.run({float_input: new ort.Tensor("float32", features, [1,16])});
                    const output = results.probabilities;
                    if (output.type !== "float32" || output.dims.join() !== "1,5" || results.label.type !== "string" || results.label.dims.join() !== "1")
                      throw new Error("Invalid ONNX output contract");
                    const values = output.data as Float32Array;
                    validateProbabilities(values);
                    if (String(results.label.data[0]) !== MODEL_CLASSES[Array.from(values).indexOf(Math.max(...values))])
                      throw new Error("Class order mismatch");
                    probabilities = values;
                  } catch (error) {
                    console.error("ONNX contract/inference failed", error);
                    setModelWarning("AI 추론을 사용할 수 없어 카메라 규칙으로 판정합니다.");
                  }
                }
                const decision = decisionRef.current.step(nowMs, {
                  faceSeen: Boolean(face_seen),
                  personSeen: Boolean(face_seen || frontPoseRes.landmarks?.length || deskPoseRes.landmarks?.length || deskFaceRes.faceLandmarks?.length),
                  ear: measuredEar, irisY: measuredIrisY, head: measuredHead,
                  badPosture: Boolean(bad_posture), pageTurn: Boolean(page_turn),
                  penFidget: Boolean(pen_fidget), restlessHand: Boolean(restless_hand)
                }, probabilities);
                predictedState = decision.final_state;
                diagnostics = decision;
                setCalibrating(!decision.calibration_valid);
                timelineRef.current.push(toTimelinePoint(timelineRef.current.length + 1, decision));

            } catch (err) {
                console.error("ONNX Inference Detailed Error:", err);
            }
        }
            
            setCurrentState(predictedState);
            setDebugData({
              ...diagnostics,
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
        } finally { inferenceBusy.current = false; }
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
    if (!modelsLoaded) { alert("카메라 분석 도구를 불러오는 중입니다."); return; }

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
      temporalBufferRef.current = [];
      decisionRef.current.reset();
      lastFrontFrameTime.current = -1;
      setCalibrating(true);

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
      if (inferenceBusy.current) { alert("판정 처리 중입니다. 잠시 후 종료를 다시 눌러 주세요."); return; }
      if (inferenceIntervalId.current) clearInterval(inferenceIntervalId.current);
      
      if (faceVideoRef.current?.srcObject) {
        (faceVideoRef.current.srcObject as MediaStream).getTracks().forEach(t => t.stop());
      }
      if (deskVideoRef.current?.srcObject) {
        (deskVideoRef.current.srcObject as MediaStream).getTracks().forEach(t => t.stop());
      }
      if (animationFrameId.current) cancelAnimationFrame(animationFrameId.current);

      // 1. End the session in `focus_sessions`
      const endResponse = await fetch(`${import.meta.env.VITE_API_BASE_URL}/sessions/${sessionId}`, {
        method: "PATCH",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ status: "completed", end_time: new Date().toISOString() }),
      });
      if (!endResponse.ok) throw new Error("세션 종료 저장 실패");

      // 2. NEW: Bulk upload our accumulated timeline data to `analysis_timeline`
      if (timelineRef.current.length > 0) {
        const timelineResponse = await fetch(`${import.meta.env.VITE_API_BASE_URL}/sessions/${sessionId}/timeline`, {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ timeline: timelineRef.current }),
        });
        if (!timelineResponse.ok) throw new Error("타임라인 저장 실패");
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
        {modelWarning && <p role="status">{modelWarning}</p>}
        {isRunning && calibrating && <p role="status">개인 기준을 맞추고 있습니다. 눈을 뜨고 정면 카메라를 약 5초 동안 바라봐 주세요.</p>}

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
