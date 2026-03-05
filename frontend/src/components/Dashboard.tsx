import { Navigation } from './Navigation';
import { useEffect, useState } from 'react';

interface DashboardProps {
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
  userId: string | null;
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

      // 404면 다음 후보로 넘어감
      if (res.status === 404) continue;

      return res;
    } catch {
      // 네트워크 에러면 다음 후보로 넘어감
      continue;
    }
  }

  return lastRes;
}

function getNumber(v: any, fallback = 0) {
  const n = Number(v);
  return Number.isFinite(n) ? n : fallback;
}

export function Dashboard({ onNavigate, userId, onLogout, onViewResult }: DashboardProps) {
  const [dailyData, setDailyData] = useState<any>(null);
  const [summaryData, setSummaryData] = useState<any>(null);
  const [recentResults, setRecentResults] = useState<any[]>([]);
  const [loading, setLoading] = useState(true);
  const [errorMsg, setErrorMsg] = useState<string>('');

  const formatDuration = (mins: number) => {
    const total = getNumber(mins, 0);
    const h = Math.floor(total / 60);
    const m = total % 60;
    return h > 0 ? `${h}h ${m}m` : `${m}m`;
  };

  const mapResultRow = (r: AnyObj) => {
    const result_id = String(r.result_id ?? r.id ?? r.resultId ?? '');
    const date = r.date ?? r.created_at ?? r.createdAt ?? '-';
    const start_time = r.start_time ?? r.time ?? r.startTime ?? '-';
    const duration_min = r.duration_min ?? r.duration ?? r.total_time_min ?? r.totalTimeMin ?? 0;
    const focus_score = r.focus_score ?? r.score ?? r.focusScore ?? 0;

    return {
      result_id,
      date,
      start_time,
      duration_min: getNumber(duration_min, 0),
      focus_score: getNumber(focus_score, 0),
    };
  };

  useEffect(() => {
    const fetchDashboardData = async () => {
      const token = localStorage.getItem('accessToken') || '';
      const today = new Date().toISOString().split('T')[0]; // YYYY-MM-DD

      setLoading(true);
      setErrorMsg('');

      const authHeaders: Record<string, string> = token
        ? { Authorization: `Bearer ${token}` }
        : {};

      try {
        // /api/v1 와 /api 둘 다 있을 수 있어서 fallback 후보 2개씩 둠
        const dailyUrls = [
          `/api/v1/dashboard/daily?date=${today}`,
          `/api/dashboard/daily?date=${today}`,
        ];
        const summaryUrls = [
          `/api/v1/dashboard/summary?range=weekly`,
          `/api/dashboard/summary?range=weekly`,
        ];
        const recentUrls = [
          `/api/v1/results/recent?size=3`,
          `/api/results/recent?size=3`,
        ];

        const [dailyRes, summaryRes, recentRes] = await Promise.all([
          fetchWithFallback(dailyUrls, { headers: authHeaders }),
          fetchWithFallback(summaryUrls, { headers: authHeaders }),
          fetchWithFallback(recentUrls, { headers: authHeaders }),
        ]);

        // daily
        if (dailyRes && dailyRes.ok) {
          const dailyJson = await safeJson(dailyRes);
          setDailyData(dailyJson);
        } else {
          setDailyData(null);
        }

        // summary
        if (summaryRes && summaryRes.ok) {
          const summaryJson = await safeJson(summaryRes);
          setSummaryData(summaryJson);
        } else {
          setSummaryData(null);
        }

        // recent
        if (recentRes && recentRes.ok) {
          const recentJson = await safeJson(recentRes);
          const items: AnyObj[] =
            recentJson.items ?? recentJson.results ?? recentJson.data ?? [];
          setRecentResults(items.map(mapResultRow).filter((x) => x.result_id));
        } else {
          setRecentResults([]);
        }

        // 둘 다 실패하면 메시지 하나 보여주기
        const okCount =
          (dailyRes?.ok ? 1 : 0) + (summaryRes?.ok ? 1 : 0) + (recentRes?.ok ? 1 : 0);
        if (okCount === 0) {
          setErrorMsg('대시보드 데이터를 불러오지 못했습니다. 백엔드 API 경로를 확인해줘.');
        }
      } catch (e) {
        console.error('Dashboard Fetch Error:', e);
        setErrorMsg('대시보드 요청 중 오류가 발생했습니다.');
      } finally {
        setLoading(false);
      }
    };

    fetchDashboardData();
  }, []);

  const todayTotalMin = getNumber(dailyData?.total_study_min ?? dailyData?.totalStudyMin, 0);
  const todayAvgFocus = getNumber(dailyData?.avg_focus_score ?? dailyData?.avgFocusScore, 0);
  const todaySessionCount = getNumber(dailyData?.session_count ?? dailyData?.sessionCount, 0);

  const weekTotalMin = getNumber(summaryData?.total_study_min ?? summaryData?.totalStudyMin, 0);
  const weekAvgFocus = getNumber(summaryData?.avg_focus_score ?? summaryData?.avgFocusScore, 0);
  const monthActiveDays = getNumber(summaryData?.active_days ?? summaryData?.activeDays, 0);

  return (
    <div className="min-h-screen border-2 border-gray-800">
      <Navigation currentPage="dashboard" onNavigate={onNavigate} onLogout={onLogout} />

      <div className="border-b-2 border-gray-800 p-6">
        <h1 className="text-center">대시보드</h1>
      </div>

      <main className="p-8">
        {loading && (
          <div className="mb-6 border-2 border-gray-400 p-4 text-center text-gray-600">
            로딩 중...
          </div>
        )}

        {!loading && errorMsg && (
          <div className="mb-6 border-2 border-gray-400 p-4 text-center text-gray-700">
            {errorMsg}
          </div>
        )}

        <div className="grid grid-cols-2 gap-6 mb-8">
          <div className="border-2 border-gray-600 p-6 bg-white">
            <h2 className="mb-4 pb-2 border-b border-gray-400 font-bold text-gray-800">
              오늘의 요약
            </h2>
            <div className="space-y-3">
              <div className="flex justify-between border-b border-gray-200 pb-2">
                <span className="text-gray-600">오늘 학습 시간</span>
                <span className="text-gray-800 font-medium">{formatDuration(todayTotalMin)}</span>
              </div>
              <div className="flex justify-between border-b border-gray-200 pb-2">
                <span className="text-gray-600">평균 집중도</span>
                <span className="text-gray-800 font-medium">{todayAvgFocus}%</span>
              </div>
              <div className="flex justify-between">
                <span className="text-gray-600">집중 세션</span>
                <span className="text-gray-800 font-medium">{todaySessionCount}회</span>
              </div>
            </div>
          </div>

          <div className="border-2 border-gray-600 p-6 bg-white">
            <h2 className="mb-4 pb-2 border-b border-gray-400 font-bold text-gray-800">
              누적 통계
            </h2>
            <div className="space-y-3">
              <div className="flex justify-between border-b border-gray-200 pb-2">
                <span className="text-gray-600">주간 학습 시간</span>
                <span className="text-gray-800 font-medium">{formatDuration(weekTotalMin)}</span>
              </div>
              <div className="flex justify-between border-b border-gray-200 pb-2">
                <span className="text-gray-600">주간 평균 집중도</span>
                <span className="text-gray-800 font-medium">{weekAvgFocus}%</span>
              </div>
              <div className="flex justify-between">
                <span className="text-gray-600">월간 학습 일수</span>
                <span className="text-gray-800 font-medium">{monthActiveDays}일</span>
              </div>
            </div>
          </div>
        </div>

        <div className="border-2 border-gray-600 p-6">
          <h2 className="mb-4 pb-2 border-b border-gray-400">최근 분석 결과</h2>

          <div className="space-y-3">
            {recentResults.length === 0 && !loading ? (
              <p className="text-center p-10 text-gray-500 italic">최근 결과가 없습니다.</p>
            ) : (
              recentResults.map((result) => (
                <div
                  key={result.result_id}
                  className="border-2 border-gray-400 p-4 flex justify-between items-center hover:bg-gray-50 bg-white"
                >
                  <div className="grid grid-cols-4 gap-8 flex-1 max-w-2xl">
                    <div>
                      <p className="text-[10px] text-gray-500 uppercase tracking-wider mb-1">날짜</p>
                      <p className="text-sm text-gray-800 font-medium">{result.date}</p>
                    </div>

                    <div>
                      <p className="text-[10px] text-gray-500 uppercase tracking-wider mb-1">시간</p>
                      <p className="text-sm text-gray-800">{result.start_time}</p>
                    </div>

                    <div>
                      <p className="text-[10px] text-gray-500 uppercase tracking-wider mb-1">학습시간</p>
                      <p className="text-sm text-gray-800">{formatDuration(result.duration_min)}</p>
                    </div>

                    <div>
                      <p className="text-[10px] text-gray-500 uppercase tracking-wider mb-1">점수</p>
                      <p className="text-sm text-gray-800 font-bold">{result.focus_score}점</p>
                    </div>
                  </div>

                  <div className="ml-4">
                    <button
                      onClick={() => onViewResult(result.result_id)}
                      className="px-6 py-2 border-2 border-gray-800 hover:bg-gray-800 hover:text-white transition-all text-xs font-bold"
                    >
                      상세 보기
                    </button>
                  </div>
                </div>
              ))
            )}
          </div>
        </div>
      </main>
    </div>
  );
}