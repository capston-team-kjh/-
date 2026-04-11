import { createBrowserRouter } from "react-router";
import { Landing } from "./pages/landing";
import { Login } from "./pages/login";
import { Signup } from "./pages/signup";
import { Dashboard } from "./pages/dashboard";
import { Settings } from "./pages/settings";
import { Reports } from "./pages/reports";
import { StudySession } from "./pages/study-session";
import { SessionDetail } from "./pages/session-detail";
import { DashboardLayout } from "./components/dashboard-layout";

export const router = createBrowserRouter([
  {
    path: "/",
    Component: Landing,
  },
  {
    path: "/login",
    Component: Login,
  },
  {
    path: "/signup",
    Component: Signup,
  },
  {
    path: "/app",
    Component: DashboardLayout,
    children: [
      {
        index: true,
        Component: Dashboard,
      },
      {
        path: "session",
        Component: StudySession,
      },
      {
        path: "reports",
        Component: Reports,
      },
      {
        path: "reports/:sessionId",
        Component: SessionDetail,
      },
      {
        path: "settings",
        Component: Settings,
      },
    ],
  },
]);