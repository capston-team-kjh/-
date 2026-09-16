# Frontend Harness Rules

- React + Vite 앱 진입점은 `src/main.tsx`이고 라우팅은 `src/routes.tsx`에서 관리한다.
- 세션 녹화와 chunk 업로드 흐름은 `src/pages/study-session.tsx`와 `src/utils/dualCamManager.ts`를 함께 확인한다.
- API base URL은 `import.meta.env.VITE_API_BASE_URL`을 사용한다. 실제 환경값은 `.env.local` 등 gitignore된 환경 파일이나 배포 환경에서만 주입한다.
- 현재 `package.json`에는 `build`와 `dev` script만 있다. lint script가 없으면 통합 검증에서 lint는 `SKIP`으로 보고한다.
- 프론트엔드 검증 명령은 다음과 같다.

```powershell
npm run build
```
