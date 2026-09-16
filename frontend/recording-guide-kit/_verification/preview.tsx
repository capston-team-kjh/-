import { useState } from "react";
import { createRoot } from "react-dom/client";
import { RecordingGuide, RecordingChecklist } from "../RecordingGuide";

function Preview() {
  const [page, setPage] = useState<"guide" | "checklist">("guide");
  const [fail, setFail] = useState(false);
  const [blocked, setBlocked] = useState(false);
  const [started, setStarted] = useState(false);
  const [version, setVersion] = useState(0);
  const [calls, setCalls] = useState(0);

  function changePage(next: "guide" | "checklist") {
    setPage(next);
    window.scrollTo(0, 0);
  }

  return <>
    <div className="demo-toolbar"><strong>FocusAI <span>컴포넌트 미리보기</span></strong><div><button type="button" aria-pressed={page === "guide"} onClick={() => changePage("guide")}>촬영 가이드</button><button type="button" aria-pressed={page === "checklist"} onClick={() => changePage("checklist")}>체크리스트</button></div></div>
    {page === "guide" ? <RecordingGuide onGoToSetup={() => changePage("checklist")} /> : <main className="demo-checklist">
      <p className="demo-caption">동작 미리보기 · 카메라와 서버에 연결하지 않습니다.</p>
      <RecordingChecklist key={version} disabled={blocked || started} disabledReason={started ? "시작 콜백이 완료됐어요." : "카메라 연결을 기다리고 있어요."} onStart={async () => {
        setCalls((value) => value + 1);
        await new Promise((resolve) => window.setTimeout(resolve, 1200));
        if (fail) throw new Error("Preview failure");
        setStarted(true);
      }} />
      <div className="demo-controls"><label><input type="checkbox" checked={fail} onChange={(event) => setFail(event.target.checked)} /> 시작 실패 예시</label><label><input type="checkbox" checked={blocked} onChange={(event) => setBlocked(event.target.checked)} /> 카메라 준비 중 예시</label><button type="button" onClick={() => { setVersion((value) => value + 1); setStarted(false); setCalls(0); }}>체크 초기화</button><span role="status">시작 호출: {calls}회{started ? " · 완료" : ""}</span></div>
      <button className="demo-back" type="button" onClick={() => changePage("guide")}>← 촬영 가이드로 돌아가기</button>
    </main>}
  </>;
}

createRoot(document.getElementById("root")!).render(<Preview />);
