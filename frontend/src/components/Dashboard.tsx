import { Navigation } from './Navigation';
import { useEffect, useState} from 'react';

interface DashboardProps {
  onNavigate: (page: 'home' | 'login' | 'signup' | 'dashboard' | 'learning' | 'result-list' | 'result-detail' | 'settings' | 'history-delete') => void;
  userId: string | null;
  onLogout: () => void;
  onViewResult: (resultId: string) => void;
}

export function Dashboard({ onNavigate, userId, onLogout, onViewResult }: DashboardProps) {

  const [dailyData, setDailyData] = useState<any>(null);
  const [summaryData, setSummaryData] = useState<any>(null);
  const [recentResults, setRecentResults] = useState<any[]>([]);
  const [loading, setLoading] = useState(true);   

  const formatDuration = (mins: number) => {
    const h = Math.floor(mins / 60);
    const m = mins % 60;
    return h > 0 ? `${h}h ${m}m` : `${m}m`;
  };

  useEffect(() => {
    const fetchDashboardData = async () => {
      const token = localStorage.getItem('accessToken');
      const today = new Date().toISOString().split('T')[0]; // YYYY-MM-DD

      try {
        // Execute all three requests in parallel for efficiency
        const [dailyRes, summaryRes, recentRes] = await Promise.all([
          fetch(`http://localhost:5000/api/dashboard/daily?date=${today}`, {
            headers: { 'Authorization': `Bearer ${token}` }
          }),
          fetch(`http://localhost:5000/api/dashboard/summary?range=weekly`, {
            headers: { 'Authorization': `Bearer ${token}` }
          }),
          fetch(`http://localhost:5000/api/results/recent?size=3`, {
            headers: { 'Authorization': `Bearer ${token}` }
          })
        ]);

        if (dailyRes.ok && summaryRes.ok && recentRes.ok) {
          setDailyData(await dailyRes.json()); //
          setSummaryData(await summaryRes.json()); //
          const recentJson = await recentRes.json();
          setRecentResults(recentJson.items); // Use 'items' key from teammate's spec
        }
      } catch (error) {
        console.error("Dashboard Fetch Error:", error);
      } finally {
        setLoading(false);
      }
    };

    fetchDashboardData();
  }, []);

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
        {/* Dashboard.tsx - Boxed Summary Section */}
        <div className="grid grid-cols-2 gap-6 mb-8">
          {/* Left Box: Daily Summary */}
          <div className="border-2 border-gray-600 p-6 bg-white">
            <h2 className="mb-4 pb-2 border-b border-gray-400 font-bold text-gray-800">오늘의 요약</h2>
            <div className="space-y-3">
              <div className="flex justify-between border-b border-gray-200 pb-2">
                <span className="text-gray-600">오늘 학습 시간</span>
                <span className="text-gray-800 font-medium">
                  {dailyData ? formatDuration(dailyData.total_study_min) : '0m'}
                </span>
              </div>
              <div className="flex justify-between border-b border-gray-200 pb-2">
                <span className="text-gray-600">평균 집중도</span>
                <span className="text-gray-800 font-medium">
                  {dailyData?.avg_focus_score || 0}%
                </span>
              </div>
              <div className="flex justify-between">
                <span className="text-gray-600">집중 세션</span>
                <span className="text-gray-800 font-medium">
                  {dailyData?.session_count || 0}회
                </span>
              </div>
            </div>
          </div>

          {/* Right Box: Weekly/Monthly Summary */}
          <div className="border-2 border-gray-600 p-6 bg-white">
            <h2 className="mb-4 pb-2 border-b border-gray-400 font-bold text-gray-800">누적 통계</h2>
            <div className="space-y-3">
              <div className="flex justify-between border-b border-gray-200 pb-2">
                <span className="text-gray-600">주간 학습 시간</span>
                <span className="text-gray-800 font-medium">
                  {summaryData ? formatDuration(summaryData.total_study_min) : '0m'}
                </span>
              </div>
              <div className="flex justify-between border-b border-gray-200 pb-2">
                <span className="text-gray-600">주간 평균 집중도</span>
                <span className="text-gray-800 font-medium">
                  {summaryData?.avg_focus_score || 0}%
                </span>
              </div>
              <div className="flex justify-between">
                <span className="text-gray-600">월간 학습 일수</span>
                <span className="text-gray-800 font-medium">
                  {summaryData?.active_days || 0}일
                </span>
              </div>
            </div>
          </div>
        </div>

        {/* Recent Results */}
        <div className="border-2 border-gray-600 p-6">
          <h2 className="mb-4 pb-2 border-b border-gray-400">최근 분석 결과</h2>
          <div className="space-y-3">
          {recentResults.map((result) => (
            <div key={result.result_id} className="border-2 border-gray-400 p-4 flex justify-between items-center hover:bg-gray-50 bg-white">
              
              {/* Left Section: Data Grid */}
              <div className="grid grid-cols-4 gap-8 flex-1 max-w-2xl">
                {/* Date Stack */}
                <div>
                  <p className="text-[10px] text-gray-500 uppercase tracking-wider mb-1">날짜</p>
                  <p className="text-sm text-gray-800 font-medium">{result.date}</p>
                </div>
                
                {/* Time Stack */}
                <div>
                  <p className="text-[10px] text-gray-500 uppercase tracking-wider mb-1">시간</p>
                  <p className="text-sm text-gray-800">{result.start_time}</p>
                </div>
                
                {/* Duration Stack */}
                <div>
                  <p className="text-[10px] text-gray-500 uppercase tracking-wider mb-1">학습시간</p>
                  <p className="text-sm text-gray-800">{formatDuration(result.duration_min)}</p>
                </div>
                
                {/* Score Stack */}
                <div>
                  <p className="text-[10px] text-gray-500 uppercase tracking-wider mb-1">점수</p>
                  <p className="text-sm text-gray-800 font-bold">{result.focus_score}점</p>
                </div>
              </div>

              {/* Right Section: Action Button */}
              <div className="ml-4">
                <button 
                  onClick={() => onViewResult(result.result_id)}
                  className="px-6 py-2 border-2 border-gray-800 hover:bg-gray-800 hover:text-white transition-all text-xs font-bold"
                >
                  상세 보기
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
