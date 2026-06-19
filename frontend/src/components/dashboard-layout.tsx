import { Outlet, Link, useLocation } from "react-router";
import { LayoutDashboard, Play, BarChart3, Settings, LogOut } from "lucide-react";
import logo from "../assets/joljak_logo.png";

export function DashboardLayout() {
  const location = useLocation();

  const isActive = (path: string) => {
    if (path === "/app") {
      return location.pathname === "/app";
    }
    return location.pathname.startsWith(path);
  };

  return (
    <div className="min-h-screen bg-background flex">
      <aside className="w-64 bg-white border-r border-border flex flex-col">
        <div className="p-6 border-b border-border">
          <Link to="/app" className="flex items-center gap-3">
            <img src={logo} alt="FocusAI" className="h-10 w-auto" />
            <span className="text-xl font-semibold text-foreground">FocusAI</span>
          </Link>
        </div>

        <nav className="flex-1 p-4 space-y-1">
          <NavLink
            to="/app"
            icon={<LayoutDashboard className="w-5 h-5" />}
            label="대시보드"
            active={isActive("/app")}
          />
          <NavLink
            to="/app/session"
            icon={<Play className="w-5 h-5" />}
            label="세션 시작"
            active={isActive("/app/session")}
          />
          <NavLink
            to="/app/reports"
            icon={<BarChart3 className="w-5 h-5" />}
            label="리포트"
            active={isActive("/app/reports")}
          />
          <NavLink
            to="/app/settings"
            icon={<Settings className="w-5 h-5" />}
            label="설정"
            active={isActive("/app/settings")}
          />
        </nav>

        <div className="p-4 border-t border-border">
          <Link
            to="/"
            className="flex items-center gap-2 p-2 text-sm text-muted-foreground hover:text-foreground hover:bg-accent rounded-lg transition-colors"
          >
            <LogOut className="w-4 h-4" />
            <span>로그아웃</span>
          </Link>
        </div>
      </aside>

      <main className="flex-1 overflow-auto">
        <Outlet />
      </main>
    </div>
  );
}

function NavLink({
  to,
  icon,
  label,
  active,
}: {
  to: string;
  icon: React.ReactNode;
  label: string;
  active: boolean;
}) {
  return (
    <Link
      to={to}
      className={`flex items-center gap-3 px-4 py-3 rounded-lg transition-colors ${
        active
          ? "bg-primary text-primary-foreground"
          : "text-muted-foreground hover:bg-accent hover:text-foreground"
      }`}
    >
      {icon}
      <span>{label}</span>
    </Link>
  );
}