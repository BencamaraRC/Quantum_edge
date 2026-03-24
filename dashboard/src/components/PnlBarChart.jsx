import { BarChart, Bar, XAxis, YAxis, Tooltip, ResponsiveContainer, Cell } from 'recharts';

const CustomTooltip = ({ active, payload, label }) => {
  if (!active || !payload?.length) return null;
  const val = payload[0].value;
  return (
    <div className="bg-[#1a1f2e] border border-[#1e2433] rounded-lg px-3 py-2 text-xs">
      <p className="text-gray-400 mb-1">{label}</p>
      <p className={`font-semibold ${val >= 0 ? 'text-emerald-400' : 'text-red-400'}`}>
        {val >= 0 ? '+' : ''}${val.toFixed(2)}
      </p>
    </div>
  );
};

export default function PnlBarChart({ data = [] }) {
  if (data.length === 0) {
    return (
      <div className="bg-[#141820] border border-[#1e2433] rounded-xl p-5">
        <h3 className="text-sm font-semibold text-white mb-4">Daily P&L</h3>
        <div className="flex items-center justify-center h-[200px] text-gray-600 text-sm">
          P&L history will appear as trades complete
        </div>
      </div>
    );
  }

  return (
    <div className="bg-[#141820] border border-[#1e2433] rounded-xl p-5">
      <h3 className="text-sm font-semibold text-white mb-4">Daily P&L</h3>
      <ResponsiveContainer width="100%" height={200}>
        <BarChart data={data} margin={{ top: 5, right: 5, left: 5, bottom: 0 }}>
          <XAxis
            dataKey="date"
            axisLine={false}
            tickLine={false}
            tick={{ fill: '#6b7280', fontSize: 9 }}
            interval={6}
          />
          <YAxis
            axisLine={false}
            tickLine={false}
            tick={{ fill: '#6b7280', fontSize: 10 }}
            tickFormatter={(v) => `$${v}`}
          />
          <Tooltip content={<CustomTooltip />} />
          <Bar dataKey="pnl" radius={[2, 2, 0, 0]}>
            {data.map((entry, i) => (
              <Cell key={i} fill={entry.pnl >= 0 ? '#10b981' : '#ef4444'} />
            ))}
          </Bar>
        </BarChart>
      </ResponsiveContainer>
    </div>
  );
}
