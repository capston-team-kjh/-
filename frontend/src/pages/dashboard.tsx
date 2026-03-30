import { useEffect, useState } from "react";
import { Link } from "react-router";
import { Calendar, Clock, Target, TrendingUp, Play } from "lucide-react";
import { ActivityHeatmap } from "../components/activity-heatmap";
import { AreaChart, Area, XAxis, YAxis, CartesianGrid, Tooltip, ResponsiveContainer } from "recharts";

const weeklyData = [
  { day: "Mon", hours: 3.5 },
  { day: "Tue", hours: 4.2 },
  { day: "Wed", hours: 2.8 },
  { day: "Thu", hours: 5.1 },
  { day: "Fri", hours: 3.9 },
  { day: "Sat", hours: 6.5 },
  { day: "Sun", hours: 4.8 },
];

const recentSessions = [
  { id: 1, name: "세션 43", duration: "2h 15m", date: "오늘, 2:30 PM" },
  { id: 2, name: "세션 42", duration: "1h 45m", date: "오늘, 10:00 AM" },
  { id: 3, name: "세션 41", duration: "3h 00m", date: "어제, 3:15 PM" },
  { id: 4, name: "세션 40", duration: "1h 30m", date: "어제, 9:00 AM" },
];

export function Dashboard() {
  const [reportData, setReportData] = useState<any>(null);
  const [recentSessions, setRecentSessions] = useState<any[]>([]);
  const [loading, setLoading] = useState(true);
  
  // Get user info from localStorage (saved during login)
  const userId = localStorage.getItem("user_id");
  const userName = localStorage.getItem("name") || "사용자";

  useEffect(() => {
    if (!userId) return;

    const fetchDashboardData = async () => {
      try {
        const headers = { "X-User-Id": userId };
        
        // Fetch both summary and recent sessions in parallel
        const [summaryRes, recentRes] = await Promise.all([
          fetch(`http://127.0.0.1:8000/api/v1/reports/summary?range=weekly`, { headers }),
          fetch(`http://127.0.0.1:8000/api/v1/reports/recent?size=4`, { headers })
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
  }, [userId]);

  if (loading) return <div className="p-8 text-center">학습 데이터를 불러오는 중...</div>;

  return (
    <div className="p-8 space-y-8 max-w-7xl mx-auto">
      <div className="flex items-center justify-between">
        <div>
          <h1 className="text-3xl font-bold text-foreground mb-1">대시보드</h1>
          <p className="text-muted-foreground">
            {userName}님, 다시 오신 것을 환영합니다! 오늘의 학습 현황을 확인하세요.
          </p>
        </div>
        <Link
          to="/app/session"
          className="flex items-center gap-2 px-6 py-3 bg-primary text-primary-foreground rounded-lg hover:bg-primary/90 transition-colors"
        >
          <Play className="w-5 h-5" />
          <span>세션 시작</span>
        </Link>
      </div>

      <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-4 gap-6">
        <StatCard
          icon={<Clock className="w-6 h-6" />}
          label="이번 주 학습"
          value={`${reportData?.total_hours || 0} hrs`}
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
          value={`${recentSessions.length > 0 ? recentSessions[0].duration_min : 0} min`}
        />
        <StatCard
          icon={<Calendar className="w-6 h-6" />}
          label="활동 지수"
          value={reportData?.active_days > 3 ? "높음" : "보통"}
        />
      </div>

      <div className="bg-white rounded-2xl border border-border p-6">
        <h2 className="text-xl font-semibold mb-4">활동 현황</h2>
        <ActivityHeatmap />
      </div>

      <div className="grid grid-cols-1 lg:grid-cols-2 gap-6">
        <div className="bg-white rounded-2xl border border-border p-6">
          <h2 className="text-xl font-semibold mb-4">주간 학습 시간</h2>
          <ResponsiveContainer width="100%" height={250}>
            <AreaChart data={weeklyData}>
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
            {recentSessions.map((session) => (
            <div key={session.session_id} className="flex items-center justify-between p-4 rounded-lg border border-border">
              <div>
                <div className="font-medium">세션 #{session.session_id}</div>
                <div className="text-sm text-muted-foreground">{session.date} {session.start_time}</div>
              </div>
              <div className="text-right">
                <div className="font-semibold text-primary">{session.duration_min}분</div>
                <div className="text-xs text-muted-foreground">집중도: {session.focus_score}%</div>
              </div>
            </div>
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
    <div className="bg-white rounded-2xl border border-border p-6 hover:border-primary/30 transition-colors">
      <div className="flex items-start justify-between mb-4">
        <div className="p-2 bg-accent rounded-lg text-primary">{icon}</div>
        {change && (
          <span
            className={`text-sm ${
              positive ? "text-green-600" : "text-muted-foreground"
            }`}
          >
            {change}
          </span>
        )}
      </div>
      <div className="text-sm text-muted-foreground mb-1">{label}</div>
      <div className="text-2xl font-bold text-foreground">{value}</div>
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