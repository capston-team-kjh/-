import { useState, useEffect, useRef } from "react";
import { DualCameraManager } from "@/utils/dualCamManager";
import { Play, Square } from "lucide-react";

const SPLICING_INTERVAL_SECONDS = 3600;

export function StudySession() {
  const [isRunning, setIsRunning] = useState(false);
  const [seconds, setSeconds] = useState(0);
  const [sessionId, setSessionId] = useState<number | null>(null);
  const chunkIndexRef = useRef(1); 
  const sessionIdRef = useRef<number | null>(null);

  const manager = useRef(new DualCameraManager());

  useEffect(() => {
    let interval: number | undefined;

    if (isRunning) {
      interval = window.setInterval(() => {
        setSeconds((s) => {
          const nextSecond = s + 1;
          
          if (nextSecond > 0 && nextSecond % SPLICING_INTERVAL_SECONDS === 0) {
            console.log(`Interval Reached: (${SPLICING_INTERVAL_SECONDS}s) Requesting video slice...`);
            manager.current.requestSlice();
          }
          
          return nextSecond;
        });
      }, 1000);
    }

    return () => {
      if (interval) clearInterval(interval);
    };
  }, [isRunning]);

  const formatTime = (totalSeconds: number) => {
    const hours = Math.floor(totalSeconds / 3600);
    const minutes = Math.floor((totalSeconds % 3600) / 60);
    const secs = totalSeconds % 60;

    return `${hours.toString().padStart(2, "0")}:${minutes
      .toString()
      .padStart(2, "0")}:${secs.toString().padStart(2, "0")}`;
  };

  const uploadChunk = async (videoBlob: Blob, isFinal: boolean = false) => {
    const currentSessionId = sessionIdRef.current;
    if (!currentSessionId) return;

    const userId = localStorage.getItem("user_id") || "unknown";

    const currentPart = chunkIndexRef.current;
    chunkIndexRef.current += 1; // Increment immediately for the next interval ticker

    try {
      const formData = new FormData();
      // Pass the slice file named uniquely with its sequence index string
      formData.append("file", videoBlob, `user_${userId}_session_${currentSessionId}_part${currentPart}.webm`);
      
      formData.append("is_final_chunk", isFinal ? "true" : "false");

      console.log(`Uploading chunk ${currentPart} for Session ${currentSessionId}...`);

      const uploadResponse = await fetch(
        `${import.meta.env.VITE_API_BASE_URL}/sessions/${currentSessionId}/upload`,
        {
          method: "POST",
          body: formData,
        }
      );

      if (!uploadResponse.ok) {
        throw new Error(`Chunk ${currentPart} upload failed`);
      }

      console.log(`Chunk ${currentPart} uploaded successfully!`);
    } catch (error) {
      console.error(`Background upload error for chunk ${currentPart}:`, error);
    }
  };

  const handleStart = async () => {
    const userId = localStorage.getItem("user_id");
    if (!userId) {
      alert("로그인이 필요합니다.");
      return;
    }

    if (isRunning) return;

    let permissionStream: MediaStream | null = null;

    try {
      permissionStream = await navigator.mediaDevices.getUserMedia({
        video: true,
        audio: false,
      });

      const devices = await navigator.mediaDevices.enumerateDevices();

      permissionStream.getTracks().forEach((track) => track.stop());
      permissionStream = null;

      await new Promise((resolve) => setTimeout(resolve, 1000));

      const allCams = devices.filter((d) => d.kind === "videoinput");
      const selectedCams = allCams.slice(0, 2);

      if (selectedCams.length < 2) {
        alert("카메라가 2개 필요합니다 (얼굴용, 책상용)");
        return;
      }

      console.log("Found Camera 1 ID:", selectedCams[0].deviceId);
      console.log("Found Camera 2 ID:", selectedCams[1].deviceId);

      const response = await fetch(`${import.meta.env.VITE_API_BASE_URL}/sessions/`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ user_id: parseInt(userId, 10) }),
      });

      if (!response.ok) {
        throw new Error("세션 생성 실패");
      }

      const data = await response.json();
      setSessionId(data.id);

      sessionIdRef.current = data.id;
      chunkIndexRef.current = 1;

      await manager.current.start(
        selectedCams[0].deviceId,
        selectedCams[1].deviceId,
        uploadChunk
      );

      setIsRunning(true);
    } catch (error) {
      console.error("Failed to start session:", error);

      if (error instanceof Error) {
        console.error("Error name:", error.name);
        console.error("Error message:", error.message);
      }

    
      alert("세션 시작에 실패했습니다. 카메라 연결 상태를 확인하고 다시 시도해주세요.");
    } finally {
      if (permissionStream) {
        permissionStream.getTracks().forEach((track) => track.stop());
      }
    }
  };

  const handleStop = async () => {
    if (!sessionId) return;

    try {
      manager.current.requestSlice(true); 
      await manager.current.stop();

      const patchResponse = await fetch(
        `${import.meta.env.VITE_API_BASE_URL}/sessions/${sessionId}`,
        {
          method: "PATCH",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({
            status: "completed",
            end_time: new Date().toISOString(),
          }),
        }
      );

      if (!patchResponse.ok) {
        throw new Error("세션 종료 처리 실패");
      }

      setIsRunning(false);
      setSeconds(0);
      setSessionId(null);
      sessionIdRef.current = null;

      alert("모든 영상 조각 업로드 및 세션 종료 성공!");
    } catch (error) {
      console.error("Pipeline error:", error);
      alert("세션 종료 중 오류가 발생했습니다.");
    }
  };

  return (
    <div className="min-h-screen bg-gradient-to-br from-accent/20 to-white p-8">
      <div className="max-w-4xl mx-auto">
        <h1 className="text-3xl font-bold text-foreground mb-8">학습 세션</h1>

        <div className="bg-white rounded-2xl border border-border p-12 mb-6 text-center shadow-lg">
          {!isRunning ? (
            <div className="space-y-6">
              <div className="w-24 h-24 bg-accent rounded-full flex items-center justify-center mx-auto mb-4">
                <Play className="w-12 h-12 text-primary" />
              </div>
              <h2 className="text-2xl font-semibold text-foreground">
                학습을 시작할 준비가 되셨나요?
              </h2>
              <p className="text-muted-foreground">
                아래 버튼을 클릭하여 세션 추적을 시작하세요
              </p>

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

        <div className="p-6 bg-accent/30 rounded-xl border border-primary/20">
          <h3 className="font-semibold mb-3 text-primary">학습 팁</h3>
          <ul className="space-y-2 text-sm text-muted-foreground">
            <li>• 50분 학습 후 5-10분 휴식을 취하세요</li>
            <li>• 수분을 충분히 섭취하고 바른 자세를 유지하세요</li>
            <li>• 더 나은 집중을 위해 방해 요소를 제거하세요</li>
            <li>• 완료 후 세션 인사이트를 확인하세요</li>
          </ul> 
        </div>
      </div>
    </div>
  );
}