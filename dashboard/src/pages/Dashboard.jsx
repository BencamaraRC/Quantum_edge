import { useState, useEffect } from 'react';
import { DollarSign, TrendingUp, Briefcase, Wallet } from 'lucide-react';
import StatCard from '../components/StatCard';
import EquityChart from '../components/EquityChart';
import AllocationChart from '../components/AllocationChart';
import PnlBarChart from '../components/PnlBarChart';
import usePortfolioData from '../hooks/usePortfolioData';
import usePipelineData from '../hooks/usePipelineData';
import { fetchRegime } from '../api/client';

export default function Dashboard() {
  const { portfolio, positions, loading } = usePortfolioData();
  const { activeMemos } = usePipelineData();
  const [regime, setRegime] = useState('unknown');

  useEffect(() => {
    fetchRegime()
      .then((data) => setRegime(data.regime || 'unknown'))
      .catch(() => {});
    const id = setInterval(() => {
      fetchRegime()
        .then((data) => setRegime(data.regime || 'unknown'))
        .catch(() => {});
    }, 30000);
    return () => clearInterval(id);
  }, []);

  const equity = portfolio?.equity ?? 0;
  const dailyPnl = portfolio?.daily_pnl ?? 0;
  const dailyPnlPct = portfolio?.daily_pnl_pct ?? 0;
  const buyingPower = portfolio?.buying_power ?? 0;
  const totalExposurePct = portfolio?.total_exposure_pct ?? 0;
  const circuitBreakerActive = portfolio?.circuit_breaker_active ?? false;
  const cash = portfolio?.cash ?? 0;

  if (loading && !portfolio) {
    return (
      <div className="flex items-center justify-center h-64">
        <div className="text-gray-500">Loading portfolio...</div>
      </div>
    );
  }

  return (
    <div className="space-y-6">
      {/* Stat Cards */}
      <div className="grid grid-cols-4 gap-4">
        <StatCard
          label="Equity"
          value={`$${equity.toLocaleString('en-US', { minimumFractionDigits: 2 })}`}
          icon={DollarSign}
        />
        <StatCard
          label="Daily P&L"
          value={`${dailyPnl >= 0 ? '+' : ''}$${dailyPnl.toLocaleString('en-US', { minimumFractionDigits: 2 })}`}
          subValue={`${dailyPnlPct >= 0 ? '+' : ''}${dailyPnlPct.toFixed(2)}%`}
          trend={dailyPnl >= 0 ? 'up' : 'down'}
          icon={TrendingUp}
        />
        <StatCard
          label="Open Positions"
          value={positions.length}
          subValue={`${totalExposurePct.toFixed(1)}% exposure`}
          icon={Briefcase}
        />
        <StatCard
          label="Buying Power"
          value={`$${buyingPower.toLocaleString('en-US', { minimumFractionDigits: 2 })}`}
          icon={Wallet}
        />
      </div>

      {/* Equity Chart */}
      <EquityChart />

      {/* Bottom Row */}
      <div className="grid grid-cols-3 gap-4">
        <AllocationChart positions={positions} cash={cash} />
        <PnlBarChart />
        <div className="bg-[#141820] border border-[#1e2433] rounded-xl p-5">
          <h3 className="text-sm font-semibold text-white mb-4">Pipeline Status</h3>
          <div className="space-y-4">
            <div>
              <p className="text-xs text-gray-500 mb-1">Active Memos</p>
              <p className="text-2xl font-bold text-amber-500">{activeMemos.length}</p>
            </div>
            <div>
              <p className="text-xs text-gray-500 mb-1">Regime</p>
              <span className={`text-xs font-medium px-2.5 py-1 rounded ${
                regime.includes('bull') ? 'bg-emerald-500/15 text-emerald-400'
                  : regime.includes('bear') ? 'bg-red-500/15 text-red-400'
                  : 'bg-amber-500/15 text-amber-400'
              }`}>
                {regime.replace(/_/g, ' ').replace(/\b\w/g, (c) => c.toUpperCase())}
              </span>
            </div>
            <div>
              <p className="text-xs text-gray-500 mb-1">Circuit Breaker</p>
              <span className={`text-xs font-medium px-2.5 py-1 rounded ${
                circuitBreakerActive
                  ? 'bg-red-500/15 text-red-400'
                  : 'bg-emerald-500/15 text-emerald-400'
              }`}>
                {circuitBreakerActive ? 'ACTIVE' : 'Normal'}
              </span>
            </div>
          </div>
        </div>
      </div>
    </div>
  );
}
