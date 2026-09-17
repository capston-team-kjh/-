import { useId, useRef, useState } from "react";
import type { ReactNode } from "react";
import "./RecordingGuide.css";

/** 실제 배포 환경에서 확인한 내용만 전달하세요. 기본값으로 보관·삭제 정책을 추정하지 않습니다. */
export interface RecordingDataPolicy {
  video: string;
  audio: string;
  retention: string;
  deletion: string;
  trainingUse?: string;
}

export interface RecordingGuideProps {
  className?: string;
  /** 카메라 준비 화면으로 이동하는 콜백입니다. 이 컴포넌트는 촬영을 시작하지 않습니다. */
  onGoToSetup?: () => void;
  dataPolicy?: RecordingDataPolicy;
  privacyPolicyHref?: string;
}

export interface RecordingChecklistProps {
  className?: string;
  /** 생략하면 체크리스트만 표시합니다. 실제 카메라 연결·세션 생성은 부모가 담당합니다. */
  onStart?: () => void | Promise<void>;
  /** 모델 로딩 또는 카메라 준비 중에는 true로 전달하세요. */
  disabled?: boolean;
  disabledReason?: string;
  guideHref?: string;
  /** 부모에서 관리하는 실제 카메라 미리보기를 넣을 수 있습니다. */
  children?: ReactNode;
}

const checklistItems = [
  { title: "얼굴과 양쪽 어깨가 보여요", detail: "얼굴이 화면 밖으로 잘리지 않고, 눈이 선명하게 보여야 해요." },
  { title: "교재와 양손이 보여요", detail: "책상 캠에서 읽고 쓰는 영역과 손의 움직임을 확인해주세요." },
  { title: "밝기와 카메라 위치를 확인했어요", detail: "역광과 눈의 가림을 피하고, 카메라가 흔들리지 않게 고정해주세요." },
  { title: "얼굴 캠과 책상 캠이 올바르게 연결됐어요", detail: "두 화면이 반대로 보이지 않는지 확인해주세요. 얼굴 캠에는 얼굴이, 책상 캠에는 책상 위 학습 영역이 보여야 해요." },
];

const faqs = [
  {
    question: "카메라가 하나만 있어도 사용할 수 있나요?",
    answer: "현재 FocusAI의 학습 분석은 얼굴용과 책상용 카메라 2개를 사용합니다. 두 카메라가 컴퓨터에 연결되어 있고 브라우저에서 인식되는지 확인해주세요.",
  },
  {
    question: "카메라 화면이 나오지 않아요.",
    answer: "브라우저의 사이트 권한에서 카메라 사용을 허용했는지 확인해주세요. 연결 케이블을 확인하고, 화상회의처럼 카메라를 사용하는 다른 프로그램을 종료한 뒤 다시 시도해주세요. 이미 학습 중이라면 새로고침 전에 세션 종료와 저장 완료 여부를 확인해주세요.",
  },
  {
    question: "얼굴 캠과 책상 캠이 반대로 보여요.",
    answer: "두 화면이 반대로 보인다면 학습을 시작하기 전에 카메라 연결 순서와 위치를 확인해주세요. ‘얼굴 캠’에는 얼굴이, ‘책상 캠’에는 책상 위 학습 영역이 나오는지 다시 확인해주세요.",
  },
  {
    question: "책을 읽거나 필기할 때 고개를 숙여도 되나요?",
    answer: "네. 평소처럼 자연스럽게 공부해주세요. 아래를 보는 행동만으로 집중하지 않는다고 판단하지 않도록 책상 위 활동을 함께 참고합니다. 다만 얼굴이나 손이 오래 가려지면 분석이 부정확할 수 있어요.",
  },
  {
    question: "안경을 쓰고 있어도 되나요?",
    answer: "평소 사용하는 안경을 착용하셔도 됩니다. 렌즈에 조명이나 화면이 강하게 반사되어 눈이 가려지면 조명 또는 카메라 각도를 조금 조절해주세요.",
  },
  {
    question: "카메라 화면을 숨기면 분석도 멈추나요?",
    answer: "학습 화면의 ‘카메라’ 버튼은 미리보기 표시를 바꾸는 기능입니다. 미리보기를 숨기는 것만으로 학습 분석이 종료되지는 않습니다. 학습을 마치려면 ‘세션 종료’를 눌러주세요.",
  },
  {
    question: "공부하고 있는데 다른 상태로 표시돼요.",
    answer: "먼저 얼굴과 눈의 가림, 조명, 카메라 역할을 확인해주세요. 결과는 영상에 보이는 행동을 바탕으로 추정하므로 실제 집중 상태와 다를 수 있습니다. 순간적인 표시 하나보다 전체 학습 흐름을 참고해주세요.",
  },
  {
    question: "학습을 끝낼 때 창을 바로 닫아도 되나요?",
    answer: "‘세션 종료’를 누른 뒤 저장 완료 안내를 확인하고 창을 닫아주세요. 종료 전에 창을 닫거나 새로고침하면 학습 기록이 저장되지 않을 수 있습니다. 저장 오류가 표시되면 바로 페이지를 떠나지 말고 연결 상태를 확인해주세요.",
  },
];

function CheckIcon() {
  return <svg viewBox="0 0 20 20" fill="none" aria-hidden="true"><path d="m5 10 3 3 7-7" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round" /></svg>;
}

function ArrowIcon() {
  return <svg viewBox="0 0 20 20" fill="none" aria-hidden="true"><path d="M4 10h12m-5-5 5 5-5 5" stroke="currentColor" strokeWidth="1.6" strokeLinecap="round" strokeLinejoin="round" /></svg>;
}

function CameraDiagram({ desk = false }: { desk?: boolean }) {
  return (
    <svg className="fg-camera-diagram" viewBox="0 0 400 225" role="img" aria-label={desk ? "책상 위를 내려다보며 펼친 교재와 양손을 담는 책상 카메라 배치 예시" : "얼굴 전체와 양쪽 어깨를 화면 중앙에 담는 얼굴 카메라 배치 예시"}>
      <rect width="400" height="225" rx="16" fill="#edf5f5" />
      <rect x="32" y="24" width="336" height="177" rx="12" fill="#fff" stroke="#cedfdf" />
      {desk ? (
        <>
          <rect x="59" y="48" width="282" height="130" rx="10" fill="#e3cfad" />
          <path d="M137 68q32-10 63 0v87q-32-10-63 0zm63 0q32-10 63 0v87q-32-10-63 0z" fill="#fffdf8" stroke="#baaa8e" strokeWidth="2" />
          <path d="M151 86h34m-34 12h34m-34 12h28m38-24h34m-34 12h34m-34 12h27" stroke="#bac6c5" strokeWidth="3" strokeLinecap="round" />
          <path d="m99 186 17-44q4-10 12-8l16 5q8 3 4 13l-9 34m162 0-17-44q-4-10-12-8l-16 5q-8 3-4 13l9 34" fill="#e8b597" stroke="#c18b71" strokeWidth="2" />
          <path d="m265 133-14-37" stroke="#1a667a" strokeWidth="5" strokeLinecap="round" />
          <rect x="92" y="57" width="216" height="116" rx="8" fill="none" stroke="#1a667a" strokeWidth="2" strokeDasharray="6 5" />
        </>
      ) : (
        <>
          <path d="M110 191v-20c0-34 43-51 90-51s90 17 90 51v20" fill="#78a8ae" />
          <path d="M186 113h28v29q-14 13-28 0" fill="#d9a284" />
          <ellipse cx="200" cy="91" rx="37" ry="46" fill="#ebbb9d" />
          <path d="M163 90q-6-49 39-49 43 1 36 49l-11-24q-27 10-54 0z" fill="#304b53" />
          <path d="M182 88h8m20 0h8" stroke="#304b53" strokeWidth="3" strokeLinecap="round" />
          <path d="M192 113q8 5 16 0" fill="none" stroke="#a76d57" strokeWidth="2" strokeLinecap="round" />
          <rect x="101" y="37" width="198" height="149" rx="10" fill="none" stroke="#1a667a" strokeWidth="2" strokeDasharray="6 5" />
        </>
      )}
      <circle cx="349" cy="42" r="6" fill="#1a667a" />
      <path d="M47 46v-8h8m298 0h-8m8 0v8M47 178v8h8m298-8v8h-8" fill="none" stroke="#1a667a" strokeWidth="2" strokeLinecap="round" />
    </svg>
  );
}

function SectionHeading({ number, title, description, id }: { number: string; title: string; description: string; id: string }) {
  return <div className="fg-section-heading"><span className="fg-section-number" aria-hidden="true">{number}</span><div><h2 id={id}>{title}</h2><p>{description}</p></div></div>;
}

export function RecordingChecklist({ className = "", onStart, disabled = false, disabledReason, guideHref, children }: RecordingChecklistProps) {
  const id = useId();
  const [checked, setChecked] = useState<boolean[]>(() => checklistItems.map(() => false));
  const [starting, setStarting] = useState(false);
  const [error, setError] = useState("");
  const startingRef = useRef(false);
  const count = checked.filter(Boolean).length;
  const ready = count === checklistItems.length;

  async function handleStart() {
    if (!onStart || !ready || disabled || startingRef.current) return;
    startingRef.current = true;
    setStarting(true);
    setError("");
    try {
      await onStart();
    } catch {
      setError("학습을 시작하지 못했습니다. 카메라와 네트워크 연결을 확인한 뒤 다시 시도해주세요.");
    } finally {
      startingRef.current = false;
      setStarting(false);
    }
  }

  return (
    <section className={`fg-root fg-checklist ${className}`} aria-labelledby={`${id}-title`}>
      <div className="fg-checklist-heading"><div><span className="fg-eyebrow">BEFORE YOU START</span><h2 id={`${id}-title`}>학습 시작 전, 카메라를 확인해주세요</h2><p>미리보기를 보며 네 가지 항목을 직접 확인해주세요.</p></div><span className="fg-count" aria-live="polite">{count} / {checklistItems.length} 확인</span></div>
      {children && <div className="fg-live-preview">{children}</div>}
      <fieldset className="fg-checklist-fields" disabled={starting}>
        <legend className="fg-sr-only">촬영 준비 확인</legend>
        {checklistItems.map((item, index) => (
          <label className={`fg-check-item ${checked[index] ? "fg-is-checked" : ""}`} key={item.title}>
            <input type="checkbox" checked={checked[index]} onChange={(event) => {
              const next = event.target.checked;
              setChecked((previous) => previous.map((value, itemIndex) => itemIndex === index ? next : value));
              setError("");
            }} />
            <span><strong>{item.title}</strong><span className="fg-check-detail">{item.detail}</span></span>
          </label>
        ))}
      </fieldset>
      <div className="fg-checklist-footer">
        <div><p id={`${id}-status`} className="fg-check-status" aria-live="polite">{disabled ? disabledReason || "카메라와 분석 준비가 끝나면 시작할 수 있어요." : ready ? "네 가지 항목을 모두 확인했어요." : "확인한 항목을 체크해주세요."}</p>{guideHref && <a className="fg-text-link" href={guideHref}>자세한 촬영 가이드 <ArrowIcon /></a>}</div>
        {onStart && <button type="button" className="fg-button" onClick={handleStart} disabled={!ready || disabled || starting} aria-busy={starting} aria-describedby={`${id}-status`}>{starting ? "학습 시작 중…" : "학습 시작"}<ArrowIcon /></button>}
      </div>
      {error && <p className="fg-error" role="alert">{error}</p>}
    </section>
  );
}

export function RecordingGuide({ className = "", onGoToSetup, dataPolicy, privacyPolicyHref }: RecordingGuideProps) {
  const baseId = `fg-${useId().replace(/:/g, "")}`;
  const sectionId = (name: string) => `${baseId}-${name}`;
  const sections = [["cameras", "카메라 배치"], ["environment", "촬영 환경"], ["steps", "학습 순서"], ["faq", "자주 묻는 질문"], ["data", "결과·정보 안내"]];
  const policyRows = dataPolicy ? [
    ["영상 처리", dataPolicy.video], ["음성 수집", dataPolicy.audio],
    ["보관 기간", dataPolicy.retention], ["삭제 방법", dataPolicy.deletion],
    ...(dataPolicy.trainingUse ? [["모델 학습 활용", dataPolicy.trainingUse]] : []),
  ] : [];

  return (
    <div className={`fg-root fg-guide ${className}`}>
      <div className="fg-container">
        <header className="fg-hero">
          <div className="fg-hero-copy"><span className="fg-eyebrow">FOCUS AI · 촬영 가이드</span><h1>잘 보이는 화면에서,<br />더 나은 학습 기록으로.</h1><p>얼굴과 책상 위 활동을 함께 살펴 학습 상태를 분석해요.<br className="fg-desktop-break" /> 시작하기 전에 두 카메라의 위치와 촬영 환경을 확인해주세요.</p><a href={`#${sectionId("cameras")}`} className="fg-button">카메라 배치 살펴보기 <ArrowIcon /></a></div>
          <div className="fg-hero-aside"><span className="fg-hero-aside-label">준비는 간단하게</span>{["두 카메라를 연결해요", "얼굴과 책상이 잘 보이는지 확인해요", "평소처럼 자연스럽게 공부해요"].map((text, index) => <div className="fg-hero-step" key={text}><span>0{index + 1}</span><p>{text}</p></div>)}</div>
        </header>

        <nav className="fg-nav" aria-label="촬영 가이드 목차">{sections.map(([name, title], index) => <a href={`#${sectionId(name)}`} key={name}><span aria-hidden="true">0{index + 1}</span>{title}</a>)}</nav>

        <section className="fg-section" aria-labelledby={sectionId("cameras")}>
          <SectionHeading id={sectionId("cameras")} number="01" title="카메라마다 보는 곳이 달라요" description="얼굴용과 책상용 카메라 2개를 연결하고, 브라우저의 카메라 사용을 허용해주세요." />
          <div className="fg-camera-grid">
            <article className="fg-camera-card"><div className="fg-card-label"><span className="fg-tag">얼굴 캠</span><span>정면에서 바라보도록</span></div><CameraDiagram /><h3>얼굴 전체와 양쪽 어깨를 담아주세요</h3><p>눈과 고개의 움직임, 자세를 살펴보는 화면이에요. 눈높이에 가깝게 배치하고 얼굴이 너무 작거나 크게 나오지 않도록 조절해주세요.</p><ul className="fg-tick-list"><li><CheckIcon />얼굴이 잘리지 않고 눈이 선명하게 보여요.</li><li><CheckIcon />양쪽 어깨가 화면에 함께 들어와요.</li></ul><p className="fg-avoid"><strong>조정이 필요해요</strong> 얼굴이 잘리거나, 너무 멀거나, 옆모습만 보이는 화면</p></article>
            <article className="fg-camera-card"><div className="fg-card-label"><span className="fg-tag">책상 캠</span><span>책상 위를 내려다보도록</span></div><CameraDiagram desk /><h3>교재와 양손의 움직임을 담아주세요</h3><p>읽고 쓰는 학습 활동을 참고하는 화면이에요. 책상 위쪽에서 교재·노트와 양손이 함께 보이도록 배치해주세요.</p><ul className="fg-tick-list"><li><CheckIcon />실제로 공부하는 영역이 화면 안에 있어요.</li><li><CheckIcon />필기하거나 책장을 넘겨도 손이 보여요.</li></ul><p className="fg-avoid"><strong>조정이 필요해요</strong> 교재만 확대되거나, 손이 잘리거나, 물건에 가려진 화면</p></article>
          </div>
          <p className="fg-note"><strong>두 화면이 반대로 보이나요?</strong> 학습을 시작하기 전에 카메라 연결 순서와 위치를 확인해주세요. ‘얼굴 캠’에는 얼굴이, ‘책상 캠’에는 책상 위 학습 영역이 보여야 합니다.</p>
        </section>

        <section className="fg-section" aria-labelledby={sectionId("environment")}>
          <SectionHeading id={sectionId("environment")} number="02" title="조명과 주변도 한 번 확인해주세요" description="특정 거리보다, 미리보기에서 얼굴과 학습 영역이 선명하게 보이는지가 중요해요." />
          <div className="fg-environment-grid">{[
            ["밝고 고른 조명", "얼굴 뒤쪽의 강한 빛을 피해주세요. 얼굴이 어둡다면 조명을 앞쪽이나 옆쪽으로 옮겨주세요.", "빛은 얼굴이 보이는 방향으로"],
            ["가리지 않는 화면", "머리카락, 손, 안경 반사로 눈이 가려지지 않는지 확인해주세요. 책상 위 물건도 촬영 범위를 가리지 않게 정리해요.", "눈과 손이 선명하게"],
            ["흔들리지 않는 카메라", "카메라를 안정적으로 고정해주세요. 공부하는 동안 화면 구도가 크게 바뀌지 않도록 해주세요.", "정한 위치를 그대로 유지"],
          ].map(([title, description, tip], index) => <article className="fg-environment-card" key={title}><span className="fg-small-number">0{index + 1}</span><h3>{title}</h3><p>{description}</p><span className="fg-small-tip">{tip}</span></article>)}</div>
        </section>

        <section className="fg-section" aria-labelledby={sectionId("steps")}>
          <SectionHeading id={sectionId("steps")} number="03" title="준비하고, 학습하고, 저장해요" description="분석을 위해 특별한 동작을 할 필요 없이 평소의 학습 모습을 보여주세요." />
          <ol className="fg-timeline">
            <li><span className="fg-step-dot" aria-hidden="true">1</span><div><span className="fg-step-label">시작할 때</span><h3>화면을 확인하고 편안하게 앉아주세요</h3><p>얼굴·책상 카메라의 역할과 촬영 범위를 확인해주세요. 시작 직후에는 평소의 편안한 자세로 잠시 정면을 바라봐주세요.</p></div></li>
            <li><span className="fg-step-dot" aria-hidden="true">2</span><div><span className="fg-step-label">학습하는 동안</span><h3>평소처럼 자연스럽게 공부해주세요</h3><p>독서·필기를 위해 고개를 숙여도 괜찮아요. 화면을 계속 쳐다볼 필요는 없어요. 카메라를 가리거나 자주 옮기지 않도록 해주세요.</p></div></li>
            <li><span className="fg-step-dot" aria-hidden="true">3</span><div><span className="fg-step-label">마무리할 때</span><h3>‘세션 종료’ 후 저장 완료를 확인해주세요</h3><p>저장이 끝나기 전에 새로고침하거나 창을 닫으면 기록이 저장되지 않을 수 있어요. 오류가 나오면 페이지를 떠나기 전에 연결 상태를 확인해주세요.</p></div></li>
          </ol>
        </section>

        <section className="fg-section" aria-labelledby={sectionId("faq")}>
          <SectionHeading id={sectionId("faq")} number="04" title="궁금한 점이 있나요?" description="촬영 준비와 학습 중 자주 겪는 상황을 모았어요." />
          <div className="fg-faq-list">{faqs.map(({ question, answer }) => <details className="fg-faq" key={question}><summary>{question}<span className="fg-faq-plus" aria-hidden="true">+</span></summary><p>{answer}</p></details>)}</div>
        </section>

        <section className="fg-section" aria-labelledby={sectionId("data")}>
          <SectionHeading id={sectionId("data")} number="05" title="분석 결과와 촬영 정보 안내" description="학습 기록을 이해하고, 촬영 화면에 담기는 정보를 확인해주세요." />
          <div className="fg-info-grid"><article className="fg-info-card"><h3>결과는 학습을 돌아보는 참고 자료예요</h3><p>영상에 나타난 행동으로 학습 상태를 추정하므로 실제 집중 상태와 다를 수 있어요. 조명, 얼굴 가림, 촬영 각도에 따라서도 결과가 달라질 수 있습니다.</p><p>점수 하나보다 자신의 학습 흐름과 쉬는 시간을 함께 살펴보세요.</p></article><article className="fg-info-card"><h3>촬영 범위를 필요한 곳으로 맞춰주세요</h3><p>다른 사람의 얼굴이나 개인정보가 적힌 문서가 화면에 들어오지 않도록 주변을 확인해주세요.</p><p>미리보기를 숨겨도 학습 분석은 계속됩니다. 마칠 때는 ‘세션 종료’를 눌러주세요.</p></article></div>
          {policyRows.length > 0 && <div className="fg-policy"><h3>영상과 학습 기록은 이렇게 처리돼요</h3><dl>{policyRows.map(([label, text]) => <div key={label}><dt>{label}</dt><dd>{text}</dd></div>)}</dl></div>}
          {privacyPolicyHref && <a className="fg-text-link fg-policy-link" href={privacyPolicyHref}>개인정보 처리방침 보기 <ArrowIcon /></a>}
        </section>

        <footer className="fg-end-card"><div><span className="fg-eyebrow">READY TO FOCUS</span><h2>이제, 나의 학습에 집중해볼까요?</h2><p>얼굴과 책상이 잘 보이는지 확인하고 시작해요.</p></div>{onGoToSetup && <button type="button" className="fg-button" onClick={onGoToSetup}>카메라 준비하러 가기 <ArrowIcon /></button>}</footer>
        <p className="fg-footnote">FocusAI · 학습 영상 촬영 가이드</p>
      </div>
    </div>
  );
}

export default RecordingGuide;
