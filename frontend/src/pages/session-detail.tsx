import { useState, useEffect, useMemo } from "react";
import { useParams, Link, useNavigate } from "react-router";
import { ArrowLeft, Calendar, Clock, Eye, User, Brain, Trash2 } from "lucide-react";
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
  duration_sec: number;
  summary: {
    focus_score: number;
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
  const [allSessions, setAllSessions] = useState<any[]>([]);
  const [loading, setLoading] = useState(true);

  const userId = localStorage.getItem("user_id"); 
  const navigate = useNavigate();

  const handleDeleteSession = async () => {
    const confirmDelete = window.confirm(
      "이 세션을 삭제하시겠습니까?\n관련된 모든 타임라인과 AI 분석 데이터가 영구적으로 삭제됩니다."
    );

    if (!confirmDelete) return;

    try {
      const response = await fetch(`${import.meta.env.VITE_API_BASE_URL}/analytics/sessions/${sessionId}`, {
        method: "DELETE",
      });

      if (response.ok) {
        alert("세션이 삭제되었습니다.");
        navigate("/app/reports"); 
      } else {
        alert("세션 삭제에 실패했습니다.");
      }
    } catch (error) {
      console.error("Failed to delete session:", error);
    }
  };

  useEffect(() => {
    if (!sessionId || !userId) return;

    const fetchSessionDetail = async () => {
      try {
        setLoading(true);
        const headers = { "X-User-Id": userId };

        const [res, listRes] = await Promise.all([
          fetch(`${import.meta.env.VITE_API_BASE_URL}/analytics/sessions/${sessionId}`, { headers }),
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

  const matchedSession = useMemo(() => {
    if (!sessionId || allSessions.length === 0) return null;
    return allSessions.find((s) => String(s.id) === String(sessionId));
  }, [allSessions, sessionId]);

  const displayIndex = matchedSession ? matchedSession.display_index : 1;

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

  const STATE_WEIGHTS: Record<string, number> = {
    focus: 100,
    gaze_down: 100,
    page_turn: 100,
    bad_posture: 60,
    pen_fidget: 80,
    unknown: 75,
    present_unknown: 75,
    gaze_away: 40,
    gaze_side: 40,
    restless_hand: 100,
    drowsy: 20,
    sleep_suspect: 20,
    absent: 0,
  };

  const FOCUS_COMPATIBLE_STATES = new Set(["focus", "gaze_down", "page_turn", "restless_hand"]);
  const STATE_LABELS: Record<string, string> = {
    focus: "집중",
    gaze_down: "책/필기 시선",
    page_turn: "페이지 넘김",
    gaze_side: "측면 시선",
    bad_posture: "자세 불량",
    pen_fidget: "펜 만지작거림",
    restless_hand: "불안정한 손 움직임",
    drowsy: "졸음",
    absent: "자리 이탈",
    unknown: "판정 불확실",
    present_unknown: "판정 불확실",
    gaze_away: "시선 이탈",
    sleep_suspect: "졸음 의심",
  };

  const sessionMetrics = useMemo(() => {
    if (!report) {
      return {
        totalSeconds: 0,
        observedSeconds: 0,
        focusScore: 0,
        actualFocusSeconds: 0,
        distractionSeconds: 0,
        unknownSeconds: 0,
        secondBySecond: [] as number[],
      };
    }

    const timeline = [...(report.timeline || [])].sort((a, b) => a.t - b.t);
    const maxTimelineSecond = timeline.length > 0 ? Math.floor(timeline[timeline.length - 1].t) + 1 : 0;
    const tSecs = Math.max(report.duration_sec || 0, matchedSession?.duration_sec || 0, maxTimelineSecond, timeline.length, 1);

    // Score only the states that were actually recorded. This keeps the report
    // aligned with the live chart instead of silently inventing states for gaps.
    const secondBySecond = timeline.map((item) => STATE_WEIGHTS[item.state] ?? STATE_WEIGHTS.unknown);
    const actualFocusSeconds = timeline.filter(({ state }) => FOCUS_COMPATIBLE_STATES.has(state)).length;
    const unknownSeconds = timeline.filter(({ state }) => state === "unknown" || state === "present_unknown").length;
    const distractionSeconds = Math.max(0, timeline.length - actualFocusSeconds - unknownSeconds);
    const focusScore = secondBySecond.length > 0
      ? Math.round(secondBySecond.reduce((sum, value) => sum + value, 0) / secondBySecond.length)
      : 0;

    return {
      totalSeconds: tSecs,
      observedSeconds: timeline.length,
      focusScore,
      actualFocusSeconds,
      distractionSeconds,
      unknownSeconds,
      secondBySecond,
    };
  }, [report, matchedSession]);

  const attentionDipSegments = useMemo(() => {
    const timeline = [...(report?.timeline || [])].sort((a, b) => a.t - b.t);
    if (timeline.length === 0) return [];

    // Use the same semantics as the displayed score. Focus-compatible activity
    // ends a dip; everything else is treated as a possible attention-loss period.
    const focusCompatible = FOCUS_COMPATIBLE_STATES;

    type DipRow = {
      start_sec: number;
      end_sec: number;
      duration_sec: number;
      dominant_state: string;
      dominant_label: string;
      dominant_seconds: number;
      score_loss: number;
      feedback: string;
    };

    const dips: DipRow[] = [];
    let current: Array<{ t: number; state: string }> = [];

    const closeDip = () => {
      if (current.length === 0) return;

      const startSec = Math.floor(current[0].t);
      const endSec = Math.floor(current[current.length - 1].t) + 1;
      const durationSec = Math.max(1, endSec - startSec);

      // Ignore tiny one/two-sample flickers in the coach section.
      if (durationSec < 3) {
        current = [];
        return;
      }

      const counts = new Map<string, number>();
      let scoreLoss = 0;
      current.forEach(({ state }) => {
        counts.set(state, (counts.get(state) || 0) + 1);
        scoreLoss += 100 - (STATE_WEIGHTS[state] ?? STATE_WEIGHTS.unknown);
      });

      let dominantState = current[0].state;
      let dominantSeconds = 0;
      for (const [state, seconds] of counts.entries()) {
        if (seconds > dominantSeconds) {
          dominantState = state;
          dominantSeconds = seconds;
        }
      }

      const dominantLabel = STATE_LABELS[dominantState] || dominantState;
      const dominantPercent = Math.round((dominantSeconds / current.length) * 100);

      dips.push({
        start_sec: startSec,
        end_sec: endSec,
        duration_sec: durationSec,
        dominant_state: dominantState,
        dominant_label: dominantLabel,
        dominant_seconds: dominantSeconds,
        score_loss: scoreLoss,
        feedback: `${formatAdaptiveTime(startSec)}~${formatAdaptiveTime(endSec)} 구간에서 ${dominantLabel} 상태가 ${dominantSeconds}초(${dominantPercent}%)로 가장 많이 감지되었습니다.`,
      });

      current = [];
    };

    for (const item of timeline) {
      if (focusCompatible.has(item.state)) {
        closeDip();
      } else {
        // Break the segment if there is a meaningful timestamp gap.
        if (
          current.length > 0 &&
          Math.floor(item.t) - Math.floor(current[current.length - 1].t) > 2
        ) {
          closeDip();
        }
        current.push(item);
      }
    }
    closeDip();

    // Rank by total focus-score loss first, then duration. This favors a shorter
    // severe drowsy/absence period over a very long but mild unknown period.
    return dips
      .sort((a, b) => b.score_loss - a.score_loss || b.duration_sec - a.duration_sec)
      .slice(0, 3);
  }, [report]);

  const parsedTimelineData = useMemo(() => {
    const timeline = [...(report?.timeline || [])].sort((a, b) => a.t - b.t);
    if (timeline.length === 0) return [];

    const dataPointsCount = 30;
    const bucketSize = Math.max(1, Math.floor(timeline.length / dataPointsCount));
    const bucketedData = [];

    for (let i = 0; i < timeline.length; i += bucketSize) {
      const chunk = timeline.slice(i, i + bucketSize);
      const avgScore = chunk.reduce(
        (sum, item) => sum + (STATE_WEIGHTS[item.state] ?? STATE_WEIGHTS.unknown),
        0
      ) / chunk.length;
      const endTime = Math.floor(chunk[chunk.length - 1].t);
      const mins = Math.floor(endTime / 60);
      const secs = endTime % 60;

      const stateCounts = new Map<string, number>();
      chunk.forEach(({ state }) => {
        stateCounts.set(state, (stateCounts.get(state) || 0) + 1);
      });

      let dominantState = chunk[chunk.length - 1].state;
      let dominantCount = -1;
      for (const [state, count] of stateCounts.entries()) {
        if (count > dominantCount) {
          dominantState = state;
          dominantCount = count;
        }
      }

      bucketedData.push({
        time: `${mins}:${String(secs).padStart(2, "0")}`,
        score: Math.round(avgScore),
        state: dominantState,
        stateLabel: STATE_LABELS[dominantState] || dominantState,
      });
    }

    return bucketedData;
  }, [report]);

  const getTimelineMetrics = (targetStates: string[]) => {
    const timeline = report?.timeline || [];
    const totalSec = timeline.filter(t => targetStates.includes(t.state)).length;

    let count = 0;
    let inBlock = false;
    const sortedTimeline = [...timeline].sort((a, b) => a.t - b.t);

    for (const item of sortedTimeline) {
      if (targetStates.includes(item.state)) {
        if (!inBlock) {
          count++;
          inBlock = true;
        }
      } else {
        inBlock = false;
      }
    }

    const baseTotal = sessionMetrics.observedSeconds || 1;
    const percent = Math.min(Math.round((totalSec / baseTotal) * 100), 100);
    
    let score = 1; 
    if (percent >= 40) score = 5;
    else if (percent >= 25) score = 4;
    else if (percent >= 15) score = 3;
    else if (percent >= 5) score = 2;

    return { count, totalSec, timeMin: Math.round(totalSec / 60), percent, score };
  };

  const absentMetrics = getTimelineMetrics(["absent"]);
  const gazeMetrics = getTimelineMetrics(["gaze_side", "gaze_away"]);
  const postureMetrics = getTimelineMetrics(["bad_posture"]);
  const penFidgetMetrics = getTimelineMetrics(["pen_fidget"]);
  const drowsyMetrics = getTimelineMetrics(["drowsy", "sleep_suspect"]);
  const pageTurnMetrics = getTimelineMetrics(["page_turn"]);

  const radarData = [
    { metric: "자리 이탈", value: absentMetrics.score, baseMark: 1, timeLabel: formatAdaptiveTime(absentMetrics.totalSec), fullMark: 5 },
    { metric: "시선 분산", value: gazeMetrics.score, baseMark: 1, timeLabel: formatAdaptiveTime(gazeMetrics.totalSec), fullMark: 5 },
    { metric: "자세 불량", value: postureMetrics.score, baseMark: 1, timeLabel: formatAdaptiveTime(postureMetrics.totalSec), fullMark: 5 },
    { metric: "펜 만지작거림", value: penFidgetMetrics.score, baseMark: 1, timeLabel: formatAdaptiveTime(penFidgetMetrics.totalSec), fullMark: 5 },
    { metric: "졸음 감지", value: drowsyMetrics.score, baseMark: 1, timeLabel: formatAdaptiveTime(drowsyMetrics.totalSec), fullMark: 5 },
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
    <div className="p-4 sm:p-8 space-y-4 sm:space-y-6 max-w-7xl mx-auto bg-background min-h-screen">
      <div className="flex items-center gap-3 sm:gap-4 mb-2">
        <Link to="/app/reports" className="p-2 hover:bg-accent rounded-lg transition-colors border border-transparent hover:border-border bg-white shadow-sm">
          <ArrowLeft className="w-5 h-5 text-muted-foreground" />
        </Link>
        <div>
          <h1 className="text-2xl sm:text-3xl font-bold text-foreground">세션 분석</h1>
          <p className="text-sm sm:text-base text-muted-foreground">학습 세션에 대한 AI 기반 인사이트</p>
        </div>
      </div>

      <div className="bg-white rounded-xl sm:rounded-2xl border border-border p-4 sm:p-6 shadow-sm flex flex-col sm:flex-row justify-between items-start sm:items-center gap-4">
        <div>
          <h2 className="text-2xl font-bold text-foreground mb-1">세션 #{displayIndex} 리포트</h2>
          <div className="flex items-center gap-4 text-sm text-muted-foreground mt-2">
            <div className="flex items-center gap-1"><Calendar className="w-4 h-4" /><span>{formattedDate}</span></div>
            <div className="flex items-center gap-1">
              <Clock className="w-4 h-4" />
              <span>종료 시각: {new Date(matchedSession?.end_time || summary.analyzed_at).toLocaleTimeString("ko-KR", {hour: '2-digit', minute:'2-digit'})}</span>
            </div>
          </div>
        </div>
        <div className="text-left sm:text-right w-full sm:w-auto flex justify-between sm:block items-center">
          <div className="text-sm text-muted-foreground mb-0 sm:mb-1">전체 집중도</div>
          <div className="text-3xl sm:text-4xl font-extrabold text-primary">{sessionMetrics.focusScore}%</div>
        </div>
      </div>

      {/* FIX: Changed to grid-cols-3 so cards sit side-by-side on mobile */}
      <div className="grid grid-cols-3 gap-2 sm:gap-4">
        <MetricCard 
          icon={<Clock className="w-4 h-4 sm:w-5 sm:h-5" />} 
          label="학습 시간" 
          value={formatAdaptiveTime(sessionMetrics.totalSeconds)}
          color="bg-blue-500" 
        />
        <MetricCard 
          icon={<Eye className="w-4 h-4 sm:w-5 sm:h-5" />} 
          label="집중 시간" 
          value={formatAdaptiveTime(sessionMetrics.actualFocusSeconds)} 
          subtitle={`${sessionMetrics.focusScore}%`} 
          color="bg-green-500" 
        />
        <MetricCard 
          icon={<User className="w-4 h-4 sm:w-5 sm:h-5" />} 
          label="주의 이탈 시간" 
          value={formatAdaptiveTime(sessionMetrics.distractionSeconds)}
          subtitle={`불확실 ${formatAdaptiveTime(sessionMetrics.unknownSeconds)}`}
          color="bg-orange-500" 
        />
      </div>

      {/* Timeline Chart */}
      <div className="bg-white rounded-2xl border border-border p-6 shadow-sm">
        <h3 className="text-xl font-semibold mb-4">집중도 점수 타임라인</h3>
        <p className="text-sm text-muted-foreground mb-6">세션 전체에 걸친 집중도의 실시간 추적</p>
        
        {/* FIX: Added Tailwind wrapper to control height */}
        <div className="h-48 sm:h-[300px] w-full">
          <ResponsiveContainer width="100%" height="100%">
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
              <Tooltip
                content={({ active, payload, label }) => {
                  if (!active || !payload || payload.length === 0) return null;
                  const point = payload[0]?.payload;
                  if (!point) return null;

                  return (
                    <div className="bg-white border border-[#e5e5e5] p-3 rounded-lg shadow-sm">
                      <p className="text-xs text-muted-foreground mb-1">{label}</p>
                      <p className="text-sm font-semibold text-foreground">
                        집중도: {point.score}%
                      </p>
                      <p className="text-sm text-primary font-medium mt-1">
                        주요 감지 상태: {point.stateLabel}
                      </p>
                    </div>
                  );
                }}
              />
              <Area type="monotone" dataKey="score" stroke="#1a667a" strokeWidth={3} fillOpacity={1} fill="url(#focusGradient)" />
            </AreaChart>
          </ResponsiveContainer>        
        </div>
      </div>

      {/* Grid Breakdowns */}
      <div className="grid grid-cols-1 lg:grid-cols-2 gap-6">
        <div className="bg-white rounded-2xl border border-border p-6 shadow-sm">
          <h3 className="text-xl font-semibold mb-4">행동 패턴 분석</h3>
          <p className="text-sm text-muted-foreground mb-4">
            가장 안쪽의 점선 영역은 낮은 기록 비율을 의미합니다. 그래프가 바깥으로 뻗어나갈수록 해당 행동이 세션 중 더 오래 기록되었음을 나타냅니다.
          </p>
          
          {/* FIX: Added Tailwind wrapper to control height */}
          <div className="h-64 sm:h-[350px] w-full mt-4">
            <ResponsiveContainer width="100%" height="100%">
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
                <Radar name="행동 감지" dataKey="value" stroke="#1a667a" fill="#1a667a" fillOpacity={0.5} strokeWidth={2} />
                
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
        </div>

        <div className="bg-white rounded-2xl border border-border p-6 shadow-sm">
          <h3 className="text-xl font-semibold mb-4">상세 지표</h3>
          <div className="space-y-4">
            <DistractionItem 
              label="자리 이탈" 
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
              description={`측면/외부 시선 이탈 빈도: 총 ${gazeMetrics.count}회`} 
            />
            <DistractionItem 
              label="자세 불량" 
              valueText={formatAdaptiveTime(postureMetrics.totalSec)} 
              percentage={postureMetrics.percent} 
              color="bg-red-500" 
              description={`거북목 및 구부정한 자세 감지: 총 ${postureMetrics.count}회`} 
            />
            <DistractionItem 
              label="졸음 감지" 
              valueText={formatAdaptiveTime(drowsyMetrics.totalSec)} 
              percentage={drowsyMetrics.percent} 
              color="bg-indigo-500" 
              description={`눈 감김 및 졸음 의심 상태: 총 ${drowsyMetrics.count}회`} 
            />
            <DistractionItem 
              label="페이지 넘김" 
              valueText={formatAdaptiveTime(pageTurnMetrics.totalSec)} 
              percentage={pageTurnMetrics.percent} 
              color="bg-emerald-500" 
              description={`학습 중 페이지 넘김 감지: 총 ${pageTurnMetrics.count}회`} 
            />
            <DistractionItem 
              label="펜 만지작거림" 
              valueText={formatAdaptiveTime(penFidgetMetrics.totalSec)} 
              percentage={penFidgetMetrics.percent} 
              color="bg-purple-500" 
              description={`작고 반복적인 펜/손 움직임 감지: 총 ${penFidgetMetrics.count}회`} 
            />
          </div>
        </div>
      </div>

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
          
          {attentionDipSegments.length > 0 && (
            <div className="mt-5 space-y-3">
              <h4 className="font-semibold text-sm text-foreground">⚠️ 집중력 저하 주요 구간</h4>
              {attentionDipSegments.map((segment, idx) => (
                <div key={`${segment.start_sec}-${segment.end_sec}-${idx}`} className="flex items-start gap-3 bg-white p-3 rounded-lg border border-border">
                  <div className="text-xs font-mono font-bold text-orange-500 bg-orange-50 px-2 py-1 rounded whitespace-nowrap">
                    {formatAdaptiveTime(segment.start_sec)} - {formatAdaptiveTime(segment.end_sec)}
                  </div>
                  <div>
                    <p className="text-sm font-medium">{segment.dominant_label}</p>
                    <p className="text-xs text-muted-foreground mt-0.5">{segment.feedback}</p>
                  </div>
                </div>
              ))}
            </div>
          )}
        </div>
      )}

      <div className="bg-white rounded-xl border border-border p-4 shadow-sm flex items-start gap-3">
        <div className="p-2 bg-accent rounded-lg text-primary">
          <Brain className="w-5 h-5" />
        </div>
        <div className="flex-1">
          <h4 className="font-semibold text-sm mb-1">개인정보 보호 안내</h4>
          <p className="text-sm text-muted-foreground">본 시스템은 듀얼 카메라 영상 프레임을 가공하여 통계 가치 데이터만 데이터베이스에 안전하게 보관하며 분석용 영상 조각은 소멸 처리합니다.</p>
        </div>
      </div>
      <div className="flex justify-end pt-4">
        <button 
          onClick={handleDeleteSession}
          className="flex items-center gap-2 px-4 py-2 text-sm text-destructive bg-destructive/5 hover:bg-destructive/10 border border-transparent hover:border-destructive/20 rounded-lg transition-colors"
        >
          <Trash2 className="w-4 h-4" />
          세션 삭제
        </button>
      </div>
    </div>
  );
}

// FIX: Updated the MetricCard component layout to scale dynamically
function MetricCard({ icon, label, value, subtitle, color, change }: { icon: React.ReactNode; label: string; value: string; subtitle?: string; color: string; change?: { text: string, positive: boolean } | null }) {
  return (
    <div className="bg-white rounded-xl border border-border p-3 sm:p-5 hover:border-primary/30 transition-colors shadow-sm relative flex flex-col items-center sm:items-start text-center sm:text-left">
      <div className="flex justify-center sm:justify-between items-start mb-2 sm:mb-3 w-full">
        <div className={`inline-flex p-1.5 sm:p-2 rounded-lg ${color} text-white shadow-sm scale-75 sm:scale-100`}>{icon}</div>
        {change && (
          <span className={`hidden sm:block text-[10px] sm:text-[11px] font-bold px-2 py-1 rounded-md border ${change.positive ? "bg-emerald-50 text-emerald-600 border-emerald-100" : "bg-rose-50 text-rose-500 border-rose-100"}`}>
            {change.text}
          </span>
        )}
      </div>
      <div className="text-[10px] sm:text-sm text-muted-foreground mb-1 font-medium truncate w-full">{label}</div>
      <div className="text-sm sm:text-2xl font-bold text-foreground font-mono truncate w-full">{value}</div>
      {subtitle && <div className="text-[9px] sm:text-xs text-muted-foreground mt-1 font-medium">{subtitle}</div>}
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