import { PieChart, Pie, Cell, Tooltip, ResponsiveContainer } from 'recharts';

const COLORS = ['#f59e0b', '#3b82f6', '#ef4444', '#10b981', '#8b5cf6', '#ec4899', '#06b6d4', '#f97316'];

const CustomTooltip = ({ active, payload }) => {
  if (!active || !payload?.length) return null;
  const d = payload[0];
  return (
    <div className="bg-[#1a1f2e] border border-[#1e2433] rounded-lg px-3 py-2 text-xs">
      <p className="text-white font-semibold">{d.name}</p>
      <p className="text-gray-400">${d.value.toLocaleString()}</p>
    </div>
  );
};

export default function AllocationChart({ positions = [], cash = 0 }) {
  const allocation = [
    ...positions.map((p, i) => ({
      name: p.symbol,
      value: Math.abs(p.market_value || 0),
      color: COLORS[i % COLORS.length],
    })),
    { name: 'Cash', value: cash, color: '#374151' },
  ].filter((a) => a.value > 0);

  if (allocation.length <= 1) {
    return (
      <div className="bg-[#141820] border border-[#1e2433] rounded-xl p-5">
        <h3 className="text-sm font-semibold text-white mb-4">Allocation</h3>
        <div className="flex items-center justify-center h-[200px] text-gray-600 text-sm">
          {cash > 0 ? '100% Cash' : 'No data'}
        </div>
      </div>
    );
  }

  const total = allocation.reduce((s, a) => s + a.value, 0);

  return (
    <div className="bg-[#141820] border border-[#1e2433] rounded-xl p-5">
      <h3 className="text-sm font-semibold text-white mb-4">Allocation</h3>
      <ResponsiveContainer width="100%" height={200}>
        <PieChart>
          <Pie
            data={allocation}
            cx="50%"
            cy="50%"
            innerRadius={55}
            outerRadius={80}
            paddingAngle={2}
            dataKey="value"
          >
            {allocation.map((entry, i) => (
              <Cell key={i} fill={entry.color} stroke="none" />
            ))}
          </Pie>
          <Tooltip content={<CustomTooltip />} />
        </PieChart>
      </ResponsiveContainer>
      <div className="grid grid-cols-3 gap-2 mt-3">
        {allocation.map((a) => (
          <div key={a.name} className="flex items-center gap-1.5">
            <span className="w-2 h-2 rounded-full" style={{ backgroundColor: a.color }} />
            <span className="text-[11px] text-gray-400">{a.name}</span>
            <span className="text-[11px] text-gray-500 ml-auto">
              {((a.value / total) * 100).toFixed(0)}%
            </span>
          </div>
        ))}
      </div>
    </div>
  );
}
