import { Navigation } from './Navigation';

interface SettingsProps {
  onNavigate: (page: 'home' | 'login' | 'signup' | 'dashboard' | 'learning' | 'result-list' | 'result-detail' | 'settings') => void;
  onLogout: () => void;
}

export function Settings({ onNavigate, onLogout }: SettingsProps) {
  return (
    <div className="min-h-screen border-2 border-gray-800">
      <Navigation 
        currentPage="settings" 
        onNavigate={onNavigate}
        onLogout={onLogout}
      />

      {/* Page Title */}
      <div className="border-b-2 border-gray-800 p-6">
        <h1 className="text-center">설정</h1>
      </div>

      {/* Main Content */}
      <main className="p-8">
        <div className="max-w-3xl mx-auto">
          {/* My Info Section */}
          <div className="border-2 border-gray-600 p-6 mb-6">
            <h2 className="mb-4 pb-2 border-b border-gray-400">내 정보</h2>
            <div className="space-y-4">
              <div className="border-2 border-gray-400 p-4">
                <div className="text-gray-700 mb-2">프로필 정보</div>
                <div className="text-gray-600 text-sm">이메일, 이름 등 기본 정보</div>
              </div>
              <div className="border-2 border-gray-400 p-4">
                <div className="text-gray-700 mb-2">비밀번호 변경</div>
                <div className="text-gray-600 text-sm">비밀번호 변경 옵션</div>
              </div>
            </div>
          </div>

          {/* Data Management Section */}
          <div className="border-2 border-gray-600 p-6">
            <h2 className="mb-4 pb-2 border-b border-gray-400">데이터 관리</h2>
            <div className="space-y-4">
              <div className="border-2 border-gray-400 p-4">
                <div className="text-gray-700 mb-2">학습 기록 삭제</div>
                <div className="text-gray-600 text-sm">전체 또는 선택 기록 삭제</div>
              </div>
              <div className="border-2 border-gray-400 p-4">
                <div className="text-gray-700 mb-2">기록 보관/내보내기</div>
                <div className="text-gray-600 text-sm">학습 기록 백업 및 내보내기 (선택)</div>
              </div>
            </div>
          </div>
        </div>
      </main>
    </div>
  );
}