import { phases } from '../data/mockData';
import usePipelineData from '../hooks/usePipelineData';
import { GitBranch, CheckCircle2, XCircle, Ban, Loader2 } from 'lucide-react';

function PhaseBar({ phaseIndex }) {
  return (
    <div className="flex gap-0.5 mt-2">
      {phases.map((phase, i) => (
        <div
          key={phase}
          className={`h-1.5 flex-1 rounded-full transition-colors ${
            i < phaseIndex ? 'bg-amber-500' : i === phaseIndex ? 'bg-amber-500 animate-pulse' : 'bg-[#1e2433]'
          }`}
          title={phase}
        />
      ))}
    </div>
  );
}

const resultIcons = {
  completed: <CheckCircle2 className="w-4 h-4 text-emerald-400" />,
  rejected: <XCircle className="w-4 h-4 text-red-400" />,
  cancelled: <Ban className="w-4 h-4 text-gray-500" />,
};

const resultColors = {
  completed: 'text-emerald-400',
  rejected: 'text-red-400',
  cancelled: 'text-gray-500',
};

export default function PipelineView() {
  const { activeMemos, recentMemos, loading, error } = usePipelineData();

  if (loading) {
    return (
      <div className="flex items-center justify-center py-12 text-gray-400">
        <Loader2 className="w-5 h-5 animate-spin mr-2" />
        Loading pipeline data...
      </div>
    );
  }

  if (error) {
    return (
      <div className="bg-red-900/20 border border-red-800 rounded-xl p-5 text-sm text-red-400">
        Failed to load pipeline: {error}
        <p className="text-xs text-gray-500 mt-1">Make sure the API is running on localhost:8000</p>
      </div>
    );
  }

  return (
    <div className="space-y-6">
      {/* Active Memos */}
      <div className="bg-[#141820] border border-[#1e2433] rounded-xl p-5">
        <div className="flex items-center gap-2 mb-4">
          <GitBranch className="w-4 h-4 text-amber-500" />
          <h3 className="text-sm font-semibold text-white">Active Pipeline</h3>
          <span className="ml-auto text-xs text-gray-500">{activeMemos.length} active</span>
        </div>
        {activeMemos.length === 0 ? (
          <p className="text-sm text-gray-500">No active memos in pipeline</p>
        ) : (
          <div className="space-y-4">
            {activeMemos.map((m) => (
              <div key={m.id} className="bg-[#0d1117] rounded-lg p-4 border border-[#1e2433]">
                <div className="flex items-center justify-between">
                  <div className="flex items-center gap-3">
                    <span className="text-base font-bold text-white">{m.symbol}</span>
                    <span className="text-[10px] text-gray-500 font-mono">{m.id}</span>
                  </div>
                  <div className="flex items-center gap-3">
                    <span className="text-xs text-gray-400">{m.startedAt}</span>
                    <span className="text-xs font-medium text-amber-500">
                      Score: {m.score.toFixed(2)}
                    </span>
                  </div>
                </div>
                <p className="text-xs text-gray-400 mt-2">
                  Phase {m.phaseIndex + 1}/{phases.length}: <span className="text-gray-300">{phases[m.phaseIndex]}</span>
                </p>
                <PhaseBar phaseIndex={m.phaseIndex} />
              </div>
            ))}
          </div>
        )}
      </div>

      {/* Completed Memos */}
      <div className="bg-[#141820] border border-[#1e2433] rounded-xl p-5">
        <h3 className="text-sm font-semibold text-white mb-4">Recent Memos</h3>
        {recentMemos.length === 0 ? (
          <p className="text-sm text-gray-500">No recent memos</p>
        ) : (
          <div className="space-y-2">
            {recentMemos.map((m) => (
              <div key={m.id} className="flex items-center justify-between py-2 border-b border-[#1e2433] last:border-0">
                <div className="flex items-center gap-3">
                  {resultIcons[m.result]}
                  <span className="text-sm font-semibold text-white">{m.symbol}</span>
                  <span className="text-[10px] text-gray-500 font-mono">{m.id}</span>
                </div>
                <div className="flex items-center gap-4">
                  <span className={`text-xs font-medium capitalize ${resultColors[m.result]}`}>
                    {m.result}
                  </span>
                  <span className="text-xs text-gray-500">Score: {m.finalScore.toFixed(2)}</span>
                  <span className="text-xs text-gray-500">{m.duration}</span>
                </div>
              </div>
            ))}
          </div>
        )}
      </div>
    </div>
  );
}
