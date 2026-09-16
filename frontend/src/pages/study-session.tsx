import { useState, useEffect, useRef, useMemo } from "react";
import { Play, Square, Activity, TrendingUp, Camera, Settings2 } from "lucide-react";
import { setupDualCameras } from "@/utils/dualCamManager"; 
import { FaceLandmarker, PoseLandmarker, FilesetResolver } from "@mediapipe/tasks-vision";
import * as ort from "onnxruntime-web";
import {
  AreaChart, Area, XAxis, YAxis, CartesianGrid, Tooltip, ResponsiveContainer
} from "recharts";

import {
  ProductionDecision,
  toTimelinePoint,
  validateFeatures,
  validateProbabilities,
  MODEL_CLASSES,
  MODEL_SHA256,
} from "@/ai/production-decision.mjs";

// FIX: Bumped gaze_down to 100 so reading a book is recorded as focused studying!
const STATE_WEIGHTS: Record<string, number> = {
  focus: 100,
  gaze_down: 100,
  page_turn: 100,
  bad_posture: 60,
  pen_fidget: 80,
  unknown: 75,
  present_unknown: 75,
  gaze_away: 40,
  gaze_side: 40,
  restless_hand: 100,
  drowsy: 20,
  sleep_suspect: 20,
  absent: 0,
};

const NON_DISTRACTING_STATES = new Set(["focus", "gaze_down", "page_turn", "pen_fidget", "restless_hand", "idle"]);

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
    if (isRunning && alarmEnabledRef.current && !NON_DISTRACTING_STATES.has(currentState)) {
      playBeep();
    }
  }, [currentState, isRunning]);

  const timelineRef = useRef<{t: number, state: string}[]>([]);
  const inferenceIntervalId = useRef<number | null>(null);
  const startTimeRef = useRef<number | null>(null);
  
  // Production 16-feature inference state
  const decisionRef = useRef(new ProductionDecision());
  const temporalBufferRef = useRef<any[]>([]);
  const lastDeskWristRef = useRef<{ x: number; y: number; t: number } | null>(null);
  const deskWristMovingUntilRef = useRef(0);
  const inferenceBusy = useRef(false);
  const lastFrontFrameTime = useRef(-1);
  const [calibrating, setCalibrating] = useState(true);
  const [modelWarning, setModelWarning] = useState("");
  const [usingDeskFallback, setUsingDeskFallback] = useState(false);
  
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
      const avgScore = chunk.reduce((sum, val) => sum + (STATE_WEIGHTS[val.state] ?? 50), 0) / chunk.length;
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
            modelAssetPath: "/pose_landmarker.task", 
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
          const hash = Array.from(new Uint8Array(digest), (value) =>
            value.toString(16).padStart(2, "0")
          ).join("");
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
    if (!frontFaceRef.current || !frontPoseRef.current || !deskFaceRef.current || !deskPoseRef.current) return;

    try {
      const nowMs = performance.now();
      if (startTimeRef.current) {
        setSeconds(Math.floor((nowMs - startTimeRef.current) / 1000));
      }
      if (nowMs - lastInferenceTime.current < 1000) return;

      const frontTrack = (faceVideo.srcObject as MediaStream | null)?.getVideoTracks()[0];
      const freshFront = Boolean(
        frontTrack?.readyState === "live" &&
        !frontTrack.muted &&
        faceVideo.currentTime > lastFrontFrameTime.current
      );
      lastFrontFrameTime.current = faceVideo.currentTime;

      const faceCanvas = faceCanvasRef.current;
      const deskCanvas = deskCanvasRef.current;
      if (faceVideo.videoWidth > 0) {
        faceCanvas.width = faceVideo.videoWidth;
        faceCanvas.height = faceVideo.videoHeight;
      }
      if (deskVideo.videoWidth > 0) {
        deskCanvas.width = deskVideo.videoWidth;
        deskCanvas.height = deskVideo.videoHeight;
      }

      const frontFaceRes = freshFront
        ? frontFaceRef.current.detectForVideo(faceVideo, nowMs)
        : { faceLandmarks: [] };
      const frontPoseRes = freshFront
        ? frontPoseRef.current.detectForVideo(faceVideo, nowMs)
        : { landmarks: [] };
      const deskFaceRes = deskFaceRef.current.detectForVideo(deskVideo, nowMs);
      const deskPoseRes = deskPoseRef.current.detectForVideo(deskVideo, nowMs);

      const faceCtx = faceCanvas.getContext("2d");
      if (faceCtx) {
        faceCtx.clearRect(0, 0, faceCanvas.width, faceCanvas.height);
        if (frontFaceRes.faceLandmarks && frontFaceRes.faceLandmarks.length > 0) {
          faceCtx.fillStyle = "#22d3ee";
          for (const landmark of frontFaceRes.faceLandmarks[0]) {
            faceCtx.beginPath();
            faceCtx.arc(landmark.x * faceCanvas.width, landmark.y * faceCanvas.height, 1.5, 0, Math.PI * 2);
            faceCtx.fill();
          }
        }
      }

      const deskCtx = deskCanvas.getContext("2d");
      if (deskCtx) {
        deskCtx.clearRect(0, 0, deskCanvas.width, deskCanvas.height);
        if (deskPoseRes.landmarks && deskPoseRes.landmarks.length > 0) {
          const landmarks = deskPoseRes.landmarks[0];
          deskCtx.strokeStyle = "#facc15";
          deskCtx.lineWidth = 2;
          [15, 16].forEach((index) => {
            if (!landmarks[index]) return;
            deskCtx.beginPath();
            deskCtx.arc(landmarks[index].x * deskCanvas.width, landmarks[index].y * deskCanvas.height, 5, 0, Math.PI * 2);
            deskCtx.stroke();
          });
        }
      }

      if (nowMs - lastInferenceTime.current > 1500) {
        temporalBufferRef.current = [];
      }
      lastInferenceTime.current = nowMs;
      inferenceBusy.current = true;

      try {
        const features = new Float32Array(16);
        features[0] = 1.0; // is_front_camera
        features[1] = 1.0; // is_overhead_camera

        let faceSeen = 0;
        let gazeSide = 0;
        let gazeDown = 0;
        let badPosture = 0;
        let eyeClosed = 0;
        let blink = 0;
        let longEyeClosure = 0;
        let headDown = 0;
        let headTilt = 0;
        let pageTurn = 0;
        let penFidget = 0;
        let restlessHand = 0;
        let measuredEar = Number.NaN;
        let measuredIrisY = Number.NaN;
        let measuredHead = Number.NaN;

        // Front camera is authoritative for face, gaze, head, and posture.
        const bestFaceLm = frontFaceRes.faceLandmarks?.[0] ?? null;
        const bestShoulderLm = frontPoseRes.landmarks?.[0] ?? null;

        // Desk camera is preferred for hand activity; front pose is fallback only.
        const bestWristLm = deskPoseRes.landmarks?.[0] ?? frontPoseRes.landmarks?.[0] ?? null;

        // Fast desk-activity fallback for periods where the front camera loses the face.
        // The normal hand-state rules below use a ~10-second window; this lightweight
        // check reacts within one analysis sample so writing can still count as active
        // study while the user's head is low/out of the front-camera face detector.
        let deskWristMoving = false;
        const deskRightWrist = deskPoseRes.landmarks?.[0]?.[16] ?? null;
        if (deskRightWrist) {
          const previousDeskWrist = lastDeskWristRef.current;
          if (previousDeskWrist) {
            const wristDisplacement = Math.hypot(
              deskRightWrist.x - previousDeskWrist.x,
              deskRightWrist.y - previousDeskWrist.y
            );
            if (wristDisplacement >= 0.01) {
              deskWristMoving = true;
              // Keep a short grace period because browser inference runs ~1 Hz.
              deskWristMovingUntilRef.current = nowMs + 2500;
            }
          }
          lastDeskWristRef.current = {
            x: deskRightWrist.x,
            y: deskRightWrist.y,
            t: nowMs,
          };
        } else {
          lastDeskWristRef.current = null;
        }

        if (nowMs < deskWristMovingUntilRef.current) {
          deskWristMoving = true;
        }

        if (bestFaceLm) {
          faceSeen = 1;
          const distance = (a: number, b: number) =>
            Math.hypot(bestFaceLm[a].x - bestFaceLm[b].x, bestFaceLm[a].y - bestFaceLm[b].y);

          const rightEar = (distance(159, 145) + distance(158, 153)) / (2 * distance(33, 133) + 1e-6);
          const leftEar = (distance(386, 374) + distance(385, 380)) / (2 * distance(362, 263) + 1e-6);
          measuredEar = (rightEar + leftEar) / 2;
          if (measuredEar <= 0.16) {
            eyeClosed = 1;
            blink = 1;
          }

          if (bestFaceLm.length > 473) {
            const ratioX = (iris: number, corner1: number, corner2: number) => {
              const minX = Math.min(bestFaceLm[corner1].x, bestFaceLm[corner2].x);
              const maxX = Math.max(bestFaceLm[corner1].x, bestFaceLm[corner2].x);
              return (bestFaceLm[iris].x - minX) / (maxX - minX + 1e-6);
            };
            const ratioY = (iris: number, corner1: number, corner2: number) => {
              const minY = Math.min(bestFaceLm[corner1].y, bestFaceLm[corner2].y);
              const maxY = Math.max(bestFaceLm[corner1].y, bestFaceLm[corner2].y);
              return (bestFaceLm[iris].y - minY) / (maxY - minY + 1e-6);
            };

            const averageIrisX = (ratioX(468, 33, 133) + ratioX(473, 362, 263)) / 2;
            const averageIrisY = (ratioY(468, 159, 145) + ratioY(473, 386, 374)) / 2;
            measuredIrisY = averageIrisY;
            if (averageIrisX <= 0.35 || averageIrisX >= 0.65) gazeSide = 1;
            if (averageIrisY >= 0.62) gazeDown = 1;
          }

          const eyeMidY = (bestFaceLm[33].y + bestFaceLm[263].y) / 2;
          const faceHeight = bestFaceLm[152].y - eyeMidY;
          const eyeWidth = Math.abs(bestFaceLm[263].x - bestFaceLm[33].x);
          measuredHead = faceHeight > 1e-6 ? (bestFaceLm[1].y - eyeMidY) / faceHeight : Number.NaN;
          if (faceHeight > 1e-6 && measuredHead >= 0.72) headDown = 1;
          if (eyeWidth > 1e-6 && Math.abs(bestFaceLm[33].y - bestFaceLm[263].y) / eyeWidth >= 0.12) headTilt = 1;
        }

        if (bestShoulderLm) {
          const shoulderWidth = Math.abs(bestShoulderLm[12].x - bestShoulderLm[11].x);
          const shoulderMidX = (bestShoulderLm[11].x + bestShoulderLm[12].x) / 2;
          if (Math.abs(bestShoulderLm[11].y - bestShoulderLm[12].y) >= 0.12) badPosture = 1;
          if (
            shoulderWidth > 1e-6 &&
            Math.abs(bestShoulderLm[0].x - shoulderMidX) / shoulderWidth >= 0.18
          ) {
            badPosture = 1;
          }
        }

        temporalBufferRef.current.push({
          eyeClosed: eyeClosed === 1,
          rightWrist: bestWristLm?.[16] ? { x: bestWristLm[16].x, y: bestWristLm[16].y } : null,
        });
        if (temporalBufferRef.current.length > 10) temporalBufferRef.current.shift();

        if (temporalBufferRef.current.length === 10) {
          if (temporalBufferRef.current.every((frame: any) => frame.eyeClosed)) longEyeClosure = 1;

          let pathLength = 0;
          let validPairs = 0;
          const xs: number[] = [];
          const ys: number[] = [];
          const vectors: { x: number; y: number }[] = [];
          let firstValidWrist: { x: number; y: number } | null = null;
          let lastValidWrist: { x: number; y: number } | null = null;

          for (let index = 1; index < temporalBufferRef.current.length; index += 1) {
            const previous = temporalBufferRef.current[index - 1].rightWrist;
            const current = temporalBufferRef.current[index].rightWrist;
            if (!previous || !current) continue;

            if (!firstValidWrist) firstValidWrist = previous;
            lastValidWrist = current;
            xs.push(previous.x, current.x);
            ys.push(previous.y, current.y);

            const dx = current.x - previous.x;
            const dy = current.y - previous.y;
            const magnitude = Math.hypot(dx, dy);
            pathLength += magnitude;
            if (magnitude > 1e-6) vectors.push({ x: dx / magnitude, y: dy / magnitude });
            validPairs += 1;
          }

          if (validPairs >= 7 && firstValidWrist && lastValidWrist && xs.length > 0 && ys.length > 0) {
            const netDisplacement = Math.hypot(
              lastValidWrist.x - firstValidWrist.x,
              lastValidWrist.y - firstValidWrist.y
            );
            const xSpan = Math.max(...xs) - Math.min(...xs);
            const ySpan = Math.max(...ys) - Math.min(...ys);
            const boundingBoxDiagonal = Math.hypot(xSpan, ySpan);
            let directionChanges = 0;

            for (let index = 1; index < vectors.length; index += 1) {
              const dot = vectors[index - 1].x * vectors[index].x + vectors[index - 1].y * vectors[index].y;
              if (dot < 0.2) directionChanges += 1;
            }

            if (
              pathLength >= 0.18 &&
              netDisplacement >= 0.14 &&
              xSpan >= 0.12 &&
              ySpan <= 0.10 &&
              directionChanges <= 2
            ) {
              pageTurn = 1;
            } else if (pathLength >= 0.18 && boundingBoxDiagonal <= 0.12 && directionChanges >= 3) {
              penFidget = 1;
            } else if (pathLength >= 0.28 && boundingBoxDiagonal >= 0.18 && directionChanges >= 2) {
              restlessHand = 1;
            }
          }
        }

        features[2] = faceSeen;
        features[3] = gazeSide;
        features[4] = gazeDown;
        features[5] = badPosture;
        features[6] = eyeClosed;
        features[7] = blink;
        features[8] = longEyeClosure;
        features[9] = headDown;
        features[10] = headTilt;
        features[11] = longEyeClosure && headDown ? 1 : 0;
        features[12] = pageTurn;
        features[13] = penFidget;
        features[14] = restlessHand;
        features[15] = 0;

        let probabilities: Float32Array | null = null;
        if (onnxSessionRef.current && [measuredEar, measuredIrisY, measuredHead].every(Number.isFinite)) {
          try {
            validateFeatures(features);
            const results = await onnxSessionRef.current.run({
              float_input: new ort.Tensor("float32", features, [1, 16]),
            });
            const probabilityOutput = results.probabilities;
            const labelOutput = results.label;
            if (
              probabilityOutput.type !== "float32" ||
              probabilityOutput.dims.join() !== "1,5" ||
              labelOutput.type !== "string" ||
              labelOutput.dims.join() !== "1"
            ) {
              throw new Error("Invalid ONNX output contract");
            }

            const values = probabilityOutput.data as Float32Array;
            validateProbabilities(values);
            const maximum = Math.max(...values);
            const predictedIndex = Array.from(values).indexOf(maximum);
            if (String(labelOutput.data[0]) !== MODEL_CLASSES[predictedIndex]) {
              throw new Error("Class order mismatch");
            }
            probabilities = values;
            if (modelWarning) setModelWarning("");
          } catch (error) {
            console.error("ONNX contract/inference failed", error);
            setModelWarning("AI 추론을 사용할 수 없어 카메라 규칙으로 판정합니다.");
          }
        }

        const rawDecision = decisionRef.current.step(
          nowMs,
          {
            faceSeen: Boolean(faceSeen),
            personSeen: Boolean(
              faceSeen ||
              frontPoseRes.landmarks?.length ||
              deskPoseRes.landmarks?.length ||
              deskFaceRes.faceLandmarks?.length
            ),
            ear: measuredEar,
            irisY: measuredIrisY,
            head: measuredHead,
            badPosture: Boolean(badPosture),
            pageTurn: Boolean(pageTurn),
            penFidget: Boolean(penFidget),
            restlessHand: Boolean(restlessHand),
          },
          probabilities
        );

        // Exhibition guard: preserve the teammate's ProductionDecision output for
        // debugging, but treat visible desk activity as evidence that the user is
        // actively studying rather than sleeping. If drowsy is returned while a
        // hand event is present, record that hand event instead. Otherwise, only
        // keep drowsy after approximately 10 consecutive one-second eye-closed
        // samples; normal downward reading becomes gaze_down/focus.
        let adjustedState = rawDecision.final_state;
        const deskFallbackActive = !faceSeen && Boolean(deskRightWrist) && deskWristMoving;
        setUsingDeskFallback(deskFallbackActive);

        // A confirmed long eye closure always wins. The previous guard allowed
        // wrist jitter to overwrite genuine drowsiness as restless_hand.
        if (longEyeClosure === 1) {
          adjustedState = "drowsy";
        } else if (deskFallbackActive) {
          // Face is missing but the overhead camera currently sees an active wrist:
          // treat this as poor posture while the user is still working at the desk.
          adjustedState = "bad_posture";
        } else if (!faceSeen) {
          // Without a front face signal there is no valid EAR/iris/head evidence.
          // If there is no currently visible moving wrist either, UNKNOWN is safer
          // than carrying forward posture or drowsiness assumptions.
          adjustedState = "unknown";
        } else if (adjustedState === "drowsy") {
          // Without sustained eye closure, suppress likely reading-related false
          // drowsiness while preserving the teammate's raw decision in debug data.
          if (pageTurn) {
            adjustedState = "page_turn";
          } else if (penFidget) {
            adjustedState = "pen_fidget";
          } else if (restlessHand || deskWristMoving) {
            adjustedState = "restless_hand";
          } else {
            adjustedState = (gazeDown || headDown) ? "gaze_down" : "focus";
          }
        }

        // A stale inference warning should disappear once the face signal is back
        // and the ONNX session is still available.
        if (faceSeen && onnxSessionRef.current && modelWarning) {
          setModelWarning("");
        }

        const decision = {
          ...rawDecision,
          final_state: adjustedState,
          decision_source:
            adjustedState === rawDecision.final_state
              ? rawDecision.decision_source
              : `frontend_guard:${rawDecision.final_state}`,
        };

        const currentT = startTimeRef.current
          ? Math.floor((nowMs - startTimeRef.current) / 1000)
          : timelineRef.current.length + 1;
        timelineRef.current.push(toTimelinePoint(currentT, decision));
        setCurrentState(decision.final_state);
        setCalibrating(!decision.calibration_valid);
        setDebugData({
          ...decision,
          timestamp: Date.now(),
          features: Array.from(features),
          probabilities: probabilities ? Array.from(probabilities) : null,
          ai_tracking: {
            front_faces: frontFaceRes.faceLandmarks?.length ?? 0,
            desk_faces: deskFaceRes.faceLandmarks?.length ?? 0,
            front_poses: frontPoseRes.landmarks?.length ?? 0,
            desk_poses: deskPoseRes.landmarks?.length ?? 0,
            desk_wrist_moving: deskWristMoving,
            desk_fallback_active: deskFallbackActive,
            front_logic_active: Boolean(faceSeen),
          },
          timeline_length: timelineRef.current.length,
          latest_payload: timelineRef.current[timelineRef.current.length - 1] ?? null,
        });
      } finally {
        inferenceBusy.current = false;
      }
    } catch (error) {
      console.warn("AI Inference skipped a frame due to an error:", error);
      inferenceBusy.current = false;
    }
  };

  const handleStart = async () => {
    const userId = localStorage.getItem("user_id");
    if (!userId) {
      alert("로그인이 필요합니다.");
      return;
    }
    if (isRunning) return;
    if (!modelsLoaded) {
      alert("카메라 분석 도구를 불러오는 중입니다.");
      return;
    }

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
      temporalBufferRef.current = [];
      lastDeskWristRef.current = null;
      deskWristMovingUntilRef.current = 0;
      decisionRef.current.reset();
      lastFrontFrameTime.current = -1;
      setCalibrating(true);
      setUsingDeskFallback(false);
      setModelWarning("");
      setCurrentState("unknown");

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
      if (inferenceBusy.current) {
        alert("판정 처리 중입니다. 잠시 후 종료를 다시 눌러 주세요.");
        return;
      }
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
      setUsingDeskFallback(false);
      setModelWarning("");
      setSeconds(0);
      setSessionId(null);
      alert("세션 종료 및 데이터 저장 성공!");
    } catch (error) {
      console.error("Pipeline error:", error);
      alert("세션 종료 중 오류가 발생했습니다.");
    }
  };

  const isDistracted = isRunning && alarmEnabledRef.current && !NON_DISTRACTING_STATES.has(currentState);

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

        {isRunning && usingDeskFallback && (
          <div role="status" className="mb-4 rounded-lg border border-sky-300 bg-sky-50 px-4 py-3 text-sm text-sky-900">
            얼굴 신호가 일시적으로 보이지 않아 책상 손 움직임과 자세 정보로 보조 판정 중입니다.
          </div>
        )}
        {isRunning && calibrating && (
          <div role="status" className="mb-4 rounded-lg border border-primary/20 bg-primary/5 px-4 py-3 text-sm text-foreground">
            개인 기준을 맞추고 있습니다. 눈을 뜨고 정면 카메라를 약 5초 동안 바라봐 주세요.
          </div>
        )}

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