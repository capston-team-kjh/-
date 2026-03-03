// DeleteHistory.tsx
import { useEffect, useState } from 'react';
import { Navigation } from './Navigation';

export function HistoryDelete({ onNavigate, onLogout }: any) {
  const [results, setResults] = useState<any[]>([]);

  const fetchResults = async () => {
    const token = localStorage.getItem('accessToken');
    const res = await fetch('http://localhost:5000/api/results?page=1&size=20', {
      headers: { 'Authorization': `Bearer ${token}` }
    });
    const data = await res.json();
    setResults(data.items);
  };

  useEffect(() => { fetchResults(); }, []);

  const handleDelete = async (resultId: string) => {
    if (!window.confirm("이 학습 기록을 정말 삭제하시겠습니까?")) return;

    const token = localStorage.getItem('accessToken');
    const res = await fetch(`http://localhost:5000/api/results/${resultId}`, {
      method: 'DELETE',
      headers: { 'Authorization': `Bearer ${token}` }
    });

    if (res.ok) {
        alert("삭제되었습니다.");
        fetchResults(); // Refresh list
    }
  };

  return (
    <div className="min-h-screen border-2 border-gray-800">
      <Navigation currentPage="settings" onNavigate={onNavigate} onLogout={onLogout} />
  
      {/* Page Title */}
      <div className="border-b-2 border-gray-800 p-6 flex justify-between items-center">
        <button 
          onClick={() => onNavigate('settings')} 
          className="px-4 py-2 border-2 border-gray-800 hover:bg-gray-100 font-bold text-sm"
        >
          ← 뒤로
        </button>
        <h1 className="flex-1 text-center text-xl font-bold">학습 기록 관리 (삭제)</h1>
        <div className="w-16"></div> {/* Spacer for center alignment */}
      </div>
  
      <main className="p-8">
        <div className="border-2 border-gray-600 p-6 bg-white">
          {/* Unified Table Header - Matches ResultList */}
          <div className="grid grid-cols-6 gap-4 pb-3 border-b-2 border-gray-400 mb-4 font-bold text-gray-700 text-center">
            <div>날짜</div>
            <div>시간</div>
            <div>학습시간</div>
            <div>점수</div>
            <div>상태</div>
            <div>작업</div>
          </div>
  
          {/* Table Rows */}
          <div className="space-y-3">
            {results.length > 0 ? results.map((result) => (
              <div 
                key={result.result_id} 
                className="grid grid-cols-6 gap-4 p-4 border-2 border-gray-400 items-center text-center hover:bg-red-50 transition-colors"
              >
                <div className="text-gray-800">{result.date}</div>
                <div className="text-gray-800">{result.time}</div>
                <div className="text-gray-800">{result.duration}</div>
                <div className="text-gray-800">{result.score}점</div>
                <div className="text-red-500 font-bold text-sm">삭제 가능</div>
                <div>
                  <button 
                    onClick={() => handleDelete(result.result_id)}
                    className="px-4 py-2 border-2 border-red-600 text-red-600 hover:bg-red-600 hover:text-white font-bold transition-all text-sm"
                  >
                    기록 삭제
                  </button>
                </div>
              </div>
            )) : (
              <p className="text-center p-10 text-gray-500 italic">삭제할 학습 기록이 없습니다.</p>
            )}
          </div>
        </div>
      </main>
    </div>
  );
}