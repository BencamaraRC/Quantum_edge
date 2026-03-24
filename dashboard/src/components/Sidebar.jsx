import { NavLink } from 'react-router-dom';
import { useState } from 'react';
import {
  Zap,
  LayoutDashboard,
  BarChart3,
  GitBranch,
  Bot,
  History,
  ShieldAlert,
  LogOut,
} from 'lucide-react';
import usePortfolioData from '../hooks/usePortfolioData';
import { activateKillSwitch } from '../api/client';

const navItems = [
  { to: '/', icon: LayoutDashboard, label: 'Dashboard' },
  { to: '/positions', icon: BarChart3, label: 'Positions' },
  { to: '/pipeline', icon: GitBranch, label: 'Pipeline' },
  { to: '/agents', icon: Bot, label: 'Agents' },
  { to: '/trades', icon: History, label: 'Trades' },
];

export default function Sidebar({ onLogout }) {
  const [killArmed, setKillArmed] = useState(false);
  const [killLoading, setKillLoading] = useState(false);
  const { portfolio } = usePortfolioData(10000);

  const equity = portfolio?.equity ?? 0;
  const dailyPnl = portfolio?.daily_pnl ?? 0;
  const dailyPnlPct = portfolio?.daily_pnl_pct ?? 0;

  const handleKillSwitch = async () => {
    setKillLoading(true);
    try {
      await activateKillSwitch();
      setKillArmed(false);
    } catch (err) {
      alert(`Kill switch failed: ${err.message}`);
    } finally {
      setKillLoading(false);
    }
  };

  return (
    <aside className="w-64 min-h-screen bg-[#0d1117] border-r border-[#1e2433] flex flex-col fixed left-0 top-0 bottom-0 z-50">
      {/* Logo */}
      <div className="px-5 py-6 flex items-center gap-3">
        <div className="w-9 h-9 rounded-lg bg-amber-500/15 flex items-center justify-center">
          <Zap className="w-5 h-5 text-amber-500" />
        </div>
        <div>
          <h1 className="text-base font-bold text-white tracking-tight">Quantum Edge</h1>
          <p className="text-[10px] text-gray-500 uppercase tracking-widest">Trading System</p>
        </div>
      </div>

      {/* System Status */}
      <div className="mx-4 mb-5 px-3 py-2.5 rounded-lg bg-[#141820] border border-[#1e2433]">
        <div className="flex items-center gap-2 mb-1.5">
          <span className={`w-2 h-2 rounded-full ${portfolio ? 'bg-emerald-500 animate-pulse' : 'bg-gray-500'}`} />
          <span className="text-[11px] font-medium text-emerald-400 uppercase tracking-wider">
            {portfolio ? 'PAPER TRADING' : 'CONNECTING...'}
          </span>
        </div>
        <p className="text-lg font-semibold text-white">
          ${equity.toLocaleString('en-US', { minimumFractionDigits: 2 })}
        </p>
        <p className={`text-xs font-medium ${dailyPnl >= 0 ? 'text-emerald-400' : 'text-red-400'}`}>
          {dailyPnl >= 0 ? '+' : ''}${dailyPnl.toLocaleString('en-US', { minimumFractionDigits: 2 })}
          {' '}({dailyPnlPct >= 0 ? '+' : ''}{dailyPnlPct.toFixed(2)}%)
        </p>
      </div>

      {/* Navigation */}
      <nav className="flex-1 px-3">
        <p className="px-3 mb-2 text-[10px] font-semibold text-gray-500 uppercase tracking-widest">Navigation</p>
        {navItems.map(({ to, icon: Icon, label }) => (
          <NavLink
            key={to}
            to={to}
            end={to === '/'}
            className={({ isActive }) =>
              `flex items-center gap-3 px-3 py-2.5 rounded-lg mb-0.5 text-sm font-medium transition-colors ${
                isActive
                  ? 'bg-amber-500/10 text-amber-500'
                  : 'text-gray-400 hover:text-gray-200 hover:bg-[#141820]'
              }`
            }
          >
            <Icon className="w-[18px] h-[18px]" />
            {label}
          </NavLink>
        ))}
      </nav>

      {/* Kill Switch */}
      <div className="p-4">
        {killArmed ? (
          <div className="space-y-2">
            <p className="text-xs text-red-400 text-center font-medium">Confirm kill switch?</p>
            <div className="flex gap-2">
              <button
                onClick={() => setKillArmed(false)}
                className="flex-1 py-2 rounded-lg text-xs font-medium border border-[#1e2433] text-gray-400 hover:bg-[#141820] transition-colors"
              >
                Cancel
              </button>
              <button
                onClick={handleKillSwitch}
                disabled={killLoading}
                className="flex-1 py-2 rounded-lg text-xs font-medium bg-red-500/20 border border-red-500/40 text-red-400 hover:bg-red-500/30 transition-colors disabled:opacity-50"
              >
                {killLoading ? 'Activating...' : 'Confirm'}
              </button>
            </div>
          </div>
        ) : (
          <button
            onClick={() => setKillArmed(true)}
            className="w-full flex items-center justify-center gap-2 py-2.5 rounded-lg text-sm font-medium border border-red-500/30 text-red-400 hover:bg-red-500/10 transition-colors"
          >
            <ShieldAlert className="w-4 h-4" />
            Kill Switch
          </button>
        )}

        {/* Logout */}
        <button
          onClick={onLogout}
          className="w-full flex items-center justify-center gap-2 py-2 rounded-lg text-xs font-medium text-gray-500 hover:text-gray-300 hover:bg-[#141820] transition-colors mt-2"
        >
          <LogOut className="w-3.5 h-3.5" />
          Logout
        </button>
      </div>
    </aside>
  );
}
