import { useState, useEffect, useRef } from "react";
import { Play, Square, Activity } from "lucide-react";
import { setupDualCameras } from "@/utils/dualCamManager"; 
import { FaceLandmarker, PoseLandmarker, FilesetResolver } from "@mediapipe/tasks-vision";
import * as ort from "onnxruntime-web";

export function StudySession() {
  const [isRunning, setIsRunning] = useState(false);
  const [seconds, setSeconds] = useState(0);
  const [sessionId, setSessionId] = useState<number | null>(null);
  
  const [currentState, setCurrentState] = useState<string>("idle");
  const [debugData, setDebugData] = useState<any>({});
  
  // NEW: Array to hold the timeline data for the database
  const timelineRef = useRef<{t: number, state: string}[]>([]);
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

  // NEW: MediaPipe Model Refs
  const faceLandmarkerRef = useRef<FaceLandmarker | null>(null);
  const poseLandmarkerRef = useRef<PoseLandmarker | null>(null);
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

        faceLandmarkerRef.current = await FaceLandmarker.createFromOptions(vision, {
          baseOptions: {
            modelAssetPath: "https://storage.googleapis.com/mediapipe-models/face_landmarker/face_landmarker/float16/1/face_landmarker.task",
            delegate: "GPU",
          },
          outputFacialTransformationMatrixes: true,
          runningMode: "VIDEO",
          numFaces: 1,
        });

        poseLandmarkerRef.current = await PoseLandmarker.createFromOptions(vision, {
          baseOptions: {
            modelAssetPath: "https://storage.googleapis.com/mediapipe-models/pose_landmarker/pose_landmarker_lite/float16/1/pose_landmarker_lite.task",
            delegate: "GPU",
          },
          runningMode: "VIDEO",
          numPoses: 1,
        });
        // Load the ONNX model from your public folder
        // Make sure your focus_classifier.onnx is inside the public/ directory!
        onnxSessionRef.current = await ort.InferenceSession.create("/focus_classifier.onnx", {
          executionProviders: ["wasm"], 
        });

        setModelsLoaded(true);
        console.log("MediaPipe and ONNX Models Loaded!");
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
    // 1. IMMEDIATELY schedule the next frame at the very top!
    // This ensures that even if we hit a 'return' statement below, the loop never dies.
    animationFrameId.current = requestAnimationFrame(runInference);

    if (!faceVideoRef.current || !deskVideoRef.current) return;
    if (!faceLandmarkerRef.current || !poseLandmarkerRef.current) return;
    if (!faceCanvasRef.current || !deskCanvasRef.current) return;

    const faceVideo = faceVideoRef.current;
    const deskVideo = deskVideoRef.current;

    // 2. NEW: Wait until the webcams actually have pixel data
    // readyState >= 2 means 'HAVE_CURRENT_DATA'
    if (faceVideo.readyState < 2 || deskVideo.readyState < 2) return;

    // 3. Wrap the AI execution in a try-catch so internal MediaPipe errors don't crash React
    try {
      const nowMs = performance.now();
      const faceCanvas = faceCanvasRef.current;
      const deskCanvas = deskCanvasRef.current;

      // Sync canvas internal resolution with the video resolution
      if (faceVideo.videoWidth > 0) {
        faceCanvas.width = faceVideo.videoWidth;
        faceCanvas.height = faceVideo.videoHeight;
        deskCanvas.width = deskVideo.videoWidth;
        deskCanvas.height = deskVideo.videoHeight;
      }

      // Run MediaPipe Perception
      const faceResult = faceLandmarkerRef.current.detectForVideo(faceVideo, nowMs);
      const poseResult = poseLandmarkerRef.current.detectForVideo(deskVideo, nowMs);

      // Draw Face Landmarks (Cyan)
      const faceCtx = faceCanvas.getContext("2d");
      if (faceCtx) {
        faceCtx.clearRect(0, 0, faceCanvas.width, faceCanvas.height);
        if (faceResult.faceLandmarks && faceResult.faceLandmarks.length > 0) {
          faceCtx.fillStyle = "#38bdf8";
          const lm = faceResult.faceLandmarks[0];
          for (let i = 0; i < lm.length; i += 5) {
            faceCtx.beginPath();
            faceCtx.arc(lm[i].x * faceCanvas.width, lm[i].y * faceCanvas.height, 1.2, 0, Math.PI * 2);
            faceCtx.fill();
          }
        }
      }

      // Draw Posture Landmarks (Yellow wrists)
      const deskCtx = deskCanvas.getContext("2d");
      if (deskCtx) {
        deskCtx.clearRect(0, 0, deskCanvas.width, deskCanvas.height);
        if (poseResult.landmarks && poseResult.landmarks.length > 0) {
          const lm = poseResult.landmarks[0];
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
            
            // 1 & 2: Camera Flags (Assuming both are active)
            features[0] = 1.0; 
            features[1] = 1.0; 
            
            let face_seen = 0, gaze_side = 0, gaze_down = 0, bad_posture = 0;
            let eye_closed = 0, blink = 0, long_eye_closure = 0, head_down = 0, head_tilt = 0, drowsy = 0;
            
            // --- FACE MATH ---
            if (faceResult.faceLandmarks && faceResult.faceLandmarks.length > 0) {
                face_seen = 1.0;
                const lm = faceResult.faceLandmarks[0];
                
                // Helper to calculate distance between two landmarks
                const getDist = (p1: number, p2: number) => Math.hypot(lm[p1].x - lm[p2].x, lm[p1].y - lm[p2].y);
                
                // EAR (Eye Aspect Ratio) Calculation
                const rightEar = (getDist(159, 145) + getDist(158, 153)) / (2.0 * getDist(33, 133) + 1e-6);
                const leftEar = (getDist(386, 374) + getDist(385, 380)) / (2.0 * getDist(362, 263) + 1e-6);
                const avgEar = (rightEar + leftEar) / 2.0;
                
                if (avgEar < 0.16) { 
                    eye_closed = 1.0; 
                    blink = 1.0; 
                }
                
                // Head Pitch (Down) Calculation
                const nose = lm[1], chin = lm[152], leftEye = lm[33], rightEye = lm[263];
                const eyeMidY = (leftEye.y + rightEye.y) / 2.0;
                const faceHeight = chin.y - eyeMidY;
                if (faceHeight > 1e-6) {
                   const headDownRatio = (nose.y - eyeMidY) / faceHeight;
                   if (headDownRatio > 0.72) head_down = 1.0;
                }
            }
            
            // --- POSE MATH ---
            if (poseResult.landmarks && poseResult.landmarks.length > 0) {
                const pLm = poseResult.landmarks[0];
                const leftShoulder = pLm[11], rightShoulder = pLm[12];
                
                // Bad Posture (Shoulder Slope) Calculation
                const shoulderSlope = Math.abs(leftShoulder.y - rightShoulder.y);
                if (shoulderSlope > 0.12) bad_posture = 1.0;
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
            features[12] = 0.0; // page_turn (Requires temporal history buffer)
            features[13] = 0.0; // pen_fidget (Requires temporal history buffer)
            features[14] = 0.0; // restless_hand (Requires temporal history buffer)
            features[15] = 0.0; // unknown

            try {
                // Create the [1, 16] Tensor
                const tensor = new ort.Tensor("float32", features, [1, 16]);
                
                // Fetch the dynamic input name ONNX assigned to your model
                const inputName = onnxSessionRef.current.inputNames[0];
                const feeds = { [inputName]: tensor };
                
                // Run the edge AI!
                const results = await onnxSessionRef.current.run(feeds);
                
                // DEBUG: Print available output names to your browser console to inspect them
                console.log("ONNX Outputs:", results);

                // Scikit-learn to ONNX models often output label strings in outputNames[0] 
                // and probabilities/scores in outputNames[1]
                const outputName = onnxSessionRef.current.outputNames[0];
                const outputData = results[outputName].data;

                if (outputData && outputData.length > 0) {
                    predictedState = String(outputData[0]);
                }
                
            } catch (err) {
                console.error("ONNX Inference Detailed Error:", err);
            }
        }

        setCurrentState(predictedState);
        setDebugData({
          timestamp: Date.now(),
          ai_tracking: {
            faces: faceResult.faceLandmarks ? faceResult.faceLandmarks.length : 0,
            poses: poseResult.landmarks ? poseResult.landmarks.length : 0
          },
          onnx_prediction: predictedState
        });

        const currentT = timelineRef.current.length + 1;
        timelineRef.current.push({
          t: currentT,
          state: predictedState
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