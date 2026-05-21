import { Navigate, Route, Routes } from "react-router-dom"

import { AppFrame } from "@/components/app/app-frame"
import { AdminPage } from "@/pages/admin-page"
import { AutoBetPage } from "@/pages/auto-bet-page"
import { CommandsPage } from "@/pages/commands-page"
import { DashboardPage } from "@/pages/dashboard-page"
import { QuizPage } from "@/pages/dashboard-page-shadcn"
import { GiveawaysPage } from "@/pages/giveaways-page"
import { LoginPage } from "@/pages/login-page"
import { StatsPage } from "@/pages/stats-page"
import { TimerPage } from "@/pages/timer-page"

export function App() {
  return (
    <Routes>
      <Route path="/" element={<LoginPage />} />
      <Route element={<AppFrame />}>
        <Route path="/dashboard" element={<DashboardPage />} />
        <Route path="/quiz" element={<QuizPage />} />
        <Route path="/commands" element={<CommandsPage />} />
        <Route path="/giveaways" element={<GiveawaysPage />} />
        <Route path="/autobet" element={<AutoBetPage />} />
        <Route path="/stats" element={<StatsPage />} />
        <Route path="/timers" element={<TimerPage />} />
        <Route path="/admin" element={<AdminPage />} />
      </Route>
      <Route path="*" element={<Navigate to="/dashboard" replace />} />
    </Routes>
  )
}
