import { useMemo, useState } from "react";
import { ChevronDown } from "lucide-react";

interface HeatmapProps {
  rawSessions: Array<{date: string; date_raw: string; duration_min: number; duration_sec?: number; focus_score: number }>;
}

export function ActivityHeatmap({ rawSessions = [] }: HeatmapProps) {
  const currentYear = new Date().getFullYear();
  const [selectedYear, setSelectedYear] = useState(currentYear);
  const [dropdownOpen, setDropdownOpen] = useState(false);

  const availableYears = [currentYear, currentYear - 1, currentYear - 2];

  // time formatter 
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

  const activityData = useMemo(() => {
    const data: { date: Date; count: number; focus: number }[] = [];
    const startDate = new Date(selectedYear, 0, 1);
    const endDate = new Date(selectedYear, 11, 31);
    
    const sessionMap: { [key: string]: { seconds: number; focusWeight: number } } = {};
    
    rawSessions.forEach((s) => {
      try {
        const dateKey = s.date_raw; 
        if (dateKey) {
          const secs = s.duration_sec || (s.duration_min * 60);
          if (!sessionMap[dateKey]) sessionMap[dateKey] = { seconds: 0, focusWeight: 0 };
          
          sessionMap[dateKey].seconds += secs;
          sessionMap[dateKey].focusWeight += ((s.focus_score || 0) * secs);
        }
      } catch (e) {}
    });

    const currentDate = new Date(startDate);
    while (currentDate <= endDate) {
      const year = currentDate.getFullYear();
      const month = String(currentDate.getMonth() + 1).padStart(2, "0");
      const day = String(currentDate.getDate()).padStart(2, "0");
      const dateKey = `${year}-${month}-${day}`;
      
      const mapData = sessionMap[dateKey];
      const actualSecs = mapData ? mapData.seconds : 0;
      const avgFocus = mapData && mapData.seconds > 0 ? Math.round(mapData.focusWeight / mapData.seconds) : 0;
      
      data.push({
        date: new Date(currentDate),
        count: actualSecs, 
        focus: avgFocus
      });
      
      currentDate.setDate(currentDate.getDate() + 1);
    }
    return data;
  }, [selectedYear, rawSessions]);

  // Organize data by day of week for each week column
  const gridData = useMemo(() => {
    // Find the starting Sunday
    const firstDate = activityData[0]?.date;
    if (!firstDate) return { weeks: [], monthLabels: [] };
    
    const startDay = firstDate.getDay(); // 0 = Sunday, 1 = Monday, etc.
    
    // Create 7 rows (one for each day of week) x N columns (weeks)
    const weeks: ({ date: Date; count: number; focus: number } | null)[][] = [];
    
    // Fill empty days at the beginning to align with day of week
    let currentWeek: ({ date: Date; count: number; focus: number } | null)[] = new Array(7).fill(null);
    
    activityData.forEach((day) => {
      const dayOfWeek = day.date.getDay();
      currentWeek[dayOfWeek] = day;
      
      // If it's Saturday, push the week and start a new one
      if (dayOfWeek === 6) {
        weeks.push([...currentWeek]);
        currentWeek = new Array(7).fill(null);
      }
    });
    
    // Push remaining days
    if (currentWeek.some(day => day !== null)) {
      weeks.push(currentWeek);
    }
    
    // Calculate month labels
    const monthLabels: { month: string; weekIndex: number }[] = [];
    let currentMonth = -1;
    
    weeks.forEach((week, weekIndex) => {
      const firstDayInWeek = week.find(day => day !== null);
      if (firstDayInWeek) {
        const month = firstDayInWeek.date.getMonth();
        if (month !== currentMonth && weekIndex > 0) {
          monthLabels.push({
            month: firstDayInWeek.date.toLocaleDateString('en-US', { month: 'short' }),
            weekIndex,
          });
          currentMonth = month;
        } else if (weekIndex === 0) {
          monthLabels.push({
            month: firstDayInWeek.date.toLocaleDateString('en-US', { month: 'short' }),
            weekIndex: 0,
          });
          currentMonth = month;
        }
      }
    });
    
    return { weeks, monthLabels };
  }, [activityData]);

  const getColor = (count: number) => {
    if (count === 0) return "bg-muted/30";
    if (count <= 7200) return "bg-[#b4dfe9]"; 
    if (count <= 14400) return "bg-[#5ab3c7]";
    return "bg-primary";
  };

  const dayLabels = ["Sun", "Mon", "Tue", "Wed", "Thu", "Fri", "Sat"];

  return (
    <div>
      {/* Year Selector */}
      <div className="relative mb-4 inline-block">
        <button
          onClick={() => setDropdownOpen(!dropdownOpen)}
          className="flex items-center gap-1 px-3 py-1.5 text-sm rounded-lg transition-colors bg-muted/50 text-foreground hover:bg-muted border border-border"
        >
          <span>{selectedYear}</span>
          <ChevronDown className="w-4 h-4" />
        </button>
        {dropdownOpen && (
          <>
            {/* Backdrop to close dropdown */}
            <div
              className="fixed inset-0 z-10"
              onClick={() => setDropdownOpen(false)}
            />
            {/* Dropdown menu */}
            <div className="absolute top-full left-0 mt-1 bg-white border border-border rounded-lg shadow-lg z-20 min-w-[100px]">
              {availableYears.map((year) => (
                <button
                  key={year}
                  onClick={() => {
                    setSelectedYear(year);
                    setDropdownOpen(false);
                  }}
                  className={`w-full text-left px-4 py-2 text-sm transition-colors first:rounded-t-lg last:rounded-b-lg ${
                    year === selectedYear
                      ? "bg-primary text-primary-foreground"
                      : "text-foreground hover:bg-accent"
                  }`}
                >
                  {year}
                </button>
              ))}
            </div>
          </>
        )}
      </div>

      <div className="overflow-x-auto">
        <div className="inline-block min-w-full">
          <div className="flex gap-1">
            {/* Day labels */}
            <div className="flex flex-col gap-1 pr-2 pt-6">
              {dayLabels.map((day, i) => (
                <div
                  key={i}
                  className="text-xs text-muted-foreground h-3 flex items-center"
                  style={{ opacity: i % 2 === 1 ? 1 : 0 }}
                >
                  {i % 2 === 1 ? day : ""}
                </div>
              ))}
            </div>

            {/* Heatmap grid container */}
            <div>
              {/* Month labels */}
              <div className="relative h-6 mb-1">
                {gridData.monthLabels.map((label, i) => (
                  <div
                    key={i}
                    className="absolute text-xs text-muted-foreground"
                    style={{ left: `${label.weekIndex * 16}px` }}
                  >
                    {label.month}
                  </div>
                ))}
              </div>

              {/* Grid */}
              <div className="flex gap-1">
                {gridData.weeks.map((week, weekIndex) => (
                  <div key={weekIndex} className="flex flex-col gap-1">
                    {week.map((day, dayIndex) => (
                      <div
                        key={dayIndex}
                        className={`w-3 h-3 rounded-sm ${
                          day ? getColor(day.count) : "bg-transparent"
                        } ${
                          day ? "hover:ring-2 hover:ring-primary/50 transition-all cursor-pointer" : ""
                        }`}
                        title={
                          day && day.count > 0
                            ? `${day.date.toLocaleDateString()}: ${formatAdaptiveTime(day.count)} | 집중도: ${day.focus}%`
                            : ""
                        }
                      />
                    ))}
                  </div>
                ))}
              </div>
            </div>
          </div>

          {/* Legend */}
          <div className="flex items-center gap-2 mt-4 text-xs text-muted-foreground">
            <span>Less</span>
            <div className="flex gap-1">
              <div className="w-3 h-3 rounded-sm bg-muted/30" />
              <div className="w-3 h-3 rounded-sm bg-[#b4dfe9]" />
              <div className="w-3 h-3 rounded-sm bg-[#5ab3c7]" />
              <div className="w-3 h-3 rounded-sm bg-primary" />
            </div>
            <span>More</span>
          </div>
        </div>
      </div>
    </div>
  );
}