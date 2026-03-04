import { Navigation } from './Navigation';

interface ResultListProps {
  onNavigate: (page: 'home' | 'login' | 'signup' | 'dashboard' | 'learning' | 'result-list' | 'result-detail' | 'settings') => void;
  onLogout: () => void;
  onViewResult: (resultId: string) => void;
}

export function ResultList({ onNavigate, onLogout, onViewResult }: ResultListProps) {
  const mockResults = [
    { id: '1', date: '2025-12-17', time: '14:30', duration: '2h 15m', score: 85, status: '완료' },
    { id: '2', date: '2025-12-16', time: '10:00', duration: '1h 45m', score: 78, status: '완료' },
    { id: '3', date: '2025-12-15', time: '15:20', duration: '3h 00m', score: 92, status: '완료' },
    { id: '4', date: '2025-12-14', time: '09:15', duration: '2h 30m', score: 88, status: '완료' },
    { id: '5', date: '2025-12-13', time: '16:00', duration: '1h 20m', score: 73, status: '완료' },
    { id: '6', date: '2025-12-12', time: '11:30', duration: '2h 45m', score: 90, status: '완료' },
    { id: '7', date: '2025-12-11', time: '14:00', duration: '3h 15m', score: 95, status: '완료' },
  ];

  return (
    <div className="min-h-screen border-2 border-gray-800">
      <Navigation 
        currentPage="result-list" 
        onNavigate={onNavigate}
        onLogout={onLogout}
      />

      {/* Page Title */}
      <div className="border-b-2 border-gray-800 p-6">
        <h1 className="text-center">분석 결과 목록</h1>
      </div>

      {/* Main Content */}
      <main className="p-8">
        <div className="border-2 border-gray-600 p-6">
          {/* Table Header */}
          <div className="grid grid-cols-6 gap-4 pb-3 border-b-2 border-gray-400 mb-4">
            <div className="text-gray-700">날짜</div>
            <div className="text-gray-700">시간</div>
            <div className="text-gray-700">학습시간</div>
            <div className="text-gray-700">점수</div>
            <div className="text-gray-700">상태</div>
            <div className="text-gray-700">작업</div>
          </div>

          {/* Table Rows */}
          <div className="space-y-3">
            {mockResults.map((result) => (
              <div 
                key={result.id}
                className="grid grid-cols-6 gap-4 p-4 border-2 border-gray-400 hover:bg-gray-50 items-center"
              >
                <div className="text-gray-800">{result.date}</div>
                <div className="text-gray-800">{result.time}</div>
                <div className="text-gray-800">{result.duration}</div>
                <div className="text-gray-800">{result.score}점</div>
                <div className="text-gray-800">{result.status}</div>
                <div>
                  <button 
                    onClick={() => onViewResult(result.id)}
                    className="px-4 py-2 border-2 border-gray-600 hover:bg-gray-100"
                  >
                    상세보기
                  </button>
                </div>
              </div>
            ))}
          </div>
        </div>
      </main>
    </div>
  );
}
