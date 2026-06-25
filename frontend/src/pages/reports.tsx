import { useState, useEffect, useMemo } from "react"; 
import { Link } from "react-router";
import { ChevronRight, BarChart3, Clock, Target, Calendar, SlidersHorizontal, ArrowUpDown } from "lucide-react";
import {
  BarChart,
  Bar,
  LineChart,
  Line,
  XAxis,
  YAxis,
  CartesianGrid,
  Tooltip,
  ResponsiveContainer,
} from "recharts";

interface ReportItem {
  id: number;
  display_index: number;
  date: string;
  date_raw: string;
  duration_min: number;
  focus_score: number;
}

interface SummaryStats {
  total_hours: number;
  avg_focus_score: number;
  active_days: number;
  weekly_chart_data: Array<{ day: string; hours: number }>;
}

export function Reports() {
  // Calculate local date default placeholders (Past 7 Days)
  const getPastDateString = (daysAgo: number) => {
    const d = new Date();
    d.setDate(d.getDate() - daysAgo);
    
    const year = d.getFullYear();
    const month = String(d.getMonth() + 1).padStart(2, '0');
    const day = String(d.getDate()).padStart(2, '0');
    
    return `${year}-${month}-${day}`;
  };

  const [startDate, setStartDate] = useState(getPastDateString(7));
  const [endDate, setEndDate] = useState(getPastDateString(0));
  
  const [sessionsList, setSessionsList] = useState<ReportItem[]>([]);
  const [summaryStats, setSummaryStats] = useState<SummaryStats | null>(null);
  const [loading, setLoading] = useState(true);

  // Filter Panel States
  const [isFilterExpanded, setIsFilterExpanded] = useState(false);
  const [sortBy, setSortBy] = useState<"date_desc" | "date_asc" | "score_desc" | "score_asc">("date_desc");
  const [minScore, setMinScore] = useState<number>(0);

  const userId = localStorage.getItem("user_id");

  useEffect(() => {
    if (!userId) return;

    const fetchReportsData = async () => {
      try {
        setLoading(true);
        const headers = { "X-User-Id": userId };

        // Passing custom start and end calendar tags dynamically to the backend API
        const [summaryRes, listRes] = await Promise.all([
          fetch(`${import.meta.env.VITE_API_BASE_URL}/analytics/summary?start_date=${startDate}&end_date=${endDate}`, { headers }),
          fetch(`${import.meta.env.VITE_API_BASE_URL}/analytics/list`, { headers })
        ]);

        if (summaryRes.ok && listRes.ok) {
          setSummaryStats(await summaryRes.json());
          const listData = await listRes.json();
          setSessionsList(listData.items);
        }
      } catch (error) {
        console.error("Failed fetching reports grid data:", error);
      } finally {
        setLoading(false);
      }
    };

    fetchReportsData();
  }, [userId, startDate, endDate]); // Re-runs automatically whenever calendar values shift

  const formatDuration = (totalMinutes: number) => {
    const hours = Math.floor(totalMinutes / 60);
    const mins = totalMinutes % 60;
    return hours > 0 ? `${hours}h ${mins}m` : `${mins}m`;
  };

  // Apply Client-Side Filter & Sort Logic Dynamically across the chosen scope
  const processedSessions = useMemo(() => {
    // Filter out items that fall outside our calendar range AND score threshold
    let filtered = sessionsList.filter((s) => {
      const withinDateRange = s.date_raw >= startDate && s.date_raw <= endDate;
      const aboveMinScore = s.focus_score >= minScore;
      return withinDateRange && aboveMinScore;
    });

    // Sort the remaining records
    return filtered.sort((a, b) => {
      if (sortBy === "date_desc") return b.id - a.id;
      if (sortBy === "date_asc") return a.id - b.id;
      if (sortBy === "score_desc") return b.focus_score - a.focus_score;
      if (sortBy === "score_asc") return a.focus_score - b.focus_score;
      return 0;
    });
  }, [sessionsList, startDate, endDate, sortBy, minScore]);

  // Dynamic calculations for stat cards based *strictly* on current visible filtered sessions list rows
  const visibleCompletedSessionsCount = processedSessions.length;

  return (
    <div className="p-8 space-y-8 max-w-7xl mx-auto">
      {/* Header Layout */}
      <div className="flex flex-col md:flex-row md:items-center justify-between gap-4">
        <div>
          <h1 className="text-3xl font-bold text-foreground mb-1">상세 보고서</h1>
          <p className="text-muted-foreground">지정 기간 내 학습 활동 종합 리포트</p>
        </div>
        
        {/* Double Calendar Input Cluster Row Element */}
        <div className="flex items-center gap-2 bg-white p-2 rounded-xl border border-border shadow-sm">
          <input
            type="date"
            value={startDate}
            onChange={(e) => setStartDate(e.target.value)}
            className="p-1.5 text-sm font-medium border border-border rounded-md text-foreground focus:outline-none focus:ring-1 focus:ring-primary"
          />
          <span className="text-muted-foreground text-sm font-bold">~</span>
          <input
            type="date"
            value={endDate}
            onChange={(e) => setEndDate(e.target.value)}
            className="p-1.5 text-sm font-medium border border-border rounded-md text-foreground focus:outline-none focus:ring-1 focus:ring-primary"
          />
        </div>
      </div>

      {/* Stat Grid - Reflects selected calculations */}
      <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-4 gap-6">
        <StatCard
          icon={<Clock className="w-6 h-6" />}
          label="기간 내 학습 시간"
          value={`${summaryStats?.total_hours || 0} hrs`}
        />
        <StatCard
          icon={<BarChart3 className="w-6 h-6" />}
          label="기간 내 완료 세션"
          value={`${visibleCompletedSessionsCount}개`}
        />
        <StatCard
          icon={<Target className="w-6 h-6" />}
          label="기간 내 평균 집중도"
          value={`${summaryStats?.avg_focus_score || 0}%`}
        />
        <StatCard
          icon={<Calendar className="w-6 h-6" />}
          label="기간 내 활동 일수"
          value={`${summaryStats?.active_days || 0}일`}
        />
      </div>

      {/* Charts Section Dashboard Container */}
      <div className="grid grid-cols-1 lg:grid-cols-2 gap-6">
        <div className="bg-white rounded-2xl border border-border p-6">
          <h2 className="text-xl font-semibold mb-4">학습 시간 추이</h2>
          <ResponsiveContainer width="100%" height={250}>
            <BarChart data={summaryStats?.weekly_chart_data || []}>
              <defs>
                <linearGradient id="colorHoursBar" x1="0" y1="0" x2="0" y2="1">
                  <stop offset="5%" stopColor="#1a667a" stopOpacity={0.9} />
                  <stop offset="95%" stopColor="#1a667a" stopOpacity={0.6} />
                </linearGradient>
              </defs>
              <CartesianGrid strokeDasharray="3 3" stroke="#f0f0f0" />
              <XAxis dataKey="day" stroke="#888" fontSize={12} />
              <YAxis stroke="#888" fontSize={12} />
              <Tooltip contentStyle={{ backgroundColor: "#fff", border: "1px solid #e5e5e5", borderRadius: "8px" }} />
              <Bar dataKey="hours" fill="url(#colorHoursBar)" radius={[6, 6, 0, 0]} />
            </BarChart>
          </ResponsiveContainer>
        </div>

        <div className="bg-white rounded-2xl border border-border p-6">
          <h2 className="text-xl font-semibold mb-4">집중도 점수 추이</h2>
          <ResponsiveContainer width="100%" height={250}>
            {/* Draws chronological path lines mapped strictly over the processed timeline subset bounds */}
            <LineChart data={[...processedSessions].reverse()}>
              <CartesianGrid strokeDasharray="3 3" stroke="#f0f0f0" />
              <XAxis dataKey="display_index" tickFormatter={(v) => `#${v}`} stroke="#888" fontSize={12} />
              <YAxis stroke="#888" fontSize={12} domain={[0, 100]} />
              <Tooltip contentStyle={{ backgroundColor: "#fff", border: "1px solid #e5e5e5", borderRadius: "8px" }} />
              <Line
                type="monotone"
                dataKey="focus_score"
                stroke="#1a667a"
                strokeWidth={2}
                dot={{ fill: "#1a667a", r: 4 }}
                name="집중도 점수"
              />
            </LineChart>
          </ResponsiveContainer>
        </div>
      </div>

      {/* Session Records Table view */}
      <div className="bg-white rounded-2xl border border-border p-6">
        <div className="flex items-center justify-between mb-4">
          <h2 className="text-xl font-semibold">세션 기록</h2>
          
          <button 
            onClick={() => setIsFilterExpanded(!isFilterExpanded)}
            className="flex items-center gap-2 text-sm text-primary font-medium hover:underline transition-all"
          >
            <SlidersHorizontal className="w-4 h-4" />
            <span>{isFilterExpanded ? "필터 닫기" : "세부 필터링"}</span>
          </button>
        </div>

        {isFilterExpanded && (
          <div className="mb-6 p-4 bg-accent/20 border border-primary/10 rounded-xl grid grid-cols-1 md:grid-cols-2 gap-6 transition-all animate-in fade-in duration-200">
            <div className="space-y-2">
              <label className="text-xs font-semibold text-muted-foreground flex items-center gap-1">
                <ArrowUpDown className="w-3 h-3" /> 정렬 기준
              </label>
              <select 
                value={sortBy}
                onChange={(e) => setSortBy(e.target.value as any)}
                className="w-full p-2 text-sm bg-white border border-border rounded-lg shadow-sm"
              >
                <option value="date_desc">최신 순</option>
                <option value="date_asc">오래된 순</option>
                <option value="score_desc">집중도 높은 순</option>
                <option value="score_asc">집중도 낮은 순</option>
              </select>
            </div>

            <div className="space-y-2">
              <label className="text-xs font-semibold text-muted-foreground flex items-center justify-between">
                <span>최소 집중도 점수</span>
                <span className="text-primary font-bold">{minScore}% 이상</span>
              </label>
              <input 
                type="range" 
                min="0" 
                max="100" 
                value={minScore}
                onChange={(e) => setMinScore(parseInt(e.target.value))}
                className="w-full accent-primary cursor-pointer mt-2"
              />
            </div>
          </div>
        )}

        <div className="overflow-x-auto">
          {processedSessions.length === 0 ? (
            <div className="p-8 text-center text-muted-foreground text-sm">지정 기간 내 조건에 맞는 완료된 세션 기록이 없습니다.</div>
          ) : (
            <table className="w-full">
              <thead className="border-b border-border">
                <tr className="text-left">
                  <th className="pb-3 text-sm font-medium text-muted-foreground">날짜</th>
                  <th className="pb-3 text-sm font-medium text-muted-foreground">세션 회차</th>
                  <th className="pb-3 text-sm font-medium text-muted-foreground">총 학습 시간</th>
                  <th className="pb-3 text-sm font-medium text-muted-foreground">집중도 성과</th>
                  <th className="pb-3 text-sm font-medium text-muted-foreground"></th>
                </tr>
              </thead>
              <tbody className="divide-y divide-border">
                {processedSessions.map((session) => (
                  <tr key={session.id} className="hover:bg-accent/20 transition-colors group">
                    <td className="py-4 text-sm text-muted-foreground">{session.date}</td>
                    <td className="py-4 text-sm font-semibold text-foreground">세션 #{session.display_index}</td>
                    <td className="py-4 text-sm text-foreground">{formatDuration(session.duration_min)}</td>
                    <td className="py-4">
                      <div className="flex items-center gap-2">
                        <div className="flex-1 max-w-[100px] bg-muted rounded-full h-2">
                          <div className="bg-primary rounded-full h-2" style={{ width: `${session.focus_score}%` }} />
                        </div>
                        <span className="text-sm font-bold text-foreground font-mono">{session.focus_score}%</span>
                      </div>
                    </td>
                    <td className="py-4 text-right">
                      <Link to={`/app/reports/${session.id}`} className="inline-flex items-center gap-1 text-sm text-primary hover:underline font-medium">
                        <span className="opacity-0 group-hover:opacity-100 transition-opacity text-xs">세부 분석 보기</span>
                        <ChevronRight className="w-4 h-4 text-primary" />
                      </Link>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          )}
        </div>
      </div>
    </div>
  );
}

function StatCard({
  icon,
  label,
  value,
}: {
  icon: React.ReactNode;
  label: string;
  value: string;
}) {
  return (
    <div className="bg-white rounded-2xl border border-border p-6 hover:border-primary/30 transition-colors">
      <div className="flex items-start justify-between mb-4">
        <div className="p-2 bg-accent rounded-lg text-primary">{icon}</div>
      </div>
      <div className="text-sm text-muted-foreground mb-1">{label}</div>
      <div className="text-2xl font-bold text-foreground font-sans">{value}</div>
    </div>
  );
}