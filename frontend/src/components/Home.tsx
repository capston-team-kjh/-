interface HomeProps {
  onNavigate: (page: 'home' | 'login' | 'signup' | 'dashboard' | 'learning' | 'result-list' | 'result-detail' | 'settings' | 'history-delete') => void;
}

export function Home({ onNavigate }: HomeProps) {
  return (
    <div className="min-h-screen border-2 border-gray-800">
      {/* Header */}
      <header className="border-b-2 border-gray-800 p-6 flex justify-between items-center">
        <div className="w-32 h-12 border-2 border-gray-600 flex items-center justify-center">
          <span className="text-gray-700">LOGO</span>
        </div>
        <div className="flex gap-4">
          <button 
            onClick={() => onNavigate('login')}
            className="px-4 py-2 border-2 border-gray-600 hover:bg-gray-100"
          >
            로그인
          </button>
          <button 
            onClick={() => onNavigate('signup')}
            className="px-4 py-2 border-2 border-gray-600 hover:bg-gray-100"
          >
            회원가입
          </button>
        </div>
      </header>

      {/* Main Content */}
      <main className="flex flex-col items-center justify-center" style={{ minHeight: 'calc(100vh - 120px)' }}>
        <div className="text-center max-w-2xl mx-auto px-4">
          <h1 className="mb-4 pb-2 border-b-2 border-gray-400">
            학습 집중도 분석 및 피드백 시스템
          </h1>
          <p className="text-gray-600 mb-8">
            AI 기반 학습 집중도 분석으로 효과적인 학습 습관을 형성하세요
          </p>
          <button 
            onClick={() => onNavigate('login')}
            className="px-8 py-4 border-2 border-gray-800 hover:bg-gray-100"
          >
            시작하기
          </button>
        </div>
      </main>
    </div>
  );
}
