import { useState, useEffect, useCallback } from 'react';
import { fetchActiveMemos, fetchRecentMemos } from '../api/client';

const PHASE_ORDER = [
  'signal_collection_pass1',
  'pass1_scoring',
  'smart_money_validation',
  'signal_collection_pass2',
  'pass2_scoring',
  'technical_evaluation',
  'risk_check',
  'execution',
  'completed',
];

const TERMINAL_PHASES = new Set(['completed', 'cancelled', 'rejected', 'timed_out']);

function timeAgo(isoString) {
  const diff = Date.now() - new Date(isoString).getTime();
  const mins = Math.floor(diff / 60000);
  if (mins < 1) return 'just now';
  if (mins < 60) return `${mins} min ago`;
  const hrs = Math.floor(mins / 60);
  if (hrs < 24) return `${hrs}h ago`;
  return `${Math.floor(hrs / 24)}d ago`;
}

function formatDuration(created, completed) {
  if (!completed) return '--';
  const diff = new Date(completed).getTime() - new Date(created).getTime();
  const mins = Math.floor(diff / 60000);
  const secs = Math.floor((diff % 60000) / 1000);
  return `${mins}m ${String(secs).padStart(2, '0')}s`;
}

function transformActiveMemo(memo) {
  const score = memo.pass2_score?.composite_score
    ?? memo.pass1_score?.composite_score
    ?? 0;

  return {
    id: memo.memo_id.slice(0, 8),
    symbol: memo.symbol,
    phase: memo.phase,
    phaseIndex: Math.max(0, PHASE_ORDER.indexOf(memo.phase)),
    startedAt: timeAgo(memo.created_at),
    score,
  };
}

function transformTerminalMemo(memo) {
  const resultMap = {
    completed: 'completed',
    rejected: 'rejected',
    cancelled: 'cancelled',
    timed_out: 'cancelled',
  };

  return {
    id: memo.memo_id.slice(0, 8),
    symbol: memo.symbol,
    result: resultMap[memo.phase] || 'cancelled',
    finalScore: memo.pass2_score?.composite_score
      ?? memo.pass1_score?.composite_score
      ?? 0,
    duration: formatDuration(memo.created_at, memo.completed_at),
  };
}

export default function usePipelineData(pollInterval = 5000) {
  const [activeMemos, setActiveMemos] = useState([]);
  const [recentMemos, setRecentMemos] = useState([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState(null);

  const fetchData = useCallback(async () => {
    try {
      const [activeRaw, recentRaw] = await Promise.all([
        fetchActiveMemos(),
        fetchRecentMemos(20),
      ]);

      setActiveMemos(activeRaw.map(transformActiveMemo));

      const terminal = recentRaw
        .filter((m) => TERMINAL_PHASES.has(m.phase))
        .map(transformTerminalMemo);
      setRecentMemos(terminal);

      setError(null);
    } catch (err) {
      setError(err.message);
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    fetchData();
    const id = setInterval(fetchData, pollInterval);
    return () => clearInterval(id);
  }, [fetchData, pollInterval]);

  return { activeMemos, recentMemos, loading, error };
}
