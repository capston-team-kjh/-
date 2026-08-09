import { useState } from "react";
import { Outlet, Link, useLocation } from "react-router";
import { LayoutDashboard, Play, BarChart3, Settings, LogOut, Menu, X } from "lucide-react";
import logo from "../assets/joljak_logo.png";

export function DashboardLayout() {
  const location = useLocation();
  const [mobileMenuOpen, setMobileMenuOpen] = useState(false);

  // Check if device is mobile
  const isMobile = typeof window !== "undefined" && /iPhone|iPad|iPod|Android/i.test(navigator.userAgent);

  const isActive = (path: string) => {
    if (path === "/app") {
      return location.pathname === "/app";
    }
    return location.pathname.startsWith(path);
  };

  return (
    <div className="min-h-screen bg-background flex flex-col md:flex-row">
      {/* ================= MOBILE HEADER & DROPDOWN MENU ================= */}
      {/* 1. Changed to 'fixed' to guarantee it hovers over the page no matter what */}
      <div className="md:hidden fixed top-0 left-0 w-full z-50">
        <header className="bg-white border-b border-border p-4 flex items-center justify-between">
          <Link to="/app" className="flex items-center gap-2">
            <img src={logo} alt="FocusAI" className="h-8 w-auto" />
            <span className="text-lg font-semibold text-foreground">FocusAI</span>
          </Link>
          <button
            onClick={() => setMobileMenuOpen(!mobileMenuOpen)}
            className="p-2 text-muted-foreground hover:text-foreground rounded-lg bg-accent/50"
          >
            {mobileMenuOpen ? <X className="w-6 h-6" /> : <Menu className="w-6 h-6" />}
          </button>
        </header>

        {/* 2. Added max-h-[80vh] and overflow-y-auto so the menu scrolls if needed */}
        {mobileMenuOpen && (
          <div className="absolute top-full left-0 w-full bg-white border-b border-border p-4 space-y-2 animate-in slide-in-from-top duration-200 shadow-lg max-h-[80vh] overflow-y-auto">
            <NavLink
              to="/app"
              icon={<LayoutDashboard className="w-5 h-5" />}
              label="대시보드"
              active={isActive("/app")}
              onClick={() => setMobileMenuOpen(false)}
            />
            {/* Hide 'Start Session' completely on Mobile */}
            {!isMobile && (
              <NavLink
                to="/app/session"
                icon={<Play className="w-5 h-5" />}
                label="세션 시작"
                active={isActive("/app/session")}
                onClick={() => setMobileMenuOpen(false)}
              />
            )}
            <NavLink
              to="/app/reports"
              icon={<BarChart3 className="w-5 h-5" />}
              label="리포트"
              active={isActive("/app/reports")}
              onClick={() => setMobileMenuOpen(false)}
            />
            <NavLink
              to="/app/settings"
              icon={<Settings className="w-5 h-5" />}
              label="설정"
              active={isActive("/app/settings")}
              onClick={() => setMobileMenuOpen(false)}
            />
            <div className="pt-2 border-t border-border">
              <Link
                to="/"
                onClick={() => setMobileMenuOpen(false)}
                className="flex items-center gap-2 p-3 text-sm text-muted-foreground hover:text-foreground hover:bg-accent rounded-lg transition-colors"
              >
                <LogOut className="w-4 h-4" />
                <span>로그아웃</span>
              </Link>
            </div>
          </div>
        )}
      </div> 
      {/* ^^^ This was the missing closing tag! ^^^ */}

      {/* ================= DESKTOP SIDEBAR ================= */}
      <aside className="hidden md:flex w-64 bg-white border-r border-border flex-col shrink-0">
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
          {!isMobile && (
            <NavLink
              to="/app/session"
              icon={<Play className="w-5 h-5" />}
              label="세션 시작"
              active={isActive("/app/session")}
            />
          )}
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

      {/* Main Content Area */}
      {/* 3. Added pt-[73px] so the content doesn't hide under the fixed mobile header */}
      <main className="flex-1 overflow-auto w-full pt-[73px] md:pt-0">
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
  onClick,
}: {
  to: string;
  icon: React.ReactNode;
  label: string;
  active: boolean;
  onClick?: () => void;
}) {
  return (
    <Link
      to={to}
      onClick={onClick}
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