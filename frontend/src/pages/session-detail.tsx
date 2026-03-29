import { useParams, Link } from "react-router";
import { ArrowLeft, Calendar, Clock, Eye, User, Activity } from "lucide-react";
import {
  LineChart,
  Line,
  RadarChart,
  Radar,
  PolarGrid,
  PolarAngleAxis,
  PolarRadiusAxis,
  XAxis,
  YAxis,
  CartesianGrid,
  Tooltip,
  ResponsiveContainer,
  Area,
  AreaChart,
} from "recharts";

const sessionData = {
  id: "43",
  sessionName: "Session 43",
  date: "March 23, 2026",
  startTime: "2:30 PM",
  endTime: "4:45 PM",
  totalDuration: 135,
  actualFocusTime: 98,
  awayFromSeat: 12,
  poorEyeGaze: 15,
  poorPosture: 18,
  fidgeting: 22,
  focusScore: 73,
};

// Timeline data - focus score over time (sampled every 5 minutes)
const timelineData = [
  { time: "0:00", score: 85 },
  { time: "0:05", score: 88 },
  { time: "0:10", score: 82 },
  { time: "0:15", score: 78 },
  { time: "0:20", score: 65 },
  { time: "0:25", score: 45 },
  { time: "0:30", score: 70 },
  { time: "0:35", score: 82 },
  { time: "0:40", score: 88 },
  { time: "0:45", score: 90 },
  { time: "0:50", score: 85 },
  { time: "0:55", score: 78 },
  { time: "1:00", score: 72 },
  { time: "1:05", score: 75 },
  { time: "1:10", score: 80 },
  { time: "1:15", score: 85 },
  { time: "1:20", score: 88 },
  { time: "1:25", score: 82 },
  { time: "1:30", score: 78 },
  { time: "1:35", score: 75 },
  { time: "1:40", score: 70 },
  { time: "1:45", score: 68 },
  { time: "1:50", score: 72 },
  { time: "1:55", score: 75 },
  { time: "2:00", score: 78 },
  { time: "2:05", score: 80 },
  { time: "2:10", score: 78 },
  { time: "2:15", score: 76 },
];

// Radial chart data - distraction breakdown
const radarData = [
  { metric: "Away from Seat", value: 12, fullMark: 30 },
  { metric: "Poor Eye Gaze", value: 15, fullMark: 30 },
  { metric: "Poor Posture", value: 18, fullMark: 30 },
  { metric: "Fidgeting", value: 22, fullMark: 30 },
  { metric: "Other", value: 5, fullMark: 30 },
];

export function SessionDetail() {
  const { sessionId } = useParams();

  const focusPercentage = Math.round(
    (sessionData.actualFocusTime / sessionData.totalDuration) * 100
  );

  return (
    <div className="p-8 space-y-6 max-w-7xl mx-auto bg-background min-h-screen">
      {/* Back Button & Header */}
      <div className="flex items-center gap-4 mb-2">
        <Link
          to="/app/reports"
          className="p-2 hover:bg-accent rounded-lg transition-colors"
        >
          <ArrowLeft className="w-5 h-5 text-muted-foreground" />
        </Link>
        <div>
          <h1 className="text-3xl font-bold text-foreground">세션 분석</h1>
          <p className="text-muted-foreground">
            학습 세션에 대한 AI 기반 인사이트
          </p>
        </div>
      </div>

      {/* Session Info Card */}
      <div className="bg-white rounded-2xl border border-border p-6">
        <div className="flex items-start justify-between mb-4">
          <div>
            <h2 className="text-2xl font-semibold text-foreground mb-2">
              {sessionData.sessionName}
            </h2>
            <div className="flex items-center gap-4 text-sm text-muted-foreground">
              <div className="flex items-center gap-1">
                <Calendar className="w-4 h-4" />
                <span>{sessionData.date}</span>
              </div>
              <div className="flex items-center gap-1">
                <Clock className="w-4 h-4" />
                <span>
                  {sessionData.startTime} - {sessionData.endTime}
                </span>
              </div>
            </div>
          </div>
          <div className="text-right">
            <div className="text-sm text-muted-foreground mb-1">전체 집중도</div>
            <div className="text-4xl font-bold text-primary">
              {sessionData.focusScore}%
            </div>
          </div>
        </div>
      </div>

      {/* Key Metrics Grid */}
      <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-4 gap-4">
        <MetricCard
          icon={<Clock className="w-5 h-5" />}
          label="총 학습 시간"
          value={formatMinutes(sessionData.totalDuration)}
          color="bg-blue-500"
        />
        <MetricCard
          icon={<Eye className="w-5 h-5" />}
          label="실제 집중 시간"
          value={formatMinutes(sessionData.actualFocusTime)}
          subtitle={`세션의 ${focusPercentage}%`}
          color="bg-green-500"
        />
        <MetricCard
          icon={<User className="w-5 h-5" />}
          label="자리 이탈"
          value={formatMinutes(sessionData.awayFromSeat)}
          color="bg-orange-500"
        />
        <MetricCard
          icon={<Activity className="w-5 h-5" />}
          label="집중도 점수"
          value={`${sessionData.focusScore}%`}
          color="bg-primary"
        />
      </div>

      {/* Timeline Chart */}
      <div className="bg-white rounded-2xl border border-border p-6">
        <h3 className="text-xl font-semibold mb-4">집중도 점수 타임라인</h3>
        <p className="text-sm text-muted-foreground mb-6">
          세션 전체에 걸친 집중도의 실시간 추적
        </p>
        <ResponsiveContainer width="100%" height={300}>
          <AreaChart data={timelineData}>
            <defs>
              <linearGradient id="focusGradient" x1="0" y1="0" x2="0" y2="1">
                <stop offset="5%" stopColor="#1a667a" stopOpacity={0.3} />
                <stop offset="95%" stopColor="#1a667a" stopOpacity={0} />
              </linearGradient>
            </defs>
            <CartesianGrid strokeDasharray="3 3" stroke="#f0f0f0" />
            <XAxis
              dataKey="time"
              stroke="#888"
              fontSize={12}
              label={{ value: "Time (hh:mm)", position: "insideBottom", offset: -5 }}
            />
            <YAxis
              stroke="#888"
              fontSize={12}
              domain={[0, 100]}
              label={{ value: "Focus Score (%)", angle: -90, position: "insideLeft" }}
            />
            <Tooltip
              contentStyle={{
                backgroundColor: "#fff",
                border: "1px solid #e5e5e5",
                borderRadius: "8px",
              }}
              formatter={(value: number) => [`${value}%`, "Focus Score"]}
            />
            <Area
              type="monotone"
              dataKey="score"
              stroke="#1a667a"
              strokeWidth={3}
              fillOpacity={1}
              fill="url(#focusGradient)"
            />
          </AreaChart>
        </ResponsiveContainer>
        <div className="mt-4 p-4 bg-accent/30 rounded-lg border border-primary/20">
          <p className="text-sm text-muted-foreground">
            <strong className="text-foreground">인사이트:</strong> 세션 시작 후 약 45분에 집중도가 최고조에 달했습니다. 높은 성과를 유지하려면 50분마다 휴식을 취하는 것을 고려하세요.
          </p>
        </div>
      </div>

      <div className="grid grid-cols-1 lg:grid-cols-2 gap-6">
        <div className="bg-white rounded-2xl border border-border p-6">
          <h3 className="text-xl font-semibold mb-4">산만함 분석</h3>
          <ResponsiveContainer width="100%" height={350}>
            <RadarChart data={radarData}>
              <PolarGrid stroke="#e5e5e5" />
              <PolarAngleAxis dataKey="metric" tick={{ fill: "#888", fontSize: 12 }} />
              <PolarRadiusAxis angle={90} domain={[0, 30]} tick={{ fill: "#888" }} />
              <Radar
                name="Minutes"
                dataKey="value"
                stroke="#1a667a"
                fill="#1a667a"
                fillOpacity={0.5}
                strokeWidth={2}
              />
              <Tooltip
                contentStyle={{
                  backgroundColor: "#fff",
                  border: "1px solid #e5e5e5",
                  borderRadius: "8px",
                }}
                formatter={(value: number) => [`${value} min`, "Time"]}
              />
            </RadarChart>
          </ResponsiveContainer>
        </div>

        {/* Detailed Breakdown List */}
        <div className="bg-white rounded-2xl border border-border p-6">
          <h3 className="text-xl font-semibold mb-4">상세 지표</h3>
          <div className="space-y-4">
            <DistractionItem
              label="자리 이탈"
              value={sessionData.awayFromSeat}
              total={sessionData.totalDuration}
              color="bg-orange-500"
              description="프레임에서 사람이 감지되지 않은 시간"
            />
            <DistractionItem
              label="시선 분산"
              value={sessionData.poorEyeGaze}
              total={sessionData.totalDuration}
              color="bg-yellow-500"
              description="학습 자료에서 시선이 벗어난 시간"
            />
            <DistractionItem
              label="나쁜 자세"
              value={sessionData.poorPosture}
              total={sessionData.totalDuration}
              color="bg-red-500"
              description="구부정한 자세, 누운 자세 또는 잘못된 위치"
            />
            <DistractionItem
              label="과도한 움직임"
              value={sessionData.fidgeting}
              total={sessionData.totalDuration}
              color="bg-purple-500"
              description="빈번한 손 움직임 및 불안정함"
            />
          </div>
        </div>
      </div>

      <div className="bg-gradient-to-br from-primary/5 to-accent/30 rounded-2xl border border-primary/20 p-6">
        <h3 className="text-xl font-semibold mb-4">맞춤형 추천</h3>
        <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
          <RecommendationCard
            title="정기적인 휴식"
            content="50분 후 피로 징후가 나타났습니다. 뽀모도로 기법을 시도해보세요: 25분 학습, 5분 휴식."
          />
          <RecommendationCard
            title="자세 개선"
            content="의자 높이를 조정하거나 자세 알림 앱을 사용하여 더 나은 자세를 유지하세요."
          />
          <RecommendationCard
            title="움직임 최소화"
            content="복잡한 주제를 다룰 때 움직임이 증가했습니다. 스트레스 볼이나 피젯 도구를 사용해보세요."
          />
          <RecommendationCard
            title="적극적인 참여"
            content="노트를 적극적으로 작성할 때 집중도가 가장 높았습니다. 이 학습 방식을 계속하세요."
          />
        </div>
      </div>

      <div className="bg-white rounded-xl border border-border p-4">
        <div className="flex items-start gap-3">
          <div className="p-2 bg-accent rounded-lg">
            <svg
              className="w-5 h-5 text-primary"
              fill="none"
              viewBox="0 0 24 24"
              stroke="currentColor"
            >
              <path
                strokeLinecap="round"
                strokeLinejoin="round"
                strokeWidth={2}
                d="M12 15v2m-6 4h12a2 2 0 002-2v-6a2 2 0 00-2-2H6a2 2 0 00-2 2v6a2 2 0 002 2zm10-10V7a4 4 0 00-8 0v4h8z"
              />
            </svg>
          </div>
          <div className="flex-1">
            <h4 className="font-semibold text-sm mb-1">개인정보 보호</h4>
            <p className="text-sm text-muted-foreground">
              세션 비디오는 AI가 분석한 후 즉시 삭제되었습니다. 이러한 인사이트를 생성하기 위해 익명화된 메타데이터만 저장됩니다.
            </p>
          </div>
        </div>
      </div>
    </div>
  );
}

function formatMinutes(minutes: number): string {
  const hours = Math.floor(minutes / 60);
  const mins = minutes % 60;
  if (hours > 0) {
    return `${hours}h ${mins}m`;
  }
  return `${mins}m`;
}

function MetricCard({
  icon,
  label,
  value,
  subtitle,
  color,
}: {
  icon: React.ReactNode;
  label: string;
  value: string;
  subtitle?: string;
  color: string;
}) {
  return (
    <div className="bg-white rounded-xl border border-border p-5 hover:border-primary/30 transition-colors">
      <div className={`inline-flex p-2 rounded-lg ${color} text-white mb-3`}>
        {icon}
      </div>
      <div className="text-sm text-muted-foreground mb-1">{label}</div>
      <div className="text-2xl font-bold text-foreground">{value}</div>
      {subtitle && <div className="text-xs text-muted-foreground mt-1">{subtitle}</div>}
    </div>
  );
}

function DistractionItem({
  label,
  value,
  total,
  color,
  description,
}: {
  label: string;
  value: number;
  total: number;
  color: string;
  description: string;
}) {
  const percentage = Math.round((value / total) * 100);

  return (
    <div className="space-y-2">
      <div className="flex items-center justify-between">
        <div>
          <div className="font-medium text-foreground">{label}</div>
          <div className="text-xs text-muted-foreground">{description}</div>
        </div>
        <div className="text-right">
          <div className="font-semibold text-foreground">{formatMinutes(value)}</div>
          <div className="text-xs text-muted-foreground">{percentage}%</div>
        </div>
      </div>
      <div className="w-full bg-muted rounded-full h-2">
        <div
          className={`${color} rounded-full h-2 transition-all`}
          style={{ width: `${percentage}%` }}
        />
      </div>
    </div>
  );
}

function RecommendationCard({
  title,
  content,
}: {
  title: string;
  content: string;
}) {
  return (
    <div className="bg-white/60 rounded-xl p-4 border border-primary/10 hover:border-primary/30 transition-colors">
      <h4 className="font-semibold text-sm mb-1 text-foreground">{title}</h4>
      <p className="text-sm text-muted-foreground">{content}</p>
    </div>
  );
}