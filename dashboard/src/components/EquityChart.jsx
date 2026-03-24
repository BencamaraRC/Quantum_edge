import { AreaChart, Area, XAxis, YAxis, Tooltip, ResponsiveContainer } from 'recharts';

const CustomTooltip = ({ active, payload, label }) => {
  if (!active || !payload?.length) return null;
  return (
    <div className="bg-[#1a1f2e] border border-[#1e2433] rounded-lg px-3 py-2 text-xs">
      <p className="text-gray-400 mb-1">{label}</p>
      <p className="text-white font-semibold">${payload[0].value.toLocaleString('en-US', { minimumFractionDigits: 2 })}</p>
    </div>
  );
};

export default function EquityChart({ data = [] }) {
  if (data.length === 0) {
    return (
      <div className="bg-[#141820] border border-[#1e2433] rounded-xl p-5">
        <div className="flex items-center justify-between mb-4">
          <div>
            <h3 className="text-sm font-semibold text-white">Equity Curve</h3>
            <p className="text-xs text-gray-500 mt-0.5">Performance over time</p>
          </div>
        </div>
        <div className="flex items-center justify-center h-[260px] text-gray-600 text-sm">
          Equity history will appear as trades execute
        </div>
      </div>
    );
  }

  return (
    <div className="bg-[#141820] border border-[#1e2433] rounded-xl p-5">
      <div className="flex items-center justify-between mb-4">
        <div>
          <h3 className="text-sm font-semibold text-white">Equity Curve</h3>
          <p className="text-xs text-gray-500 mt-0.5">Performance over time</p>
        </div>
      </div>
      <ResponsiveContainer width="100%" height={260}>
        <AreaChart data={data} margin={{ top: 5, right: 5, left: 5, bottom: 0 }}>
          <defs>
            <linearGradient id="equityGrad" x1="0" y1="0" x2="0" y2="1">
              <stop offset="0%" stopColor="#f59e0b" stopOpacity={0.3} />
              <stop offset="100%" stopColor="#f59e0b" stopOpacity={0} />
            </linearGradient>
          </defs>
          <XAxis
            dataKey="date"
            axisLine={false}
            tickLine={false}
            tick={{ fill: '#6b7280', fontSize: 10 }}
            interval={Math.max(0, Math.floor(data.length / 6))}
          />
          <YAxis
            axisLine={false}
            tickLine={false}
            tick={{ fill: '#6b7280', fontSize: 10 }}
            domain={['dataMin - 2000', 'dataMax + 2000']}
            tickFormatter={(v) => `$${(v / 1000).toFixed(0)}k`}
          />
          <Tooltip content={<CustomTooltip />} />
          <Area
            type="monotone"
            dataKey="equity"
            stroke="#f59e0b"
            strokeWidth={2}
            fill="url(#equityGrad)"
          />
        </AreaChart>
      </ResponsiveContainer>
    </div>
  );
}
