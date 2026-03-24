import { useState } from 'react';
import { BrowserRouter, Routes, Route, Navigate } from 'react-router-dom';
import { getToken, clearToken } from './api/client';
import Sidebar from './components/Sidebar';
import Dashboard from './pages/Dashboard';
import Positions from './pages/Positions';
import Pipeline from './pages/Pipeline';
import Agents from './pages/Agents';
import AgentDetail from './pages/AgentDetail';
import Trades from './pages/Trades';
import Login from './pages/Login';

function PrivateRoute({ children, isAuth }) {
  return isAuth ? children : <Navigate to="/login" replace />;
}

export default function App() {
  const [isAuth, setIsAuth] = useState(!!getToken());

  function handleLogin() {
    setIsAuth(true);
  }

  function handleLogout() {
    clearToken();
    setIsAuth(false);
  }

  return (
    <BrowserRouter>
      <Routes>
        <Route path="/login" element={
          isAuth ? <Navigate to="/" replace /> : <Login onLogin={handleLogin} />
        } />
        <Route path="/*" element={
          <PrivateRoute isAuth={isAuth}>
            <Sidebar onLogout={handleLogout} />
            <main className="ml-64 flex-1 p-6 min-h-screen">
              <Routes>
                <Route path="/" element={<Dashboard />} />
                <Route path="/positions" element={<Positions />} />
                <Route path="/pipeline" element={<Pipeline />} />
                <Route path="/agents" element={<Agents />} />
                <Route path="/agents/:agentId" element={<AgentDetail />} />
                <Route path="/trades" element={<Trades />} />
              </Routes>
            </main>
          </PrivateRoute>
        } />
      </Routes>
    </BrowserRouter>
  );
}
