import { BrowserRouter, NavLink, Routes, Route, Navigate } from "react-router-dom";
import Dashboard from "./pages/Dashboard";
import Portfolio from "./pages/Portfolio";
import { useWebSocket } from "./hooks/useWebSocket";

function Nav({ connected }: { connected: boolean }) {
  const linkClass = ({ isActive }: { isActive: boolean }) =>
    `px-4 py-2 rounded text-sm font-medium transition-colors ${
      isActive
        ? "bg-surface-2 text-white"
        : "text-slate-400 hover:text-slate-200 hover:bg-surface-2"
    }`;

  return (
    <nav className="flex items-center gap-1 px-4 py-2 bg-surface-1 border-b border-surface-3">
      <span className="text-accent-green font-bold text-base mr-4 select-none">
        🍳 Polycook
      </span>
      <NavLink to="/dashboard" className={linkClass}>
        Scanner
      </NavLink>
      <NavLink to="/portfolio" className={linkClass}>
        Portfolio
      </NavLink>
      <div className="ml-auto flex items-center gap-2 text-xs text-slate-500">
        <span
          className={`w-2 h-2 rounded-full ${
            connected ? "bg-accent-green" : "bg-accent-red animate-pulse"
          }`}
        />
        <span>{connected ? "Live" : "Connecting…"}</span>
      </div>
    </nav>
  );
}

export default function App() {
  const liveState = useWebSocket();

  return (
    <BrowserRouter>
      <div className="flex flex-col h-full">
        <Nav connected={liveState.connected} />
        <main className="flex-1 overflow-hidden">
          <Routes>
            <Route path="/" element={<Navigate to="/dashboard" replace />} />
            <Route
              path="/dashboard"
              element={<Dashboard liveState={liveState} />}
            />
            <Route
              path="/portfolio"
              element={<Portfolio liveState={liveState} />}
            />
          </Routes>
        </main>
      </div>
    </BrowserRouter>
  );
}
