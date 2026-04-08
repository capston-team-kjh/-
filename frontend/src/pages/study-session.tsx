import { useState, useEffect } from "react";
import { Play, Square } from "lucide-react";

export function StudySession() {
  const [isRunning, setIsRunning] = useState(false);
  const [seconds, setSeconds] = useState(0);
  const [sessionId, setSessionId] = useState<number | null>(null);

  useEffect(() => {
    let interval: number | undefined;
    
    if (isRunning) {
      interval = window.setInterval(() => {
        setSeconds((s) => s + 1);
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

  const handleStart = async () => {
    const userId = localStorage.getItem("user_id");
    if (!userId) {
    alert("로그인이 필요합니다.");
    return;
  }

  try {
    const response = await fetch("http://13.209.127.3:8000/api/v1/sessions/", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ user_id: parseInt(userId) }),
    });

    if (response.ok) {
      const data = await response.json();
      setSessionId(data.id); 
      setIsRunning(true);
    }
  } catch (error) {
    console.error("Failed to start session:", error);
  }
};

  const handleStop = async () => {
    if (!sessionId) return;

  try {
    const response = await fetch(`http://13.209.127.3:8000/api/v1/sessions/${sessionId}`, {
      method: "PATCH",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        end_time: new Date().toISOString(),
        status: "completed",
      }),
    });

    if (response.ok) {
      setIsRunning(false);
      alert(`세션이 저장되었습니다! 총 시간: ${formatTime(seconds)}`);
      setSeconds(0);
      setSessionId(null);
    }
  } catch (error) {
    console.error("Failed to stop session:", error);
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