import { useState, useEffect, useMemo } from "react"; 
import { Link } from "react-router";
import { ChevronRight, Clock, Target, Calendar, Brain, ArrowUpRight, ArrowDownRight, AlertCircle } from "lucide-react";

interface ReportItem {
  id: number;
  display_index: number;
  date: string;
  date_raw: string;
  duration_min: number;
  duration_sec: number;
  focus_score: number;
  eventSecs?: { gaze: number; posture: number; absent: number; fidget: number };
}

export function Reports() {
  const [sessionsList, setSessionsList] = useState<ReportItem[]>([]);
  const [loading, setLoading] = useState(true);

  const [currentPage, setCurrentPage] = useState(1);
  const itemsPerPage = 6;
  
  const userId = localStorage.getItem("user_id");
  const userName = localStorage.getItem("name") || "사용자";

  // Helper: Get YYYY-MM-DD for a specific number of days ago
  const getPastDateString = (daysAgo: number) => {
    const d = new Date();
    d.setDate(d.getDate() - daysAgo);
    const year = d.getFullYear();
    const month = String(d.getMonth() + 1).padStart(2, '0');
    const day = String(d.getDate()).padStart(2, '0');
    return `${year}-${month}-${day}`;
  };

  useEffect(() => {
    if (!userId) return;

    const fetchReportsData = async () => {
      try {
        setLoading(true);
        const headers = { "X-User-Id": userId };
        
        const listRes = await fetch(`${import.meta.env.VITE_API_BASE_URL}/analytics/list`, { headers });

        if (listRes.ok) {
          const listData = await listRes.json();
          setSessionsList(listData.items || []);
        }
      } catch (error) {
        console.error("Failed fetching reports data:", error);
      } finally {
        setLoading(false);
      }
    };

    fetchReportsData();
  }, [userId]);

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

  // Daily Comparison Engine (Today vs Yesterday)
  const dailyRecap = useMemo(() => {
    const todayStr = getPastDateString(0);
    const yesterdayStr = getPastDateString(1);

    const todaySessions = sessionsList.filter(s => s.date_raw === todayStr);
    const yesterdaySessions = sessionsList.filter(s => s.date_raw === yesterdayStr);

    const calcStats = (sessions: ReportItem[]) => {
      let totalSecs = 0; 
      let totalScoreWeight = 0;
      sessions.forEach(s => {
        totalSecs += s.duration_sec;
        totalScoreWeight += (s.focus_score * s.duration_sec);
      });
      const avgScore = totalSecs > 0 ? Math.round(totalScoreWeight / totalSecs) : 0;
      return { totalSecs, avgScore };
    };

    const todayStats = calcStats(todaySessions);
    const yesterdayStats = calcStats(yesterdaySessions);

    return {
      hasTodayData: todaySessions.length > 0,
      todayTime: todayStats.totalSecs,
      todayScore: todayStats.avgScore,
      timeDiff: todayStats.totalSecs - yesterdayStats.totalSecs,
      scoreDiff: todayStats.avgScore - yesterdayStats.avgScore,
      hasYesterdayData: yesterdaySessions.length > 0
    };
  }, [sessionsList]);

  // Weekly Coaching Engine (Dominant Habit Analysis)
  const weeklyRecap = useMemo(() => {
    const oneWeekAgoStr = getPastDateString(7);
    const weeklySessions = sessionsList.filter(s => s.date_raw >= oneWeekAgoStr);
    
    if (weeklySessions.length === 0) return null;

    let totalScoreWeight = 0;
    let totalMin = 0;
    const totals = { "시선 분산": 0, "자세 불량": 0, "자리 이탈": 0, "과도한 움직임": 0 };

    weeklySessions.forEach(s => {
      totalMin += s.duration_min;
      totalScoreWeight += (s.focus_score * s.duration_min);
      if (s.eventSecs) {
        totals["시선 분산"] += s.eventSecs.gaze;
        totals["자세 불량"] += s.eventSecs.posture;
        totals["자리 이탈"] += s.eventSecs.absent;
        totals["과도한 움직임"] += s.eventSecs.fidget;
      }
    });

    const avgScore = totalMin > 0 ? Math.round(totalScoreWeight / totalMin) : 0;
    
    // Find worst habit
    let worstHabit = "없음";
    let maxSecs = 0;
    Object.entries(totals).forEach(([habit, secs]) => {
      if (secs > maxSecs) {
        maxSecs = secs;
        worstHabit = habit;
      }
    });

    // Smart Case Statements
    let recommendation = "아주 훌륭한 주간 집중도를 보여주었습니다. 현재의 학습 환경과 루틴을 유지하세요!";
    if (worstHabit === "시선 분산") recommendation = "이번 주에는'시선 분산'이 자주 감지되었습니다. 스마트폰을 시야 밖으로 치우거나 주변 시각적 자극이 적은 환경에서 학습을 시작해 보세요.";
    if (worstHabit === "자세 불량") recommendation = "이번 주에는'자세 불량'이 자주 감지되었습니다. 허리와 목의 피로가 누적되면 장기적인 집중력이 떨어질 수 있습니다.";
    if (worstHabit === "자리 이탈") recommendation = "이번 주에는'자리 이탈'이 가장 많이 기록되었습니다. 물이나 필기도구 등 필요한 물품을 미리 준비하여 세션 중 흐름이 끊기는 것을 방지하세요.";
    if (worstHabit === "과도한 움직임") recommendation = "이번 주에는 '과도한 움직임'이 가장 많이 기록되었습니다. 집중력이 떨어질 때는 무리해서 앉아있기보다 5분 정도 가벼운 스트레칭 후 다시 시작하는 것이 좋습니다.";

    return { avgScore, worstHabit, recommendation, hasDistractions: maxSecs > 0 };
  }, [sessionsList]);

  // Pagination Logic
  const sortedSessions = useMemo(() => {
    return [...sessionsList].sort((a, b) => b.id - a.id);
  }, [sessionsList]);

  const totalPages = Math.ceil(sortedSessions.length / itemsPerPage);
  const paginatedSessions = sortedSessions.slice(
    (currentPage - 1) * itemsPerPage,
    currentPage * itemsPerPage
  );

  if (loading) return <div className="p-8 text-center text-muted-foreground">데이터를 분석하는 중...</div>;

  return (
    <div className="p-8 space-y-8 max-w-5xl mx-auto">
      <div>
        <h1 className="text-3xl font-bold text-foreground mb-2">학습 리포트</h1>
        <p className="text-muted-foreground text-lg">
          {userName}님, 오늘의 성과와 주간 피드백을 확인해 보세요.
        </p>
      </div>

      {/* Daily Briefing Section */}
      <div className="space-y-4">
        <h2 className="text-xl font-bold flex items-center gap-2">
          <Calendar className="w-5 h-5 text-primary" /> 일간 요약 (어제와 비교)
        </h2>
        
        <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
          <div className="bg-white rounded-2xl border border-border p-6 shadow-sm">
            <div className="flex items-center gap-3 mb-4 text-muted-foreground">
              <Clock className="w-5 h-5" />
              <span className="font-semibold">오늘 총 학습 시간</span>
            </div>
            <div className="flex items-end justify-between">
              <span className="text-4xl font-extrabold text-foreground">{formatAdaptiveTime(dailyRecap.todayTime)}</span>
              {dailyRecap.hasYesterdayData && (
                <div className={`flex items-center text-sm font-bold px-2.5 py-1 rounded-md ${dailyRecap.timeDiff >= 0 ? "bg-emerald-50 text-emerald-600" : "bg-rose-50 text-rose-500"}`}>
                  {dailyRecap.timeDiff >= 0 ? <ArrowUpRight className="w-4 h-4 mr-1" /> : <ArrowDownRight className="w-4 h-4 mr-1" />}
                  어제 대비 {formatAdaptiveTime(Math.abs(dailyRecap.timeDiff))}
                </div>
              )}
            </div>
          </div>

          <div className="bg-white rounded-2xl border border-border p-6 shadow-sm">
            <div className="flex items-center gap-3 mb-4 text-muted-foreground">
              <Target className="w-5 h-5" />
              <span className="font-semibold">오늘 평균 집중도</span>
            </div>
            <div className="flex items-end justify-between">
              <span className="text-4xl font-extrabold text-foreground">{dailyRecap.todayScore}%</span>
              {dailyRecap.hasYesterdayData && (
                <div className={`flex items-center text-sm font-bold px-2.5 py-1 rounded-md ${dailyRecap.scoreDiff >= 0 ? "bg-emerald-50 text-emerald-600" : "bg-rose-50 text-rose-500"}`}>
                  {dailyRecap.scoreDiff >= 0 ? <ArrowUpRight className="w-4 h-4 mr-1" /> : <ArrowDownRight className="w-4 h-4 mr-1" />}
                  어제 대비 {Math.abs(dailyRecap.scoreDiff)}%
                </div>
              )}
            </div>
          </div>
        </div>
      </div>

      {/* Smart Weekly Coaching Insight */}
      {weeklyRecap && (
        <div className="bg-gradient-to-br from-primary/5 to-accent/30 rounded-2xl border border-primary/20 p-6 shadow-sm">
          <div className="flex items-center gap-3 mb-4">
            <div className="p-2 bg-primary text-white rounded-lg"><Brain className="w-6 h-6" /></div>
            <div>
              <h2 className="text-xl font-bold">주간 AI 학습 코칭</h2>
              <p className="text-sm text-muted-foreground">지난 7일간의 학습 패턴을 분석했습니다.</p>
            </div>
          </div>
          
          <div className="bg-white/80 rounded-xl p-5 border border-primary/10">
            <div className="flex items-start gap-4">
              <AlertCircle className={`w-6 h-6 mt-0.5 ${weeklyRecap.hasDistractions ? "text-orange-500" : "text-emerald-500"}`} />
              <div>
                <h3 className="font-bold text-foreground mb-1 text-lg">
                  주간 평균 집중도: {weeklyRecap.avgScore}% 
                  {weeklyRecap.hasDistractions && <span className="text-muted-foreground text-sm font-normal ml-2">| 주요 방해 요인: {weeklyRecap.worstHabit}</span>}
                </h3>
                <p className="text-muted-foreground leading-relaxed">{weeklyRecap.recommendation}</p>
              </div>
            </div>
          </div>
        </div>
      )}

      {/* Recent Session History Table */}
      <div className="bg-white rounded-2xl border border-border p-6">
        <h2 className="text-xl font-semibold mb-4">전체 세션 기록</h2>
        <div className="overflow-x-auto">
          {sessionsList.length === 0 ? (
            <div className="p-8 text-center text-muted-foreground text-sm">완료된 세션 기록이 없습니다. 첫 세션을 시작해 보세요!</div>
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
                {/* paginatedSessions */}
                {paginatedSessions.map((session) => (
                  <tr key={session.id} className="hover:bg-accent/20 transition-colors group">
                    <td className="py-4 text-sm text-muted-foreground">{session.date}</td>
                    <td className="py-4 text-sm font-semibold text-foreground">세션 #{session.display_index}</td>
                    <td className="py-4 text-sm text-foreground">{formatAdaptiveTime(session.duration_sec)}</td>
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
        {totalPages > 1 && (
          <div className="flex items-center justify-between mt-6 pt-4 border-t border-border">
            <span className="text-sm text-muted-foreground">
              총 {sortedSessions.length}개 중 {(currentPage - 1) * itemsPerPage + 1}-
              {Math.min(currentPage * itemsPerPage, sortedSessions.length)}개 표시
            </span>
            <div className="flex gap-2">
              <button
                onClick={() => setCurrentPage(p => Math.max(1, p - 1))}
                disabled={currentPage === 1}
                className="px-4 py-2 text-sm font-medium rounded-lg border border-border bg-white text-foreground hover:bg-accent disabled:opacity-50 disabled:cursor-not-allowed transition-colors"
              >
                이전
              </button>
              <button
                onClick={() => setCurrentPage(p => Math.min(totalPages, p + 1))}
                disabled={currentPage === totalPages}
                className="px-4 py-2 text-sm font-medium rounded-lg border border-border bg-white text-foreground hover:bg-accent disabled:opacity-50 disabled:cursor-not-allowed transition-colors"
              >
                다음
              </button>
            </div>
          </div>
        )}
      </div>
    </div>
  );
}