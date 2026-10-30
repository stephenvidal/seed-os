import { AlertTriangle } from "lucide-react";
import { Suspense, lazy } from "react";
import { Route, Routes } from "react-router-dom";
import { AppShell } from "./components/shell/AppShell";
import { BrandMark } from "./components/shell/BrandMark";
import { Button } from "./components/ui/Button";
import { useSession } from "./lib/auth";
import { AgentsPage } from "./pages/Agents";
import { SchedulesPage } from "./pages/Schedules";
import { ModelsPage } from "./pages/areas";
import { ToolsPage } from "./pages/Tools";
import { ProjectPage, ProjectsPage } from "./pages/Projects";
import { StudioArtifactPage, StudioPage } from "./pages/Studio";
import { CommandCenterPage } from "./pages/CommandCenter";
import { InspectorPage, InspectorTaskPage } from "./pages/Inspector";
import { LoginPage } from "./pages/Login";
import { NotFoundPage } from "./pages/NotFound";
import { SettingsPage } from "./pages/Settings";
import { TaskDetailPage, TasksPage } from "./pages/Tasks";

// Chat carries the Markdown renderer (~50 kB gzip); load it only when opened.
const ChatPage = lazy(() => import("./pages/Chat").then((m) => ({ default: m.ChatPage })));
const chat = (
  <Suspense fallback={<p className="text-xs text-fg-muted">Loading…</p>}>
    <ChatPage />
  </Suspense>
);

export function App() {
  const session = useSession();

  if (session.isPending)
    return (
      <div className="grid h-full place-items-center text-fg-subtle" aria-busy="true">
        <span className="animate-pulse">
          <BrandMark size={28} />
        </span>
      </div>
    );

  if (session.isError)
    return (
      <div className="grid h-full place-items-center px-4">
        <div role="alert" className="flex max-w-sm flex-col items-center gap-3 text-center">
          <AlertTriangle className="text-danger" aria-hidden />
          <p className="text-sm font-medium">{session.error.message}</p>
          <p className="text-xs text-fg-muted">Check that the SEED API is running, then retry.</p>
          <Button onClick={() => session.refetch()}>Retry</Button>
        </div>
      </div>
    );

  if (!session.data) return <LoginPage />;

  return (
    <Routes>
      <Route element={<AppShell />}>
        <Route index element={<CommandCenterPage />} />
        <Route path="chat" element={chat} />
        <Route path="chat/:id" element={chat} />
        <Route path="tasks" element={<TasksPage />} />
        <Route path="tasks/:id" element={<TaskDetailPage />} />
        <Route path="agents" element={<AgentsPage />} />
        <Route path="schedules" element={<SchedulesPage />} />
        <Route path="projects" element={<ProjectsPage />} />
        <Route path="projects/:id" element={<ProjectPage />} />
        <Route path="studio" element={<StudioPage />} />
        <Route path="studio/:id" element={<StudioArtifactPage />} />
        <Route path="inspector" element={<InspectorPage />} />
        <Route path="inspector/:id" element={<InspectorTaskPage />} />
        <Route path="models" element={<ModelsPage />} />
        <Route path="tools" element={<ToolsPage />} />
        <Route path="settings" element={<SettingsPage />} />
        <Route path="*" element={<NotFoundPage />} />
      </Route>
    </Routes>
  );
}
