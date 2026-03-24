export default function PositionsTable({ positions = [], loading = false }) {
  if (loading) {
    return (
      <div className="bg-[#141820] border border-[#1e2433] rounded-xl p-8 text-center text-gray-500">
        Loading positions...
      </div>
    );
  }

  if (positions.length === 0) {
    return (
      <div className="bg-[#141820] border border-[#1e2433] rounded-xl p-8 text-center">
        <p className="text-gray-500 text-sm">No open positions</p>
        <p className="text-gray-600 text-xs mt-1">Positions will appear here when trades are executed during market hours</p>
      </div>
    );
  }

  return (
    <div className="bg-[#141820] border border-[#1e2433] rounded-xl overflow-hidden">
      <div className="px-5 py-4 border-b border-[#1e2433]">
        <h3 className="text-sm font-semibold text-white">Open Positions</h3>
      </div>
      <div className="overflow-x-auto">
        <table className="w-full text-sm">
          <thead>
            <tr className="text-[11px] text-gray-500 uppercase tracking-wider">
              <th className="text-left px-5 py-3 font-medium">Symbol</th>
              <th className="text-left px-3 py-3 font-medium">Side</th>
              <th className="text-right px-3 py-3 font-medium">Qty</th>
              <th className="text-right px-3 py-3 font-medium">Entry</th>
              <th className="text-right px-3 py-3 font-medium">Current</th>
              <th className="text-right px-3 py-3 font-medium">P&L</th>
              <th className="text-right px-5 py-3 font-medium">P&L %</th>
            </tr>
          </thead>
          <tbody>
            {positions.map((p) => {
              const side = (p.side || 'long').toUpperCase();
              const pnl = p.unrealized_pl || 0;
              const pnlPct = (p.unrealized_pl_pct || 0) * 100;
              return (
                <tr key={p.symbol} className="border-t border-[#1e2433] hover:bg-[#1a1f2e] transition-colors">
                  <td className="px-5 py-3">
                    <span className="font-semibold text-white">{p.symbol}</span>
                    <span className="ml-2 text-[10px] text-gray-500">{p.asset_class || ''}</span>
                  </td>
                  <td className="px-3 py-3">
                    <span className={`text-[11px] font-semibold px-2 py-0.5 rounded ${
                      side === 'LONG' ? 'bg-emerald-500/15 text-emerald-400' : 'bg-red-500/15 text-red-400'
                    }`}>
                      {side}
                    </span>
                  </td>
                  <td className="px-3 py-3 text-right text-gray-300">{p.qty}</td>
                  <td className="px-3 py-3 text-right text-gray-400">${(p.avg_entry_price || 0).toFixed(2)}</td>
                  <td className="px-3 py-3 text-right text-white font-medium">${(p.current_price || 0).toFixed(2)}</td>
                  <td className={`px-3 py-3 text-right font-medium ${pnl >= 0 ? 'text-emerald-400' : 'text-red-400'}`}>
                    {pnl >= 0 ? '+' : ''}${pnl.toFixed(2)}
                  </td>
                  <td className={`px-5 py-3 text-right font-medium ${pnlPct >= 0 ? 'text-emerald-400' : 'text-red-400'}`}>
                    {pnlPct >= 0 ? '+' : ''}{pnlPct.toFixed(2)}%
                  </td>
                </tr>
              );
            })}
          </tbody>
        </table>
      </div>
    </div>
  );
}
