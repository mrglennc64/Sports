import { BrowserRouter as Router, Routes, Route, Navigate } from 'react-router-dom'
import { useAuthStore } from './store/auth'
import { Navbar } from './components/Navbar'
import { LoginPage } from './pages/LoginPage'
import { SignupPage } from './pages/SignupPage'
import { DashboardPage } from './pages/DashboardPage'
import { CLVTrackerPage } from './pages/CLVTrackerPage'
import { PredictionsPage } from './pages/PredictionsPage'
import { PlaceBetPage } from './pages/PlaceBetPage'
import { PositionsPage } from './pages/PositionsPage'
import { AuditPage } from './pages/AuditPage'
import { LandingPage } from './pages/LandingPage'
import { VerticalPage } from './pages/VerticalPage'
import { PortfolioPage } from './pages/PortfolioPage'

function App() {
  const token = useAuthStore((state) => state.token)
  const isAuthenticated = !!token

  return (
    <Router>
      <div className="min-h-screen bg-gray-900">
        {isAuthenticated && <Navbar />}
        <main className={isAuthenticated ? "max-w-7xl mx-auto px-4 py-8" : ""}>
          <Routes>
            <Route path="/" element={isAuthenticated ? <DashboardPage /> : <LandingPage />} />
            <Route path="/dashboard" element={isAuthenticated ? <DashboardPage /> : <Navigate to="/login" />} />
            <Route path="/verticals/:vertical" element={isAuthenticated ? <VerticalPage /> : <Navigate to="/login" />} />
            <Route path="/login" element={<LoginPage />} />
            <Route path="/signup" element={<SignupPage />} />
            <Route
              path="/clv-tracker"
              element={isAuthenticated ? <CLVTrackerPage /> : <Navigate to="/login" />}
            />
            <Route
              path="/predictions"
              element={isAuthenticated ? <PredictionsPage /> : <Navigate to="/login" />}
            />
            <Route
              path="/place-bet"
              element={isAuthenticated ? <PlaceBetPage /> : <Navigate to="/login" />}
            />
            <Route
              path="/positions"
              element={isAuthenticated ? <PositionsPage /> : <Navigate to="/login" />}
            />
            <Route
              path="/audit"
              element={isAuthenticated ? <AuditPage /> : <Navigate to="/login" />}
            />
            <Route
              path="/portfolio"
              element={isAuthenticated ? <PortfolioPage /> : <Navigate to="/login" />}
            />
          </Routes>
        </main>
      </div>
    </Router>
  )
}

export default App
