import { useState, useEffect, useCallback } from 'react';
import { fetchTrades } from '../api/client';

export default function TradeHistory() {
  const [trades, setTrades] = useState([]);
  const [loading, setLoading] = useState(true);

  const loadTrades = useCallback(async () => {
    try {
      const data = await fetchTrades(50);
      setTrades(data);
    } catch {
      // Keep previous data on error
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    loadTrades();
    const id = setInterval(loadTrades, 15000);
    return () => clearInterval(id);
  }, [loadTrades]);

  if (loading) {
    return (
      <div className="bg-[#141820] border border-[#1e2433] rounded-xl p-8 text-center text-gray-500">
        Loading trades...
      </div>
    );
  }

  if (trades.length === 0) {
    return (
      <div className="bg-[#141820] border border-[#1e2433] rounded-xl p-8 text-center">
        <p className="text-gray-500 text-sm">No trades yet</p>
        <p className="text-gray-600 text-xs mt-1">Completed trades will appear here as memos reach execution</p>
      </div>
    );
  }

  return (
    <div className="space-y-6">
      {/* Summary Stats */}
      <div className="grid grid-cols-3 gap-4">
        {[
          { label: 'Total Trades', value: trades.length },
          { label: 'Avg R:R', value: trades[0]?.rr || '--' },
          { label: 'Status', value: trades.length > 0 ? 'Active' : '--' },
        ].map((s) => (
          <div key={s.label} className="bg-[#141820] border border-[#1e2433] rounded-xl px-4 py-3">
            <p className="text-[11px] text-gray-500 uppercase tracking-wider mb-1">{s.label}</p>
            <p className="text-xl font-bold text-white">{s.value}</p>
          </div>
        ))}
      </div>

      {/* Trade Table */}
      <div className="bg-[#141820] border border-[#1e2433] rounded-xl overflow-hidden">
        <div className="px-5 py-4 border-b border-[#1e2433]">
          <h3 className="text-sm font-semibold text-white">Trade Log</h3>
        </div>
        <div className="overflow-x-auto">
          <table className="w-full text-sm">
            <thead>
              <tr className="text-[11px] text-gray-500 uppercase tracking-wider">
                <th className="text-left px-5 py-3 font-medium">Time</th>
                <th className="text-left px-3 py-3 font-medium">Symbol</th>
                <th className="text-left px-3 py-3 font-medium">Side</th>
                <th className="text-right px-3 py-3 font-medium">Qty</th>
                <th className="text-right px-3 py-3 font-medium">Entry</th>
                <th className="text-right px-3 py-3 font-medium">R:R</th>
                <th className="text-right px-5 py-3 font-medium">Status</th>
              </tr>
            </thead>
            <tbody>
              {trades.map((t, i) => {
                const side = (t.side || 'long').toUpperCase();
                const time = t.time ? new Date(t.time).toLocaleString('en-US', { month: 'short', day: 'numeric', hour: '2-digit', minute: '2-digit' }) : '--';
                return (
                  <tr key={i} className="border-t border-[#1e2433] hover:bg-[#1a1f2e] transition-colors">
                    <td className="px-5 py-3 text-gray-400">{time}</td>
                    <td className="px-3 py-3 font-semibold text-white">{t.symbol}</td>
                    <td className="px-3 py-3">
                      <span className={`text-[11px] font-semibold px-2 py-0.5 rounded ${
                        side === 'LONG' ? 'bg-emerald-500/15 text-emerald-400' : 'bg-red-500/15 text-red-400'
                      }`}>
                        {side}
                      </span>
                    </td>
                    <td className="px-3 py-3 text-right text-gray-300">{t.qty}</td>
                    <td className="px-3 py-3 text-right text-gray-400">${(t.entry || 0).toFixed(2)}</td>
                    <td className="px-3 py-3 text-right text-gray-400">{t.rr}</td>
                    <td className="px-5 py-3 text-right">
                      <span className="text-[11px] font-semibold px-2 py-0.5 rounded bg-emerald-500/15 text-emerald-400">
                        {t.status}
                      </span>
                    </td>
                  </tr>
                );
              })}
            </tbody>
          </table>
        </div>
      </div>
    </div>
  );
}
