import { useState, useEffect, useMemo } from "react";
import { useParams, Link } from "react-router";
import { ArrowLeft, Calendar, Clock, Eye, User, Activity, Brain } from "lucide-react";
import {
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

interface SessionReportData {
  summary: {
    session_id: string;
    focus_ratio: number;
    absent_count: number;
    absent_total_sec: number;
    away_count: number;
    away_total_sec: number;
    bad_posture_ratio: number;
    analyzed_at: string;
  };
  timeline: Array<{ t: number; state: string }>;
  insights: string[];
  events: Array<{
    event_type: string;
    start_sec: number;
    end_sec: number;
    score: number;
  }>;
  personal_feedback?: {
    main_problem: string;
    reason: string;
    feedback: string;
    next_action: string;
    worst_segments: Array<{
      start_sec: number;
      end_sec: number;
      problem: string;
      feedback: string;
    }>;
  };
  feedback_source?: string;
}

export function SessionDetail() {
  const { sessionId } = useParams<{ sessionId: string }>();
  const [report, setReport] = useState<SessionReportData | null>(null);
  const [allSessions, setAllSessions] = useState<any[]>([]); //Track full list history
  const [loading, setLoading] = useState(true);

  const userId = localStorage.getItem("user_id"); 

  useEffect(() => {
    if (!sessionId || !userId) return;

    const fetchSessionDetail = async () => {
      try {
        setLoading(true);
        const headers = { "X-User-Id": userId };

        // Fetch both the session analysis data and the full historical order list in parallel
        const [res, listRes] = await Promise.all([
          fetch(`${import.meta.env.VITE_API_BASE_URL}/analytics/session/${sessionId}`),
          fetch(`${import.meta.env.VITE_API_BASE_URL}/analytics/list`, { headers })
        ]);

        if (res.ok && listRes.ok) {
          setReport(await res.json());
          const listData = await listRes.json();
          setAllSessions(listData.items || []);
        }
      } catch (error) {
        console.error("Failed to load individual session report metrics:", error);
      } finally {
        setLoading(false);
      }
    };

    fetchSessionDetail();
  }, [sessionId, userId]);

  // Calculate the dynamic matching display_index based on your sorted history rows
  const displayIndex = useMemo(() => {
    if (!sessionId || allSessions.length === 0) return 1;
    // Find where this session exists in your history list
    const matched = allSessions.find((s) => String(s.id) === String(sessionId));
    return matched ? matched.display_index : 1;
  }, [allSessions, sessionId]);

  // Helper formatting logic
  const formatAdaptiveTime = (totalSecs: number): string => {
    if (totalSecs >= 3600) {
      // 1 hour or more: Show Hours and Minutes
      const hours = Math.floor(totalSecs / 3600);
      const mins = Math.floor((totalSecs % 3600) / 60);
      return `${hours}h ${mins}m`;
    } else {
      // Under 1 hour: Show Minutes and Seconds
      const mins = Math.floor(totalSecs / 60);
      const secs = Math.floor(totalSecs % 60);
      return mins > 0 ? `${mins}m ${secs}s` : `${secs}s`;
    }
  };

  const sessionMetrics = useMemo(() => {
    if (!report) return { totalSeconds: 0, focusScore: 0, actualFocusSeconds: 0, secondBySecond: [] };
    
    // Determine exact session length in seconds
    const tSecs = report.timeline?.length > 0 
      ? report.timeline.length 
      : Math.max(...(report.events?.map(e => e.end_sec) || [0]), 1);
      
    // Baseline array: Assume 100% focus for every second
    const secondBySecond = new Array(tSecs).fill(100);
    
    // Apply event penalties
    report.events?.forEach(event => {
      const start = Math.floor(event.start_sec);
      const end = Math.floor(event.end_sec);
      const penalty = (event.score || 0) * 100;
      const resultingFocus = Math.max(0, 100 - penalty);

      for (let i = start; i < end && i < tSecs; i++) {
        secondBySecond[i] = Math.min(secondBySecond[i], resultingFocus);
      }
    });
    
    // Calculate the average focus score mathematically
    const totalScoreSum = secondBySecond.reduce((sum, score) => sum + score, 0);
    const focusRatio = tSecs > 0 ? totalScoreSum / (tSecs * 100) : 0;
    const focusScore = Math.round(focusRatio * 100);
    const actualFocusSeconds = Math.round(tSecs * focusRatio);
    
    return { totalSeconds: tSecs, focusScore, actualFocusSeconds, secondBySecond };
  }, [report]);

  const parsedTimelineData = useMemo(() => {
    const { totalSeconds, secondBySecond } = sessionMetrics;
    if (totalSeconds === 0) return [];

    const dataPointsCount = 30;
    const bucketSize = Math.max(1, Math.floor(totalSeconds / dataPointsCount));

    const bucketedData = [];
    for (let i = 0; i < totalSeconds; i += bucketSize) {
      const chunk = secondBySecond.slice(i, i + bucketSize);
      const avgScore = chunk.reduce((sum, val) => sum + val, 0) / chunk.length;

      const mins = Math.floor(i / 60);
      const secs = i % 60;
      bucketedData.push({
        time: `${mins}:${String(secs).padStart(2, "0")}`,
        score: Math.round(avgScore),
      });
    }

    return bucketedData;
  }, [sessionMetrics]);

  const getEventMetrics = (eventTypes: string[]) => {
    // Safely check if report and events exist
    const matchedEvents = report?.events?.filter(e => eventTypes.includes(e.event_type)) || [];
    const count = matchedEvents.length;
    const totalSec = matchedEvents.reduce((sum, e) => sum + (e.end_sec - e.start_sec), 0);
    const timeMin = Math.round(totalSec / 60);
    
    // Use sessionMetrics.totalSeconds instead of the old redundant variable
    const baseTotal = sessionMetrics.totalSeconds || 1; 
    const percent = Math.min(Math.round((totalSec / baseTotal) * 100), 100);
    
    let score = 1; 
    if (percent >= 5) score = 2;
    if (percent >= 15) score = 3;
    if (percent >= 25) score = 4;
    if (percent >= 40) score = 5;

    return { count, totalSec, timeMin, percent, score };
  };

  const getFidgetingMetrics = () => {
    const targetEvents = report?.events?.filter(e => ["bad_posture", "gaze_side"].includes(e.event_type)).sort((a, b) => a.start_sec - b.start_sec) || [];
    let count = 0;
    let totalSec = 0;

    for (let i = 1; i < targetEvents.length; i++) {
      const prev = targetEvents[i - 1];
      const curr = targetEvents[i];
      const gapSeconds = curr.start_sec - prev.end_sec;

      if (gapSeconds >= 0 && gapSeconds <= 5) {
        count += 1;
        totalSec += (curr.end_sec - curr.start_sec) + gapSeconds;
      }
    }

    const timeMin = Math.round(totalSec / 60);
    const baseTotal = sessionMetrics.totalSeconds || 1;
    const percent = Math.min(Math.round((totalSec / baseTotal) * 100), 100);
    
    let score = 1; 
    if (percent >= 5) score = 2;
    if (percent >= 15) score = 3;
    if (percent >= 25) score = 4;
    if (percent >= 40) score = 5;

    return { count, totalSec, timeMin, percent, score };
  };

  const absentMetrics = getEventMetrics(["absent"]);
  const gazeMetrics = getEventMetrics(["gaze_side"]);
  const postureMetrics = getEventMetrics(["bad_posture"]);
  const fidgetingMetrics = getFidgetingMetrics();

  const radarData = [
    { metric: "자리 이탈", value: absentMetrics.score, baseMark: 1, timeLabel: formatAdaptiveTime(absentMetrics.totalSec), fullMark: 5 },
    { metric: "시선 분산", value: gazeMetrics.score, baseMark: 1, timeLabel: formatAdaptiveTime(gazeMetrics.totalSec), fullMark: 5 },
    { metric: "자세 불량", value: postureMetrics.score, baseMark: 1, timeLabel: formatAdaptiveTime(postureMetrics.totalSec), fullMark: 5 },
    { metric: "과도한 움직임", value: fidgetingMetrics.score, baseMark: 1, timeLabel: formatAdaptiveTime(fidgetingMetrics.totalSec), fullMark: 5 },
  ];

  if (loading) return <div className="p-8 text-center text-muted-foreground">세부 분석 리포트를 생성하는 중...</div>;
  if (!report) return <div className="p-8 text-center text-destructive">리포트 데이터를 찾을 수 없습니다.</div>;

  const { summary } = report;

  const formattedDate = new Date(summary.analyzed_at).toLocaleDateString("ko-KR", {
    year: "numeric",
    month: "long",
    day: "numeric",
  });

  return (
    <div className="p-8 space-y-6 max-w-7xl mx-auto bg-background min-h-screen">
      {/* Back Button & Header */}
      <div className="flex items-center gap-4 mb-2">
        <Link to="/app/reports" className="p-2 hover:bg-accent rounded-lg transition-colors border border-transparent hover:border-border bg-white shadow-sm">
          <ArrowLeft className="w-5 h-5 text-muted-foreground" />
        </Link>
        <div>
          <h1 className="text-3xl font-bold text-foreground">세션 분석</h1>
          <p className="text-muted-foreground">학습 세션에 대한 AI 기반 인사이트</p>
        </div>
      </div>

      {/* Session Info Card */}
      <div className="bg-white rounded-2xl border border-border p-6 shadow-sm flex flex-col sm:flex-row justify-between items-start sm:items-center gap-4">
        <div>
          <h2 className="text-2xl font-bold text-foreground mb-1">세션 #{displayIndex} 리포트</h2>
          <div className="flex items-center gap-4 text-sm text-muted-foreground mt-2">
            <div className="flex items-center gap-1"><Calendar className="w-4 h-4" /><span>{formattedDate}</span></div>
            <div className="flex items-center gap-1"><Clock className="w-4 h-4" /><span>종료 시각: {new Date(summary.analyzed_at).toLocaleTimeString("ko-KR", {hour: '2-digit', minute:'2-digit'})}</span></div>
          </div>
        </div>
        <div className="text-right">
          <div className="text-sm text-muted-foreground mb-1">전체 집중도</div>
          <div className="text-4xl font-extrabold text-primary">{sessionMetrics.focusScore}%</div>
        </div>
      </div>

      {/* Key Metrics Grid */}
      <div className="grid grid-cols-1 md:grid-cols-3 gap-4">
        <MetricCard 
          icon={<Clock className="w-5 h-5" />} 
          label="총 학습 시간" 
          value={formatAdaptiveTime(sessionMetrics.totalSeconds)}
          color="bg-blue-500" 
        />
        <MetricCard 
          icon={<Eye className="w-5 h-5" />} 
          label="실제 집중 시간" 
          value={formatAdaptiveTime(sessionMetrics.actualFocusSeconds)} 
          subtitle={`세션의 ${sessionMetrics.focusScore}%`} 
          color="bg-green-500" 
        />
        <MetricCard 
          icon={<User className="w-5 h-5" />} 
          label="총 산만 시간" 
          value={formatAdaptiveTime(sessionMetrics.totalSeconds - sessionMetrics.actualFocusSeconds)}
          color="bg-orange-500" 
        />
      </div>

      {/* Timeline Chart */}
      <div className="bg-white rounded-2xl border border-border p-6 shadow-sm">
        <h3 className="text-xl font-semibold mb-4">집중도 점수 타임라인</h3>
        <p className="text-sm text-muted-foreground mb-6">세션 전체에 걸친 집중도의 실시간 추적</p>
        
        <ResponsiveContainer width="100%" height={300}>
          <AreaChart data={parsedTimelineData}>
            <defs>
              <linearGradient id="focusGradient" x1="0" y1="0" x2="0" y2="1">
                <stop offset="5%" stopColor="#1a667a" stopOpacity={0.3} />
                <stop offset="95%" stopColor="#1a667a" stopOpacity={0} />
              </linearGradient>
            </defs>
            <CartesianGrid strokeDasharray="3 3" stroke="#f0f0f0" />
            <XAxis dataKey="time" stroke="#888" fontSize={12} tickLine={false} dy={10} />
            <YAxis stroke="#888" fontSize={12} domain={[0, 100]} ticks={[0, 25, 50, 75, 100]} tickLine={false} dx={-5} />
            <Tooltip contentStyle={{ backgroundColor: "#fff", border: "1px solid #e5e5e5", borderRadius: "8px" }} formatter={(value: number) => [`${value}%`, "Focus Score"]} />
            <Area type="monotone" dataKey="score" stroke="#1a667a" strokeWidth={3} fillOpacity={1} fill="url(#focusGradient)" />
          </AreaChart>
        </ResponsiveContainer>        
      </div>

      {/* Grid Breakdowns */}
      <div className="grid grid-cols-1 lg:grid-cols-2 gap-6">
        <div className="bg-white rounded-2xl border border-border p-6 shadow-sm">
          <h3 className="text-xl font-semibold mb-4">산만함 분석</h3>
          <p className="text-sm text-muted-foreground mb-4">
            가장 안쪽의 점선 영역은 정상 범위를 의미합니다. 그래프가 바깥으로 뻗어나갈수록 해당 요소로 인한 방해 시간이 길었음을 나타냅니다.
          </p>
          <ResponsiveContainer width="100%" height={350}>
            <RadarChart data={radarData}>
              <PolarGrid stroke="#e5e5e5" />
              <PolarAngleAxis dataKey="metric" tick={{ fill: "#888", fontSize: 12 }} />
              <PolarRadiusAxis angle={90} domain={[0, 5]} tickCount={6} tick={false} axisLine={false} />

              <Radar 
                name="정상(안전) 범위" 
                dataKey="baseMark" 
                stroke="#10b981" 
                fill="none" 
                strokeWidth={2} 
                strokeDasharray="5 5" 
              />
              {/* Data layer */}
              <Radar name="산만함 감지" dataKey="value" stroke="#1a667a" fill="#1a667a" fillOpacity={0.5} strokeWidth={2} />
              
  
              
              <Tooltip 
                content={({ active, payload }) => {
                  if (active && payload && payload.length) {
                    const data = payload.find(p => p.dataKey === "value");
                    if (data) {
                      return (
                        <div className="bg-white border border-[#e5e5e5] p-3 rounded-lg shadow-sm">
                          <p className="font-bold text-sm text-foreground mb-1">{data.payload.metric}</p>
                          <p className="text-sm text-primary font-medium">누적 발생 시간: {data.payload.timeLabel}</p>
                        </div>
                      );
                    }
                  }
                  return null;
                }}
              />
            </RadarChart>
          </ResponsiveContainer>
        </div>

        <div className="bg-white rounded-2xl border border-border p-6 shadow-sm">
          <h3 className="text-xl font-semibold mb-4">상세 지표</h3>
          <div className="space-y-4">
            <DistractionItem 
              label="자리 이탈" 
              // Pass the formatted adaptive time string directly
              valueText={formatAdaptiveTime(absentMetrics.totalSec)} 
              percentage={absentMetrics.percent} 
              color="bg-orange-500" 
              description={`프레임 내 미감지 빈도: 총 ${absentMetrics.count}회`} 
            />
            <DistractionItem 
              label="시선 분산" 
              valueText={formatAdaptiveTime(gazeMetrics.totalSec)} 
              percentage={gazeMetrics.percent} 
              color="bg-yellow-500" 
              description={`외부 주시 및 시선 이탈 빈도: 총 ${gazeMetrics.count}회`} 
            />
            <DistractionItem 
              label="자세 불량" 
              valueText={formatAdaptiveTime(postureMetrics.totalSec)} 
              percentage={postureMetrics.percent} 
              color="bg-red-500" 
              description={`거북목 및 구부정한 자세 감지: 총 ${postureMetrics.count}회`} 
            />
            <DistractionItem 
              label="과도한 움직임" 
              valueText={formatAdaptiveTime(fidgetingMetrics.totalSec)} 
              percentage={fidgetingMetrics.percent} 
              color="bg-purple-500" 
              description={`불안정한 움직임 감지: 총 ${fidgetingMetrics.count}회`} 
            />
          </div>
        </div>
      </div>

      {/* 백엔드 AI JSON 데이터를 활용한 스마트 피드백 영역 */}
      {report?.personal_feedback && (
        <div className="bg-gradient-to-br from-primary/5 to-accent/30 rounded-2xl border border-primary/20 p-6 shadow-sm mb-6">
          <div className="flex items-center justify-between mb-5">
            <h3 className="text-xl font-bold text-foreground flex items-center gap-2">
              <Brain className="w-6 h-6 text-primary" /> AI 맞춤형 세션 코칭
            </h3>
            {report.feedback_source === "ai_api" && (
              <span className="px-2 py-1 bg-primary/10 text-primary text-xs rounded-md font-medium">
                AI 분석 완료
              </span>
            )}
          </div>
          
          <div className="grid grid-cols-1 md:grid-cols-2 gap-5 mb-5">
            <RecommendationCard 
              title={`주요 문제: ${report.personal_feedback.main_problem}`} 
              content={report.personal_feedback.reason} 
            />
            <RecommendationCard 
              title="향후 학습 제안" 
              content={report.personal_feedback.next_action} 
            />
          </div>

          <div className="bg-white/80 rounded-xl p-5 border border-primary/10 shadow-sm">
            <h4 className="font-semibold text-sm mb-2 text-primary">상세 피드백</h4>
            <p className="text-sm text-muted-foreground leading-relaxed">
              {report.personal_feedback.feedback}
            </p>
          </div>
          
          {/* 최악의 구간(worst_segments)이 존재할 경우 렌더링 */}
          {report.personal_feedback.worst_segments && report.personal_feedback.worst_segments.length > 0 && (
            <div className="mt-5 space-y-3">
              <h4 className="font-semibold text-sm text-foreground">⚠️ 집중력 저하 주요 구간</h4>
              {report.personal_feedback.worst_segments.map((segment, idx) => (
                <div key={idx} className="flex items-start gap-3 bg-white p-3 rounded-lg border border-border">
                  <div className="text-xs font-mono font-bold text-orange-500 bg-orange-50 px-2 py-1 rounded">
                    {formatAdaptiveTime(segment.start_sec)} - {formatAdaptiveTime(segment.end_sec)}
                  </div>
                  <div>
                    <p className="text-sm font-medium">{segment.problem}</p>
                    <p className="text-xs text-muted-foreground mt-0.5">{segment.feedback}</p>
                  </div>
                </div>
              ))}
            </div>
          )}
        </div>
      )}

      {/* Privacy Box */}
      <div className="bg-white rounded-xl border border-border p-4 shadow-sm flex items-start gap-3">
        <div className="p-2 bg-accent rounded-lg text-primary">
          <Brain className="w-5 h-5" />
        </div>
        <div className="flex-1">
          <h4 className="font-semibold text-sm mb-1">개인정보 보호 안내</h4>
          <p className="text-sm text-muted-foreground">본 시스템은 듀얼 카메라 영상 프레임을 가공하여 통계 가치 데이터만 데이터베이스에 안전하게 보관하며 분석용 영상 조각은 소멸 처리합니다.</p>
        </div>
      </div>
    </div>
  );
}

function MetricCard({ icon, label, value, subtitle, color, change }: { icon: React.ReactNode; label: string; value: string; subtitle?: string; color: string; change?: { text: string, positive: boolean } | null }) {
  return (
    <div className="bg-white rounded-xl border border-border p-5 hover:border-primary/30 transition-colors shadow-sm relative">
      <div className="flex justify-between items-start mb-3">
        <div className={`inline-flex p-2 rounded-lg ${color} text-white shadow-sm`}>{icon}</div>
        {/* Render the comparison pill if data exists */}
        {change && (
          <span className={`text-[11px] font-bold px-2.5 py-1 rounded-md border ${change.positive ? "bg-emerald-50 text-emerald-600 border-emerald-100" : "bg-rose-50 text-rose-500 border-rose-100"}`}>
            {change.text}
          </span>
        )}
      </div>
      <div className="text-sm text-muted-foreground mb-1 font-medium">{label}</div>
      <div className="text-2xl font-bold text-foreground font-mono">{value}</div>
      {subtitle && <div className="text-xs text-muted-foreground mt-1 font-medium">{subtitle}</div>}
    </div>
  );
}

function DistractionItem({ 
  label, valueText, percentage, color, description 
}: { 
  label: string; valueText: string; percentage: number; color: string; description: string;
}) {
  return (
    <div className="space-y-2">
      <div className="flex items-center justify-between">
        <div>
          <div className="font-medium text-foreground text-sm">{label}</div>
          <div className="text-xs text-muted-foreground">{description}</div>
        </div>
        <div className="text-right">
          {/* Displaying the formatted string directly */}
          <div className="font-bold text-foreground text-sm font-mono">{valueText}</div>
          <div className="text-xs text-muted-foreground font-medium">{percentage}%</div>
        </div>
      </div>
      <div className="w-full bg-muted rounded-full h-2">
        <div className={`${color} rounded-full h-2 transition-all duration-500`} style={{ width: `${percentage}%` }} />
      </div>
    </div>
  );
}

function RecommendationCard({ title, content }: { title: string; content: string }) {
  return (
    <div className="bg-white/80 rounded-xl p-4 border border-primary/10 hover:border-primary/30 transition-colors shadow-sm">
      <h4 className="font-semibold text-sm mb-1 text-primary">{title}</h4>
      <p className="text-sm text-muted-foreground leading-relaxed">{content}</p>
    </div>
  );
}