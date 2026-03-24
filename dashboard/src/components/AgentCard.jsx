import { Activity, Wifi } from 'lucide-react';

export default function AgentCard({ agent, onClick }) {
  const isActive = agent.status === 'active';

  return (
    <div onClick={onClick} className="bg-[#141820] border border-[#1e2433] rounded-xl p-5 hover:bg-[#1a1f2e] transition-colors cursor-pointer">
      <div className="flex items-center justify-between mb-3">
        <div className="flex items-center gap-2">
          <div className={`w-8 h-8 rounded-lg flex items-center justify-center ${
            isActive ? 'bg-amber-500/10' : 'bg-gray-500/10'
          }`}>
            <Activity className={`w-4 h-4 ${isActive ? 'text-amber-500' : 'text-gray-500'}`} />
          </div>
          <div>
            <h4 className="text-sm font-semibold text-white">{agent.name}</h4>
            <p className="text-[10px] text-gray-500 font-mono">{agent.id}</p>
          </div>
        </div>
        <span className={`w-2.5 h-2.5 rounded-full ${
          isActive ? 'bg-emerald-500 animate-pulse' : 'bg-gray-600'
        }`} />
      </div>
      <p className="text-xs text-gray-400 mb-3">{agent.detail}</p>
      <div className="flex items-center justify-between text-[11px]">
        <div className="flex items-center gap-1 text-gray-500">
          <Wifi className="w-3 h-3" />
          <span>{agent.lastHeartbeat}</span>
        </div>
        <span className="text-gray-400 font-medium">{agent.signals} signals</span>
      </div>
    </div>
  );
}
