import { useState } from "react";
import { Link } from "react-router";
import { Filter, ChevronRight } from "lucide-react";
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

const monthlyData = [
  { month: "Sep", hours: 98 },
  { month: "Oct", hours: 112 },
  { month: "Nov", hours: 95 },
  { month: "Dec", hours: 127 },
  { month: "Jan", hours: 118 },
  { month: "Feb", hours: 124 },
];

const performanceData = [
  { week: "Week 1", focus: 85, productivity: 78 },
  { week: "Week 2", focus: 92, productivity: 88 },
  { week: "Week 3", focus: 78, productivity: 72 },
  { week: "Week 4", focus: 95, productivity: 91 },
];

export function Reports() {
  const [timeRange, setTimeRange] = useState<"week" | "month" | "year">("month");

  return (
    <div className="p-8 space-y-8 max-w-7xl mx-auto">
      <div className="flex items-center justify-between">
        <div>
          <h1 className="text-3xl font-bold text-foreground mb-1">상세 보고서</h1>
          <p className="text-muted-foreground">
            학습 세션에 대한 종합 분석
          </p>
        </div>
        <select
          value={timeRange}
          onChange={(e) => setTimeRange(e.target.value as any)}
          className="px-4 py-2 bg-white border border-border rounded-lg focus:outline-none focus:ring-2 focus:ring-primary/50"
        >
          <option value="week">지난 주</option>
          <option value="month">지난 달</option>
          <option value="year">지난 해</option>
        </select>
      </div>

      <div className="grid grid-cols-1 md:grid-cols-4 gap-6">
        <SummaryCard label="총 시간" value="124" unit="hrs" />
        <SummaryCard label="세션" value="42" unit="sessions" />
        <SummaryCard label="평균 시간" value="2.9" unit="hrs" />
        <SummaryCard label="집중도 점수" value="89" unit="%" />
      </div>

      <div className="grid grid-cols-1 lg:grid-cols-2 gap-6">
        <div className="bg-white rounded-2xl border border-border p-6">
          <h2 className="text-xl font-semibold mb-4">학습 시간 추이</h2>
          <ResponsiveContainer width="100%" height={300}>
            <BarChart data={monthlyData}>
              <CartesianGrid strokeDasharray="3 3" stroke="#f0f0f0" />
              <XAxis dataKey="month" stroke="#888" fontSize={12} />
              <YAxis stroke="#888" fontSize={12} />
              <Tooltip
                contentStyle={{
                  backgroundColor: "#fff",
                  border: "1px solid #e5e5e5",
                  borderRadius: "8px",
                }}
              />
              <Bar dataKey="hours" fill="#1a667a" radius={[8, 8, 0, 0]} />
            </BarChart>
          </ResponsiveContainer>
        </div>

        <div className="bg-white rounded-2xl border border-border p-6">
          <h2 className="text-xl font-semibold mb-4">집중도 점수 추이</h2>
          <ResponsiveContainer width="100%" height={300}>
            <LineChart data={performanceData}>
              <CartesianGrid strokeDasharray="3 3" stroke="#f0f0f0" />
              <XAxis dataKey="week" stroke="#888" fontSize={12} />
              <YAxis stroke="#888" fontSize={12} domain={[0, 100]} />
              <Tooltip
                contentStyle={{
                  backgroundColor: "#fff",
                  border: "1px solid #e5e5e5",
                  borderRadius: "8px",
                }}
              />
              <Line
                type="monotone"
                dataKey="focus"
                stroke="#1a667a"
                strokeWidth={2}
                dot={{ fill: "#1a667a", r: 4 }}
                name="Focus Score"
              />
            </LineChart>
          </ResponsiveContainer>
        </div>
      </div>

      <div className="bg-white rounded-2xl border border-border p-6">
        <div className="flex items-center justify-between mb-4">
          <h2 className="text-xl font-semibold">세션 기록</h2>
          <button className="flex items-center gap-2 text-sm text-muted-foreground hover:text-foreground">
            <Filter className="w-4 h-4" />
            <span>필터</span>
          </button>
        </div>
        <div className="overflow-x-auto">
          <table className="w-full">
            <thead className="border-b border-border">
              <tr className="text-left">
                <th className="pb-3 text-sm font-medium text-muted-foreground">날짜</th>
                <th className="pb-3 text-sm font-medium text-muted-foreground">세션</th>
                <th className="pb-3 text-sm font-medium text-muted-foreground">시간</th>
                <th className="pb-3 text-sm font-medium text-muted-foreground">집중도</th>
                <th className="pb-3 text-sm font-medium text-muted-foreground"></th>
              </tr>
            </thead>
            <tbody className="divide-y divide-border">
              <SessionRow
                id="1"
                date="Mar 23, 2026"
                sessionName="Session 43"
                duration="2h 15m"
                focus={95}
              />
              <SessionRow
                id="2"
                date="Mar 23, 2026"
                sessionName="Session 42"
                duration="1h 45m"
                focus={100}
              />
              <SessionRow
                id="3"
                date="Mar 22, 2026"
                sessionName="Session 41"
                duration="3h 00m"
                focus={85}
              />
              <SessionRow
                id="4"
                date="Mar 22, 2026"
                sessionName="Session 40"
                duration="1h 30m"
                focus={90}
              />
              <SessionRow
                id="5"
                date="Mar 21, 2026"
                sessionName="Session 39"
                duration="2h 45m"
                focus={92}
              />
            </tbody>
          </table>
        </div>
      </div>
    </div>
  );
}

function SummaryCard({
  label,
  value,
  unit,
}: {
  label: string;
  value: string;
  unit: string;
}) {
  return (
    <div className="bg-white rounded-2xl border border-border p-6">
      <div className="text-sm text-muted-foreground mb-2">{label}</div>
      <div className="flex items-baseline gap-1">
        <span className="text-3xl font-bold text-primary">{value}</span>
        <span className="text-sm text-muted-foreground">{unit}</span>
      </div>
    </div>
  );
}

function SessionRow({
  id,
  date,
  sessionName,
  duration,
  focus,
}: {
  id: string;
  date: string;
  sessionName: string;
  duration: string;
  focus: number;
}) {
  return (
    <tr className="hover:bg-accent/20 transition-colors cursor-pointer group">
      <td className="py-4 text-sm">{date}</td>
      <td className="py-4 text-sm font-medium">{sessionName}</td>
      <td className="py-4 text-sm">{duration}</td>
      <td className="py-4">
        <div className="flex items-center gap-2">
          <div className="flex-1 max-w-[100px] bg-muted rounded-full h-2">
            <div
              className="bg-primary rounded-full h-2"
              style={{ width: `${focus}%` }}
            />
          </div>
          <span className="text-sm font-medium">{focus}%</span>
        </div>
      </td>
      <td className="py-4 text-right">
        <Link 
          to={`/app/reports/${id}`}
          className="inline-flex items-center gap-1 text-sm text-primary hover:underline"
        >
          <span className="opacity-0 group-hover:opacity-100 transition-opacity">세부 정보 보기</span>
          <ChevronRight className="w-4 h-4" />
        </Link>
      </td>
    </tr>
  );
}