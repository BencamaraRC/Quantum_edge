export default function StatCard({ label, value, subValue, icon: Icon, trend }) {
  return (
    <div className="bg-[#141820] border border-[#1e2433] rounded-xl p-5 flex flex-col gap-1">
      <div className="flex items-center justify-between mb-1">
        <span className="text-xs font-medium text-gray-500 uppercase tracking-wider">{label}</span>
        {Icon && (
          <div className="w-8 h-8 rounded-lg bg-amber-500/10 flex items-center justify-center">
            <Icon className="w-4 h-4 text-amber-500" />
          </div>
        )}
      </div>
      <p className="text-2xl font-bold text-white">{value}</p>
      {subValue && (
        <p className={`text-xs font-medium ${
          trend === 'up' ? 'text-emerald-400' : trend === 'down' ? 'text-red-400' : 'text-gray-500'
        }`}>
          {subValue}
        </p>
      )}
    </div>
  );
}
