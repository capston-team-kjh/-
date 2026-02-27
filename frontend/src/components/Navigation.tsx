interface NavigationProps {
  currentPage: string;
  onNavigate: (page: 'home' | 'login' | 'signup' | 'dashboard' | 'learning' | 'result-list' | 'result-detail' | 'settings') => void;
  onLogout: () => void;
}

export function Navigation({ currentPage, onNavigate, onLogout }: NavigationProps) {
  return (
    <nav className="border-b-2 border-gray-800 p-6 flex justify-between items-center">
      <div className="flex gap-6">
        <button
          onClick={() => onNavigate('dashboard')}
          className={`px-4 py-2 border-2 ${
            currentPage === 'dashboard' ? 'border-gray-800 bg-gray-200' : 'border-gray-400'
          } hover:bg-gray-100`}
        >
          대시보드
        </button>
        <button
          onClick={() => onNavigate('learning')}
          className={`px-4 py-2 border-2 ${
            currentPage === 'learning' ? 'border-gray-800 bg-gray-200' : 'border-gray-400'
          } hover:bg-gray-100`}
        >
          학습하기
        </button>
        <button
          onClick={() => onNavigate('result-list')}
          className={`px-4 py-2 border-2 ${
            currentPage === 'result-list' ? 'border-gray-800 bg-gray-200' : 'border-gray-400'
          } hover:bg-gray-100`}
        >
          분석 결과
        </button>
        <button
          onClick={() => onNavigate('settings')}
          className={`px-4 py-2 border-2 ${
            currentPage === 'settings' ? 'border-gray-800 bg-gray-200' : 'border-gray-400'
          } hover:bg-gray-100`}
        >
          설정
        </button>
      </div>
      <button
        onClick={onLogout}
        className="px-4 py-2 border-2 border-gray-600 hover:bg-gray-100"
      >
        로그아웃
      </button>
    </nav>
  );
}
