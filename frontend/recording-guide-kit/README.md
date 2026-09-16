# FocusAI 촬영 가이드 · 바로 붙여 넣는 React 컴포넌트

`RecordingGuide.tsx`와 `RecordingGuide.css`를 **같은 폴더**에 복사하면 됩니다.
React 18 이상 + TypeScript + CSS import를 지원하는 Vite 환경 기준입니다.
Tailwind, 아이콘 라이브러리, 외부 이미지, 추가 패키지 설치가 필요하지 않습니다.
이 폴더는 독립적인 전달용 코드입니다. 기존 화면과 라우트에는 아직 연결하지 않았습니다.

저장소 위치: `frontend/recording-guide-kit/`

`preview.html`을 브라우저로 열면 설치 없이 가이드와 체크리스트를 볼 수 있습니다.
이 미리보기는 카메라나 서버를 호출하지 않습니다.

## 포함 내용

- `RecordingGuide`: 카메라 배치 그림, 촬영 환경, 시작·학습·종료 안내, FAQ 8개, 분석 결과와 촬영 정보 안내.
- `RecordingChecklist`: 시작 전 체크 항목 4개, 확인 개수, 선택적인 시작 버튼, 시작 중 중복 클릭 방지 및 실패 안내.
- 모바일 반응형, 키보드 포커스, 접근 가능한 체크박스·접기/펼치기.
- 그림은 배치를 설명하는 SVG 예시입니다. 실제 카메라 영상이 아닙니다.

## 1. 파일 복사

```text
frontend/src/components/recording-guide/
  RecordingGuide.tsx
  RecordingGuide.css
```

CSS는 TSX에서 import합니다. 클래스에 `fg-` 접두어를 사용하여 기존 스타일에 대한 영향을 줄였습니다.
폰트는 부모 화면에서 상속하고 기본 색상은 현재 FocusAI의 청록색에 맞췄습니다.

## 2. 촬영 가이드 페이지 추가

`frontend/src/pages/recording-guide.tsx`:

```tsx
import { useNavigate } from "react-router";
import { RecordingGuide } from "../components/recording-guide/RecordingGuide";

export function RecordingGuidePage() {
  const navigate = useNavigate();

  return (
    <RecordingGuide onGoToSetup={() => navigate("/app/session")} />
  );
}
```

기존 `frontend/src/routes.tsx`에 import를 추가합니다.

```tsx
import { RecordingGuidePage } from "./pages/recording-guide";
```

`/app` 라우트의 **children 배열 안에** 다음 항목을 추가합니다.

```tsx
{
  path: "recording-guide",
  Component: RecordingGuidePage,
},
```

사이드바의 기존 `NavLink` 형식을 그대로 사용하려면
`dashboard-layout.tsx`의 `lucide-react` import에 `BookOpen`을 추가하고 다음을 넣습니다.

```tsx
<NavLink
  to="/app/recording-guide"
  icon={<BookOpen className="w-5 h-5" />}
  label="촬영 가이드"
  active={isActive("/app/recording-guide")}
/>
```

## 3. 기존 학습 화면에 체크리스트 추가

```tsx
import { RecordingChecklist } from "../components/recording-guide/RecordingGuide";
```

전체 가이드 페이지는 위 2단계만으로 바로 표시됩니다. **아래 체크리스트 연결은 선택 사항입니다.**
현재 학습 화면은 세션 시작 후에만 카메라 화면을 보여주므로, 시작 버튼 앞에 확인 체크를 강제하면
아직 보지 못한 화면을 확인했다고 체크하게 됩니다. 먼저 `카메라 연결·미리보기`와 `실제 분석 시작`을
분리한 화면에서 아래 예시를 사용하세요.

별도 준비 화면에서 체크리스트만 표시할 때는 `<RecordingChecklist />`로 사용할 수 있습니다.
시작 버튼까지 연결하는 아래 예시에서
`camerasReady`, `modelsLoaded`, `isRunning`, `startAnalysis`, `CameraPreviews`는 부모에서 실제 상태·함수·컴포넌트로 연결합니다.

```tsx
<RecordingChecklist
  disabled={!camerasReady || !modelsLoaded || isRunning}
  disabledReason={
    !camerasReady
      ? "카메라 2개를 연결하고 미리보기를 확인해주세요."
      : !modelsLoaded
        ? "분석 기능을 준비하고 있어요. 잠시 기다려주세요."
        : "학습이 진행 중이에요."
  }
  onStart={startAnalysis}
  guideHref="/app/recording-guide"
>
  <CameraPreviews />
</RecordingChecklist>
```

- 체크 항목 4개를 모두 선택하고 `disabled`가 false여야 시작 버튼이 활성화됩니다.
- 체크 여부는 **사용자의 수동 확인**입니다. 카메라를 자동 검사하거나 정확도를 보장하지 않습니다.
- `onStart`를 생략하면 시작 버튼이 나타나지 않습니다.
- `onStart`가 Promise를 반환하면 완료까지 체크박스와 버튼을 비활성화합니다. 실패를 throw/reject하면 오류 안내와 재시도를 제공합니다.
- 시작 성공 이후의 화면 전환·실행 중 상태 처리는 부모가 담당합니다. `isRunning` 동안 컴포넌트를 숨기거나 `disabled`를 유지하세요.
- 부모가 오류를 catch하고 정상 반환하면 이 컴포넌트는 실패를 알 수 없습니다. 부모가 오류를 표시하거나 다시 throw하도록 연결하세요.
- 카메라 연결, 스트림 해제, 권한 요청, 세션 생성, 분석·저장은 기존 앱에서 처리합니다. 컴포넌트가 자동 실행하지 않습니다.
- 실행 중 전체 가이드 링크를 누르면 현재 페이지를 떠날 수 있습니다. 학습 중 도움말에는 `guideHref`를 생략하고 같은 화면에서 안내를 펼쳐주세요. 현재 앱에는 페이지 이탈 시 자동 저장이 없습니다.
- 카메라를 교체하거나 새 세션을 준비할 때 `key={setupVersion}`처럼 key를 바꾸면 체크 항목을 초기화할 수 있습니다.
- 시작 전 미리보기를 구현하면서 **기존 `handleStart`를 그대로 호출하여 카메라를 중복 연결하지 마세요.** 이미 얻은 스트림을 재사용하도록 기존 흐름을 분리해야 합니다.
- 현재 학습 화면은 시작 후에만 미리보기를 표시합니다. 따라서 그 상태에서 아직 보지 못한 화면을 확인했다고 체크하도록 시작 버튼을 막으면 안 됩니다.

## 4. 영상·개인정보 안내 연결

확인되지 않은 ‘영상 즉시 삭제’, ‘서버 전송 없음’, 보관 기간을 코드에 임의로 넣지 않았습니다.
기본 화면은 촬영 범위와 분석 결과의 의미를 안내합니다. 실제 처리 정책을 확정한 뒤 `dataPolicy`에 넣으면
‘영상과 학습 기록은 이렇게 처리돼요’ 표가 추가됩니다. 선택적 `privacyPolicyHref`에는 **실제로 존재하는** 처리방침 경로를 넣으세요.

```tsx
import type { RecordingDataPolicy } from "../components/recording-guide/RecordingGuide";

// approvedPolicy는 팀에서 실제 배포 동작을 확인한 정책 객체입니다.
// 임의 예시를 실제 정책으로 게시하지 않도록 구체적인 보관·삭제 값은 기본 제공하지 않습니다.
const policy: RecordingDataPolicy = approvedPolicy;

<RecordingGuide
  dataPolicy={policy}
  privacyPolicyHref="/privacy"
  onGoToSetup={() => navigate("/app/session")}
/>
```

`RecordingDataPolicy` 필드:

| 필드 | 입력할 실제 정책 |
| --- | --- |
| `video` | 영상의 처리 위치, 원본 전송·저장 여부 |
| `audio` | 마이크·음성 수집 여부 |
| `retention` | 저장하는 정보와 보관 기간 |
| `deletion` | 삭제 방법·요청 경로 |
| `trainingUse` (선택) | 모델 학습 활용 여부와 조건 |

현재 로컬 프론트에서 확인한 일반 세션 흐름은 브라우저 분석 후 결과 timeline을 전송하는 방식입니다.
기존 서버 업로드 경로 및 실제 배포 버전 전체의 정책까지 확정한 것은 아닙니다.

## 5. 확인 방법

기존 프론트에 파일을 복사하고 라우트를 연결한 뒤 `frontend`에서 실행합니다.

```powershell
npm run build
npm run dev
```

`/app/recording-guide`에서 목차 이동, FAQ 펼치기, 모바일 화면을 확인하세요.
체크리스트를 연결했다면 일부 체크 시 시작 불가, 전체 체크 시 활성화, 상위 disabled 우선 적용,
시작 중 중복 클릭 차단, 실패 안내와 재시도를 확인하면 됩니다.

이 전달물의 미리보기는 별도 `preview.html`에 있습니다. 실제 카메라와 서버를 호출하지 않습니다.

## 6. 미리보기 다시 만들기

프론트 의존성이 설치된 상태에서 `frontend` 폴더에서 실행합니다.

```powershell
node .\recording-guide-kit\_verification\build-preview.cjs
```

출력은 `recording-guide-kit/preview.html`입니다. 다른 위치의 기존 의존성을 재사용하려면
마지막 인자로 해당 `node_modules` 경로를 전달할 수 있습니다.

로컬 HTTP 미리보기가 필요하면 같은 위치에서 다음 명령을 실행합니다.

```powershell
node .\recording-guide-kit\_verification\serve.cjs
```

브라우저에서 `http://127.0.0.1:4319`를 엽니다. 이미 사용 중인 포트이면 기존 미리보기 서버를 확인해주세요.
