import { Navigation } from './Navigation';
import { useEffect, useState } from 'react';

interface ResultListProps {
  onNavigate: (
    page:
      | 'home'
      | 'login'
      | 'signup'
      | 'dashboard'
      | 'learning'
      | 'result-list'
      | 'result-detail'
      | 'settings'
      | 'history-delete'
  ) => void;
  onLogout: () => void;
  onViewResult: (resultId: string) => void;
}

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

export function ResultList({ onNavigate, onLogout, onViewResult }: ResultListProps) {
  const [results, setResults] = useState<any[]>([]);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    const fetchResults = async () => {
      const token = localStorage.getItem('accessToken') || '';
      const headers: Record<string, string> = token ? { Authorization: `Bearer ${token}` } : {};

      try {
        const urls = ['/api/v1/results?page=1&size=10', '/api/results?page=1&size=10'];
        const response = await fetchWithFallback(urls, { headers });

        if (response && response.ok) {
          const data = await safeJson(response);
          const items = data.items ?? data.results ?? data.data ?? [];
          setResults(items);
        } else {
          setResults([]);
        }
      } catch (error) {
        console.error('List Fetch Error:', error);
        setResults([]);
      } finally {
        setLoading(false);
      }
    };

    fetchResults();
  }, []);

  return (
    <div className="min-h-screen border-2 border-gray-800">
      <Navigation currentPage="result-list" onNavigate={onNavigate} onLogout={onLogout} />

      <div className="border-b-2 border-gray-800 p-6">
        <h1 className="text-center">분석 결과 목록</h1>
      </div>

      <main className="p-8">
        <div className="border-2 border-gray-600 p-6">
          <div className="grid grid-cols-6 gap-4 pb-3 border-b-2 border-gray-400 mb-4">
            <div className="text-gray-700">날짜</div>
            <div className="text-gray-700">시간</div>
            <div className="text-gray-700">학습시간</div>
            <div className="text-gray-700">점수</div>
            <div className="text-gray-700">상태</div>
            <div className="text-gray-700">작업</div>
          </div>

          <div className="space-y-3">
            {loading ? (
              <p className="text-center">로딩 중...</p>
            ) : results.length === 0 ? (
              <p className="text-center text-gray-500 italic p-10">결과가 없습니다.</p>
            ) : (
              results.map((result: AnyObj) => {
                const resultId = String(result.result_id ?? result.id ?? '');
                const date = pick(result.date);
                const time = pick(result.time ?? result.start_time);
                const duration = pick(result.duration ?? result.duration_min ?? result.total_time_min);
                const score = pick(result.score ?? result.focus_score ?? result.focusScore, 0);
                const status = pick(result.status ?? result.state, '-');

                return (
                  <div
                    key={resultId}
                    className="grid grid-cols-6 gap-4 p-4 border-2 border-gray-400 hover:bg-gray-50 items-center"
                  >
                    <div className="text-gray-800">{date}</div>
                    <div className="text-gray-800">{time}</div>
                    <div className="text-gray-800">{String(duration)}</div>
                    <div className="text-gray-800">{String(score)}점</div>
                    <div className="text-gray-800">{String(status)}</div>
                    <div>
                      <button
                        onClick={() => onViewResult(resultId)}
                        className="px-4 py-2 border-2 border-gray-600 hover:bg-gray-100"
                      >
                        상세보기
                      </button>
                    </div>
                  </div>
                );
              })
            )}
          </div>
        </div>
      </main>
    </div>
  );
}