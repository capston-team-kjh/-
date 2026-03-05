import { Navigation } from './Navigation';
import { useEffect, useState } from 'react';

interface ResultDetailProps {
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
  resultId: string | null;
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

function num(v: any, fallback = 0) {
  const n = Number(v);
  return Number.isFinite(n) ? n : fallback;
}

export function ResultDetail({ onNavigate, onLogout, resultId }: ResultDetailProps) {
  const [data, setData] = useState<any>(null);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    const fetchDetail = async () => {
      const token = localStorage.getItem('accessToken') || '';
      const headers: Record<string, string> = token ? { Authorization: `Bearer ${token}` } : {};

      setLoading(true);

      try {
        const urls = [`/api/v1/results/${resultId}`, `/api/results/${resultId}`];
        const response = await fetchWithFallback(urls, { headers });

        if (response && response.ok) {
          const json = await safeJson(response);
          setData(json);
        } else {
          setData(null);
        }
      } catch (error) {
        console.error('Result Detail Fetch Error:', error);
        setData(null);
      } finally {
        setLoading(false);
      }
    };

    if (resultId) fetchDetail();
    else {
      setLoading(false);
      setData(null);
    }
  }, [resultId]);

  if (loading) return <div className="p-10 text-center">데이터 분석 결과를 불러오는 중...</div>;
  if (!data) return <div className="p-10 text-center">데이터가 없습니다.</div>;

  // 백엔드마다 summary 키가 다를 수 있어서 안전 처리
  const summary = data.summary ?? data.data?.summary ?? data;
  const totalTimeMin = num(summary?.total_time_min ?? summary?.totalTimeMin ?? summary?.duration_min, 0);
  const focusRatio = num(summary?.focus_ratio ?? summary?.focusRatio ?? summary?.avg_focus_score, 0);

  return (
    <div className="min-h-screen border-2 border-gray-800">
      <Navigation currentPage="result-detail" onNavigate={onNavigate} onLogout={onLogout} />

      <div className="border-b-2 border-gray-800 p-6">
        <h1 className="text-center">결과 상세</h1>
      </div>

      <main className="p-8">
        <div className="max-w-5xl mx-auto space-y-6">
          <div className="border-2 border-gray-600 p-6">
            <h2 className="mb-4 pb-2 border-b border-gray-400">요약 지표</h2>
            <div className="grid grid-cols-4 gap-4">
              <div className="border-2 border-gray-400 p-4">
                <div className="text-gray-600 text-sm mb-2">총 학습시간</div>
                <div className="text-gray-800">{totalTimeMin}m</div>
              </div>
              <div className="border-2 border-gray-400 p-4">
                <div className="text-gray-600 text-sm mb-2">집중 비율</div>
                <div className="text-gray-800">{focusRatio}%</div>
              </div>
              <div className="border-2 border-gray-400 p-4">
                <div className="text-gray-600 text-sm mb-2">집중 시간</div>
                <div className="text-gray-800">-</div>
              </div>
              <div className="border-2 border-gray-400 p-4">
                <div className="text-gray-600 text-sm mb-2">비집중 시간</div>
                <div className="text-gray-800">-</div>
              </div>
            </div>
          </div>

          <div className="border-2 border-gray-600 p-6">
            <h2 className="mb-4 pb-2 border-b border-gray-400">집중도 그래프 (타임라인)</h2>
            <div className="border-2 border-gray-400 p-8 bg-gray-50">
              <div className="flex gap-4">
                <div className="flex flex-col justify-between text-gray-600 text-sm" style={{ height: '240px' }}>
                  <div>100%</div>
                  <div>75%</div>
                  <div>50%</div>
                  <div>25%</div>
                  <div>0%</div>
                </div>

                <div className="flex-1 border-2 border-gray-600 relative" style={{ height: '240px' }}>
                  <div className="absolute inset-0">
                    <div className="h-1/4 border-b border-gray-300"></div>
                    <div className="h-1/4 border-b border-gray-300"></div>
                    <div className="h-1/4 border-b border-gray-300"></div>
                    <div className="h-1/4 border-b border-gray-300"></div>
                  </div>

                  <div className="absolute inset-0 flex items-end px-4 pb-4">
                    <div className="flex-1 flex items-end justify-around">
                      <div className="w-2 bg-gray-800" style={{ height: '70%' }}></div>
                      <div className="w-2 bg-gray-800" style={{ height: '85%' }}></div>
                      <div className="w-2 bg-gray-800" style={{ height: '65%' }}></div>
                      <div className="w-2 bg-gray-800" style={{ height: '90%' }}></div>
                      <div className="w-2 bg-gray-800" style={{ height: '80%' }}></div>
                      <div className="w-2 bg-gray-800" style={{ height: '75%' }}></div>
                      <div className="w-2 bg-gray-800" style={{ height: '95%' }}></div>
                      <div className="w-2 bg-gray-800" style={{ height: '88%' }}></div>
                      <div className="w-2 bg-gray-800" style={{ height: '82%' }}></div>
                      <div className="w-2 bg-gray-800" style={{ height: '78%' }}></div>
                    </div>
                  </div>
                </div>
              </div>

              <div className="ml-12 mt-2 flex justify-between text-gray-600 text-sm">
                <div>-</div>
                <div>-</div>
                <div>-</div>
                <div>-</div>
                <div>-</div>
              </div>
            </div>
          </div>

          <div className="border-2 border-gray-600 p-6">
            <h2 className="mb-4 pb-2 border-b border-gray-400">습관 행동 요약</h2>
            <div className="space-y-3">
              <div className="border-2 border-gray-400 p-4">
                <div className="flex justify-between items-center mb-2">
                  <span className="text-gray-700">자세 변화 횟수</span>
                  <span className="text-gray-800">-</span>
                </div>
                <div className="text-gray-600 text-sm">-</div>
              </div>
              <div className="border-2 border-gray-400 p-4">
                <div className="flex justify-between items-center mb-2">
                  <span className="text-gray-700">시선 이탈 횟수</span>
                  <span className="text-gray-800">-</span>
                </div>
                <div className="text-gray-600 text-sm">-</div>
              </div>
              <div className="border-2 border-gray-400 p-4">
                <div className="flex justify-between items-center mb-2">
                  <span className="text-gray-700">휴식 시간</span>
                  <span className="text-gray-800">-</span>
                </div>
                <div className="text-gray-600 text-sm">-</div>
              </div>
            </div>
          </div>

          <div className="text-center pt-4">
            <button
              onClick={() => onNavigate('result-list')}
              className="px-6 py-3 border-2 border-gray-600 hover:bg-gray-100"
            >
              목록으로 돌아가기
            </button>
          </div>
        </div>
      </main>
    </div>
  );
}