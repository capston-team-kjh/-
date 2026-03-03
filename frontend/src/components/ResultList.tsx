import { Navigation } from './Navigation';
import { useEffect, useState } from 'react';

interface ResultListProps {
  onNavigate: (page: 'home' | 'login' | 'signup' | 'dashboard' | 'learning' | 'result-list' | 'result-detail' | 'settings' | 'history-delete') => void;
  onLogout: () => void;
  onViewResult: (resultId: string) => void;
}

export function ResultList({ onNavigate, onLogout, onViewResult }: ResultListProps) {
  const [results, setResults] = useState<any[]>([]);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    const fetchResults = async () => {
      const token = localStorage.getItem('accessToken');
      try {
        const response = await fetch('http://localhost:5000/api/results?page=1&size=10', {
          headers: { 'Authorization': `Bearer ${token}` }
        });
        if (response.ok) {
          const data = await response.json();
          setResults(data.items); // Use 'items' from teammate's spec
        }
      } catch (error) {
        console.error("List Fetch Error:", error);
      } finally {
        setLoading(false);
      }
    };
    fetchResults();
  }, []);

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
            {loading ? <p className="text-center">로딩 중...</p> : 
              results.map((result) => (
                <div key={result.result_id} className="grid grid-cols-6 gap-4 p-4 border-2 border-gray-400 hover:bg-gray-50 items-center">
                  <div className="text-gray-800">{result.date}</div>
                  <div className="text-gray-800">{result.time}</div>
                  <div className="text-gray-800">{result.duration}</div>
                  <div className="text-gray-800">{result.score}점</div>
                  <div className="text-gray-800">{result.status}</div>
                  <div>
                    <button 
                      onClick={() => onViewResult(result.result_id)} // UUID 전달
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
