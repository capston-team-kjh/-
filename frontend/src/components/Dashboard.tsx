import { Navigation } from './Navigation';

interface DashboardProps {
  onNavigate: (page: 'home' | 'login' | 'signup' | 'dashboard' | 'learning' | 'result-list' | 'result-detail' | 'settings') => void;
  onLogout: () => void;
  onViewResult: (resultId: string) => void;
}

export function Dashboard({ onNavigate, onLogout, onViewResult }: DashboardProps) {
  const mockResults = [
    { id: '1', date: '2025-12-17', time: '14:30', duration: '2h 15m', score: 85 },
    { id: '2', date: '2025-12-16', time: '10:00', duration: '1h 45m', score: 78 },
    { id: '3', date: '2025-12-15', time: '15:20', duration: '3h 00m', score: 92 },
  ];

  return (
    <div className="min-h-screen border-2 border-gray-800">
      <Navigation 
        currentPage="dashboard" 
        onNavigate={onNavigate}
        onLogout={onLogout}
      />

      {/* Page Title */}
      <div className="border-b-2 border-gray-800 p-6">
        <h1 className="text-center">대시보드</h1>
      </div>

      {/* Main Content */}
      <main className="p-8">
        {/* Summary Cards */}
        <div className="grid grid-cols-2 gap-6 mb-8">
          {/* Daily Summary */}
          <div className="border-2 border-gray-600 p-6">
            <h2 className="mb-4 pb-2 border-b border-gray-400">하루 전체 요약</h2>
            <div className="space-y-3">
              <div className="flex justify-between border-b border-gray-300 pb-2">
                <span className="text-gray-700">오늘 학습 시간</span>
                <span className="text-gray-700">2h 15m</span>
              </div>
              <div className="flex justify-between border-b border-gray-300 pb-2">
                <span className="text-gray-700">평균 집중도</span>
                <span className="text-gray-700">85%</span>
              </div>
              <div className="flex justify-between">
                <span className="text-gray-700">집중 세션</span>
                <span className="text-gray-700">3회</span>
              </div>
            </div>
          </div>

          {/* Weekly/Monthly Summary */}
          <div className="border-2 border-gray-600 p-6">
            <h2 className="mb-4 pb-2 border-b border-gray-400">주간/월간 요약</h2>
            <div className="space-y-3">
              <div className="flex justify-between border-b border-gray-300 pb-2">
                <span className="text-gray-700">주간 학습 시간</span>
                <span className="text-gray-700">14h 30m</span>
              </div>
              <div className="flex justify-between border-b border-gray-300 pb-2">
                <span className="text-gray-700">주간 평균 집중도</span>
                <span className="text-gray-700">82%</span>
              </div>
              <div className="flex justify-between">
                <span className="text-gray-700">월간 학습 일수</span>
                <span className="text-gray-700">18일</span>
              </div>
            </div>
          </div>
        </div>

        {/* Recent Results */}
        <div className="border-2 border-gray-600 p-6">
          <h2 className="mb-4 pb-2 border-b border-gray-400">최근 분석 결과</h2>
          <div className="space-y-3">
            {mockResults.map((result) => (
              <div 
                key={result.id}
                className="border-2 border-gray-400 p-4 flex justify-between items-center hover:bg-gray-50"
              >
                <div className="flex gap-8">
                  <div className="w-24">
                    <div className="text-gray-600 text-sm">날짜</div>
                    <div className="text-gray-800">{result.date}</div>
                  </div>
                  <div className="w-20">
                    <div className="text-gray-600 text-sm">시간</div>
                    <div className="text-gray-800">{result.time}</div>
                  </div>
                  <div className="w-24">
                    <div className="text-gray-600 text-sm">학습시간</div>
                    <div className="text-gray-800">{result.duration}</div>
                  </div>
                  <div className="w-20">
                    <div className="text-gray-600 text-sm">점수</div>
                    <div className="text-gray-800">{result.score}점</div>
                  </div>
                </div>
                <button 
                  onClick={() => onViewResult(result.id)}
                  className="px-4 py-2 border-2 border-gray-600 hover:bg-gray-100"
                >
                  상세 보기
                </button>
              </div>
            ))}
          </div>
        </div>
      </main>
    </div>
  );
}
