import { useEffect, useState, useMemo } from "react";
import { Link } from "react-router";
import { Calendar, Clock, Target, TrendingUp, Play } from "lucide-react";
import { ActivityHeatmap } from "../components/activity-heatmap";
import { AreaChart, Area, XAxis, YAxis, CartesianGrid, Tooltip, ResponsiveContainer } from "recharts";

export function Dashboard() {
  const [reportData, setReportData] = useState<any>(null);
  const [recentSessions, setRecentSessions] = useState<any[]>([]);
  const [loading, setLoading] = useState(true);

  // Mobile check
  const isMobile = typeof window !== "undefined" && /iPhone|iPad|iPod|Android/i.test(navigator.userAgent);
  
  // Get user info from localStorage
  const userId = localStorage.getItem("user_id");
  const userName = localStorage.getItem("name") || "사용자";

  // Time Formatter
  const formatAdaptiveTime = (totalSecs: number): string => {
    if (totalSecs >= 3600) {
      const hours = Math.floor(totalSecs / 3600);
      const mins = Math.floor((totalSecs % 3600) / 60);
      return `${hours}h ${mins}m`;
    } else {
      const mins = Math.floor(totalSecs / 60);
      const secs = Math.floor(totalSecs % 60);
      return mins > 0 ? `${mins}m ${secs}s` : `${secs}s`;
    }
  };

  // --- NEW: 1. Calculate the strict Sunday-Saturday range for the current week ---
  const weekBounds = useMemo(() => {
    const today = new Date();
    const dayOfWeek = today.getDay(); // 0 = Sunday, 1 = Monday, etc.
    
    // FIX: Shift the start day to Sunday (0 days back if it's already Sunday)
    const daysToSunday = dayOfWeek; 
    
    const sunday = new Date(today);
    sunday.setDate(today.getDate() - daysToSunday);
    
    const saturday = new Date(sunday);
    saturday.setDate(sunday.getDate() + 6);
    
    const format = (d: Date) => `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, '0')}-${String(d.getDate()).padStart(2, '0')}`;
    
    return { start: format(sunday), end: format(saturday), sunday }; // Changed 'monday' key to 'sunday'
  }, []);

  useEffect(() => {
    if (!userId) return;

    const fetchDashboardData = async () => {
      try {
        const headers = { "X-User-Id": userId };

        // FIX: Fetch exactly Monday to Sunday instead of a rolling 7-day window
        const [summaryRes, recentRes] = await Promise.all([
          fetch(`${import.meta.env.VITE_API_BASE_URL}/analytics/summary?start_date=${weekBounds.start}&end_date=${weekBounds.end}`, { headers }),
          fetch(`${import.meta.env.VITE_API_BASE_URL}/analytics/list`, { headers })
        ]);

        if (summaryRes.ok && recentRes.ok) {
          setReportData(await summaryRes.json());
          const recentData = await recentRes.json();
          setRecentSessions(recentData.items);
        }
      } catch (error) {
        console.error("Dashboard data fetch failed:", error);
      } finally {
        setLoading(false);
      }
    };

    fetchDashboardData();
  }, [userId, weekBounds]);

  // --- NEW: 2. Pad the sparse data to ensure Recharts always gets exactly 7 days ---
  const fixedWeeklyData = useMemo(() => {
    const dayNames = ["일", "월", "화", "수", "목", "금", "토"];
    
    // Added 'shortMatch' to our TypeScript definition
    const template: { dateMatch: string; shortMatch: string; day: string; seconds: number; hours: number }[] = [];
    
    for(let i = 0; i < 7; i++) {
      const d = new Date(weekBounds.sunday);
      d.setDate(weekBounds.sunday.getDate() + i);
      
      const y = d.getFullYear();
      const m = String(d.getMonth() + 1).padStart(2, '0');
      const day = String(d.getDate()).padStart(2, '0');
      
      const isoDate = `${y}-${m}-${day}`; // Format: "2026-07-31"
      const shortDate = `${m}/${day}`;    // Format: "07/31"
      
      template.push({
        dateMatch: isoDate,
        shortMatch: shortDate, // Add a short date to the template
        day: `${m}/${day}(${dayNames[d.getDay()]})`, 
        seconds: 0,
        hours: 0
      });
    }

    if (reportData?.weekly_chart_data) {
      reportData.weekly_chart_data.forEach((item: any) => {
        // FIX: Broaden the matching logic so it catches "YYYY-MM-DD", "MM/DD", or "MM/DD(Day)"
        const target = template.find(t => 
          t.dateMatch === item.date || 
          t.dateMatch === item.day || 
          t.shortMatch === item.day || 
          t.day === item.day
        );
        
        if (target) {
          // Fallbacks added to safely grab the time regardless of the API naming convention
          target.seconds = Number(item.seconds || item.total_seconds || item.duration_sec || 0);
          target.hours = item.hours !== undefined ? Number(item.hours) : (target.seconds / 3600);
        }
      });
    }
    
    return template;
  }, [reportData, weekBounds]);

  if (loading) return <div className="p-8 text-center">학습 데이터를 불러오는 중...</div>;

  return (
    // Scaled down padding and spacing for mobile, preserved for desktop
    <div className="p-4 sm:p-8 space-y-5 sm:space-y-8 max-w-7xl mx-auto">
      <div className="flex items-center justify-between">
        <div>
          {/* Shrunk the title and subtitle */}
          <h1 className="text-2xl sm:text-3xl font-bold text-foreground mb-1">대시보드</h1>
          <p className="text-sm sm:text-base text-muted-foreground">
            {userName}님, 다시 오신 것을 환영합니다! 오늘의 학습 현황을 확인하세요.
          </p>
        </div>
        
        {/* FIX: Hide Start Session button on mobile */}
        {!isMobile && (
          <Link
            to="/app/session"
            className="hidden sm:flex items-center gap-2 px-6 py-3 bg-primary text-primary-foreground rounded-lg hover:bg-primary/90 transition-colors shrink-0"
          >
            <Play className="w-5 h-5" />
            <span>세션 시작</span>
          </Link>
        )}
      </div>

      {/* Grid items automatically scale to 1 column on mobile (grid-cols-1) */}
      <div className="grid grid-cols-2 md:grid-cols-4 gap-3 sm:gap-6">
        <StatCard
          icon={<Clock className="w-6 h-6" />}
          label="이번 주 학습"
          value={reportData ? formatAdaptiveTime(reportData.total_seconds || 0) : "0s"}
          change={`${reportData?.active_days || 0}일 활동 중`}
          positive
        />
        <StatCard
          icon={<TrendingUp className="w-6 h-6" />}
          label="평균 집중도"
          value={`${reportData?.avg_focus_score || 0}%`}
          positive
        />
        <StatCard
          icon={<Target className="w-6 h-6" />} 
          label="최근 세션"
          value={
            recentSessions.length > 0 
              ? formatAdaptiveTime([...recentSessions].sort((a, b) => b.id - a.id)[0].duration_sec) 
              : "0s"
          }
        />
        <StatCard
          icon={<Calendar className="w-6 h-6" />}
          label="활동 지수"
          value={reportData?.active_days > 3 ? "높음" : "보통"}
        />
      </div>

      <div className="bg-white rounded-2xl border border-border p-6">
        <h2 className="text-xl font-semibold mb-4">활동 현황</h2>
        <ActivityHeatmap rawSessions={recentSessions} />
      </div>

      <div className="grid grid-cols-1 lg:grid-cols-2 gap-6">
        <div className="bg-white rounded-2xl border border-border p-6">
          <h2 className="text-xl font-semibold mb-4">주간 학습 시간</h2>
          <ResponsiveContainer width="100%" height={250}>
            <AreaChart data={fixedWeeklyData}>
              <defs>
                <linearGradient id="colorHours" x1="0" y1="0" x2="0" y2="1">
                  <stop offset="5%" stopColor="#1a667a" stopOpacity={0.3} />
                  <stop offset="95%" stopColor="#1a667a" stopOpacity={0} />
                </linearGradient>
              </defs>
              <CartesianGrid strokeDasharray="3 3" stroke="#f0f0f0" />
              <XAxis dataKey="day" stroke="#888" fontSize={12} />
              <YAxis stroke="#888" fontSize={12} />
              <Tooltip
                contentStyle={{
                  backgroundColor: "#fff",
                  border: "1px solid #e5e5e5",
                  borderRadius: "8px",
                }}
                formatter={(value: number, name: string, props: any) => {
                  // FIX: Directly extract the seconds from the parent data payload!
                  const actualSeconds = props.payload.seconds || 0;
                  return [formatAdaptiveTime(actualSeconds), "학습 시간"];
                }}
              />
              <Area
                type="monotone"
                dataKey="hours"
                stroke="#1a667a"
                strokeWidth={2}
                fillOpacity={1}
                fill="url(#colorHours)"
              />
            </AreaChart>
          </ResponsiveContainer>
        </div>

        <div className="bg-white rounded-2xl border border-border p-6">
          <div className="flex items-center justify-between mb-4">
            <h2 className="text-xl font-semibold">최근 세션</h2>
            <Link to="/app/reports" className="text-sm text-primary hover:underline">
              모두 보기
            </Link>
          </div>
          <div className="space-y-3">
            {[...recentSessions].sort((a, b) => b.id - a.id).slice(0, 3).map((session) => (
              <Link 
                key={session.session_id || session.id} 
                to={`/app/reports/${session.session_id || session.id}`} 
                className="flex items-center justify-between p-4 rounded-xl border border-border bg-white hover:border-primary/40 hover:shadow-sm transition-all cursor-pointer group block"
              >
                <div>
                  {/* Displaying the relative order number instead of the absolute database index row id */}
                  <div className="font-semibold text-foreground group-hover:text-primary transition-colors">
                    세션 #{session.display_index}
                  </div>
                  <div className="text-sm text-muted-foreground mt-0.5">
                    {session.date} {session.start_time}
                  </div>
                </div>
                <div className="text-right flex items-center gap-4">
                  <div>
                    <div className="font-bold text-primary">{formatAdaptiveTime(session.duration_sec)}</div>
                    <div className="text-xs text-muted-foreground font-medium">
                      집중도: {session.focus_score}%
                    </div>
                  </div>
                  <span className="text-muted-foreground opacity-0 group-hover:opacity-100 group-hover:translate-x-1 transition-all text-sm font-medium">
                    →
                  </span>
                </div>
              </Link>
            ))}
          </div>
        </div>
      </div>

      <div>
        <QuickActionCard
          title="상세 보고서 보기"
          description="시간에 따른 진행 상황 분석"
          action="보고서 보기"
          link="/app/reports"
        />
      </div>
    </div>
  );
}

function StatCard({
  icon,
  label,
  value,
  change,
  positive,
}: {
  icon: React.ReactNode;
  label: string;
  value: string;
  change?: string;
  positive?: boolean;
}) {
  return (
    // Reduced padding drastically for mobile (p-3)
    <div className="bg-white rounded-xl sm:rounded-2xl border border-border p-3 sm:p-6 hover:border-primary/30 transition-colors">
      <div className="flex items-start justify-between mb-2 sm:mb-4">
        <div className="p-1.5 sm:p-2 bg-accent rounded-lg text-primary scale-75 sm:scale-100">{icon}</div>
        {change && (
          <span className={`text-[10px] sm:text-sm ${positive ? "text-green-600" : "text-muted-foreground"}`}>
            {change}
          </span>
        )}
      </div>
      <div className="text-[11px] sm:text-sm text-muted-foreground mb-0.5 sm:mb-1 truncate">{label}</div>
      {/* Dropped mobile text size to text-lg */}
      <div className="text-lg sm:text-2xl font-bold text-foreground truncate">{value}</div>
    </div>
  );
}

function QuickActionCard({
  title,
  description,
  action,
  link,
}: {
  title: string;
  description: string;
  action: string;
  link?: string;
}) {
  const content = (
    <div className="bg-gradient-to-br from-accent/30 to-white rounded-2xl border border-border p-6 hover:border-primary/30 transition-all hover:shadow-md">
      <h3 className="font-semibold mb-2">{title}</h3>
      <p className="text-sm text-muted-foreground mb-4">{description}</p>
      <div className="text-sm text-primary font-medium">{action} →</div>
    </div>
  );

  return link ? <Link to={link}>{content}</Link> : content;
}