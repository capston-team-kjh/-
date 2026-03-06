import { useEffect, useState } from 'react';
import { Navigation } from './Navigation';

type AnyObj = Record<string, any>;

async function safeJson(res: Response) {
  return res.json().catch(() => ({} as AnyObj));
}

async function fetchWithFallback(urls: string[], init?: RequestInit) {
  let lastRes: Response | null = null;

  for (const url of urls) {
    try {
      const res = await fetch(url, init);
      lastRes = res;
      if (res.status === 404) continue;
      return res;
    } catch {
      continue;
    }
  }

  return lastRes;
}

function pick(v: any, fallback = '-') {
  return v === undefined || v === null || v === '' ? fallback : v;
}

export function HistoryDelete({ onNavigate, onLogout }: any) {
  const [results, setResults] = useState<any[]>([]);
  const [loading, setLoading] = useState(true);

  const fetchResults = async () => {
    const token = localStorage.getItem('accessToken') || '';
    const headers: Record<string, string> = token ? { Authorization: `Bearer ${token}` } : {};

    setLoading(true);

    const urls = ['/api/v1/results?page=1&size=20', '/api/results?page=1&size=20'];
    const res = await fetchWithFallback(urls, { headers });

    if (res && res.ok) {
      const data = await safeJson(res);
      const items = data.items ?? data.results ?? data.data ?? [];
      setResults(items);
    } else {
      setResults([]);
    }

    setLoading(false);
  };

  useEffect(() => {
    fetchResults();
  }, []);

  const handleDelete = async (resultId: string) => {
    if (!window.confirm('이 학습 기록을 정말 삭제하시겠습니까?')) return;

    const token = localStorage.getItem('accessToken') || '';
    const headers: Record<string, string> = token ? { Authorization: `Bearer ${token}` } : {};

    const urls = [`/api/v1/results/${resultId}`, `/api/results/${resultId}`];
    const res = await fetchWithFallback(urls, { method: 'DELETE', headers });

    if (res && res.ok) {
      alert('삭제되었습니다.');
      fetchResults();
      return;
    }

    const err = res ? await safeJson(res) : {};
    alert(err.detail || err.error || '삭제 실패');
  };

  return (
    <div className="min-h-screen border-2 border-gray-800">
      <Navigation currentPage="history-delete" onNavigate={onNavigate} onLogout={onLogout} />

      <div className="border-b-2 border-gray-800 p-6 flex justify-between items-center">
        <button
          onClick={() => onNavigate('settings')}
          className="px-4 py-2 border-2 border-gray-800 hover:bg-gray-100 font-bold text-sm"
        >
          ← 뒤로
        </button>
        <h1 className="flex-1 text-center text-xl font-bold">학습 기록 관리 (삭제)</h1>
        <div className="w-16"></div>
      </div>

      <main className="p-8">
        <div className="border-2 border-gray-600 p-6 bg-white">
          <div className="grid grid-cols-6 gap-4 pb-3 border-b-2 border-gray-400 mb-4 font-bold text-gray-700 text-center">
            <div>날짜</div>
            <div>시간</div>
            <div>학습시간</div>
            <div>점수</div>
            <div>상태</div>
            <div>작업</div>
          </div>

          <div className="space-y-3">
            {loading ? (
              <p className="text-center p-10 text-gray-500 italic">로딩 중...</p>
            ) : results.length > 0 ? (
              results.map((result: AnyObj) => {
                const resultId = String(result.result_id ?? result.id ?? '');
                const date = pick(result.date);
                const time = pick(result.time ?? result.start_time);
                const duration = pick(result.duration ?? result.duration_min ?? result.total_time_min);
                const score = pick(result.score ?? result.focus_score ?? result.focusScore, 0);

                return (
                  <div
                    key={resultId}
                    className="grid grid-cols-6 gap-4 p-4 border-2 border-gray-400 items-center text-center hover:bg-red-50 transition-colors"
                  >
                    <div className="text-gray-800">{date}</div>
                    <div className="text-gray-800">{time}</div>
                    <div className="text-gray-800">{String(duration)}</div>
                    <div className="text-gray-800">{String(score)}점</div>
                    <div className="text-red-500 font-bold text-sm">삭제 가능</div>
                    <div>
                      <button
                        onClick={() => handleDelete(resultId)}
                        className="px-4 py-2 border-2 border-red-600 text-red-600 hover:bg-red-600 hover:text-white font-bold transition-all text-sm"
                      >
                        기록 삭제
                      </button>
                    </div>
                  </div>
                );
              })
            ) : (
              <p className="text-center p-10 text-gray-500 italic">삭제할 학습 기록이 없습니다.</p>
            )}
          </div>
        </div>
      </main>
    </div>
  );
}