import { useState, useEffect } from 'react';
import { useParams, useNavigate } from 'react-router-dom';
import { ArrowLeft, Activity, Wifi } from 'lucide-react';
import { fetchAgentFeed, fetchAgentStatus } from '../api/client';

// ─── Helpers ───

/** Flatten nested 'data' JSON string into top-level fields */
function flattenEntry(d) {
  if (!d.data) return d;
  try {
    const nested = typeof d.data === 'string' ? JSON.parse(d.data) : d.data;
    return { ...d, ...nested };
  } catch {
    return d;
  }
}

// ─── Feed entry formatters per agent ───

function NewsEntry({ d }) {
  const score = parseFloat(d.sentiment_score || 0).toFixed(2);
  const label = d.sentiment_label || 'neutral';
  const color = label === 'positive' ? 'text-emerald-400' : label === 'negative' ? 'text-red-400' : 'text-gray-400';
  return (
    <div>
      <div className="flex items-center gap-2 mb-1">
        <span className="text-xs font-semibold text-amber-400">{d.symbol}</span>
        <span className={`text-xs font-medium ${color}`}>{label} ({score})</span>
      </div>
      <p className="text-sm text-gray-300 leading-snug">{d.headline}</p>
      <p className="text-[10px] text-gray-600 mt-1">{d.source}</p>
    </div>
  );
}

function MarketDataEntry({ d }) {
  const price = parseFloat(d.price || 0).toFixed(2);
  const change = parseFloat(d.momentum || d.change_pct || 0);
  const volume = parseInt(d.volume || 0).toLocaleString();
  const spread = parseFloat(d.spread_pct || d.spread || 0).toFixed(3);
  const arrow = change >= 0 ? '▲' : '▼';
  const color = change >= 0 ? 'text-emerald-400' : 'text-red-400';
  return (
    <div className="flex items-center justify-between">
      <div className="flex items-center gap-3">
        <span className="text-sm font-semibold text-amber-400">{d.symbol}</span>
        <span className="text-sm text-white">${price}</span>
        <span className={`text-xs font-medium ${color}`}>{arrow}{Math.abs(change).toFixed(2)}%</span>
      </div>
      <div className="flex items-center gap-4 text-[11px] text-gray-500">
        <span>Vol: {volume}</span>
        <span>Spread: {spread}%</span>
      </div>
    </div>
  );
}

function EventsEntry({ d }) {
  const impact = (d.impact_level || d.impact || 'unknown').toUpperCase();
  const impactColor = impact === 'HIGH' ? 'text-red-400' : impact === 'MEDIUM' ? 'text-amber-400' : 'text-gray-400';
  const hours = parseFloat(d.hours_until || d.days_until || 0).toFixed(1);
  return (
    <div className="flex items-center justify-between">
      <div className="flex items-center gap-2">
        <span className={`text-xs font-bold ${impactColor}`}>{impact}</span>
        <span className="text-sm text-white">{d.event_name || d.event_type}</span>
        {d.symbol && <span className="text-xs text-amber-400">{d.symbol}</span>}
      </div>
      <span className="text-xs text-gray-500">{hours}h away</span>
    </div>
  );
}

function TechnicalsEntry({ d }) {
  const rsi = parseFloat(d.rsi_14 || d.rsi || 0).toFixed(1);
  const macd = parseFloat(d.macd_histogram || d.macd || 0).toFixed(3);
  const adx = parseFloat(d.adx || 0).toFixed(1);
  const bb = parseFloat(d.bb_position || 0).toFixed(2);
  return (
    <div className="flex items-center justify-between">
      <span className="text-sm font-semibold text-amber-400">{d.symbol}</span>
      <div className="flex items-center gap-4 text-[11px]">
        <span className="text-gray-400">RSI: <span className="text-white">{rsi}</span></span>
        <span className="text-gray-400">MACD: <span className="text-white">{macd}</span></span>
        <span className="text-gray-400">ADX: <span className="text-white">{adx}</span></span>
        <span className="text-gray-400">BB: <span className="text-white">{bb}</span></span>
      </div>
    </div>
  );
}

function RiskEntry({ d }) {
  const approved = d.approved === 'true' || d.approved === 'True';
  const kelly = parseFloat(d.kelly_fraction || d.kelly || 0).toFixed(1);
  const size = d.position_size_dollars || d.position_size || '';
  if (approved) {
    return (
      <div className="flex items-center gap-3">
        <span className="text-xs font-bold text-emerald-400">APPROVED</span>
        <span className="text-sm text-amber-400">{d.symbol}</span>
        <span className="text-xs text-gray-400">Kelly: {kelly}%</span>
        {size && <span className="text-xs text-gray-400">${parseFloat(size).toLocaleString()}</span>}
      </div>
    );
  }
  return (
    <div className="flex items-center gap-3">
      <span className="text-xs font-bold text-red-400">VETOED</span>
      <span className="text-sm text-amber-400">{d.symbol}</span>
      <span className="text-xs text-gray-500">{d.veto_reason || d.reason || 'Risk check failed'}</span>
    </div>
  );
}

function DataScienceEntry({ d }) {
  const regime = d.regime || 'unknown';
  const prob = (parseFloat(d.regime_probability || d.probability || 0) * 100).toFixed(0);
  const vol = parseFloat(d.vol_forecast || 0).toFixed(1);
  const anomaly = d.anomaly_detected === 'true' || d.anomaly_detected === 'True';
  const regimeColor = regime.includes('bull') ? 'text-emerald-400' : regime.includes('bear') ? 'text-red-400' : 'text-amber-400';
  return (
    <div className="flex items-center justify-between">
      <div className="flex items-center gap-3">
        <span className={`text-sm font-medium ${regimeColor}`}>{regime.replace('_', ' ')}</span>
        <span className="text-xs text-gray-400">({prob}%)</span>
      </div>
      <div className="flex items-center gap-4 text-[11px] text-gray-500">
        <span>Vol: {vol}%</span>
        {anomaly && <span className="text-red-400 font-medium">ANOMALY</span>}
        {!anomaly && <span>No anomaly</span>}
      </div>
    </div>
  );
}

function SmartMoneyEntry({ d }) {
  const score = parseFloat(d.score || d.composite_score || 0).toFixed(2);
  const direction = (d.direction || 'neutral').toUpperCase();
  const dirColor = direction === 'BULLISH' ? 'text-emerald-400' : direction === 'BEARISH' ? 'text-red-400' : 'text-gray-400';
  const sources = d.sources || '';
  return (
    <div className="flex items-center justify-between">
      <div className="flex items-center gap-3">
        <span className="text-sm font-semibold text-amber-400">{d.symbol}</span>
        <span className="text-xs text-white">{score}</span>
        <span className={`text-xs font-medium ${dirColor}`}>{direction}</span>
      </div>
      <span className="text-[10px] text-gray-600">{sources}</span>
    </div>
  );
}

function GenericEntry({ d }) {
  return (
    <div className="text-xs text-gray-400 font-mono whitespace-pre-wrap">
      {Object.entries(d).filter(([k]) => k !== 'agent_id' && k !== 'timestamp').map(([k, v]) => `${k}: ${v}`).join(' | ')}
    </div>
  );
}

const FORMATTERS = {
  agent_01: NewsEntry,
  agent_02: MarketDataEntry,
  agent_03: EventsEntry,
  agent_04: TechnicalsEntry,
  agent_05: RiskEntry,
  agent_06: DataScienceEntry,
  agent_07: SmartMoneyEntry,
};

function formatTimestamp(data) {
  const ts = data.timestamp || data.processed_at || '';
  if (!ts) return '';
  try {
    const d = new Date(ts);
    return d.toLocaleTimeString('en-US', { hour: '2-digit', minute: '2-digit', second: '2-digit' });
  } catch {
    return ts;
  }
}

export default function AgentDetail() {
  const { agentId } = useParams();
  const navigate = useNavigate();
  const [feed, setFeed] = useState(null);
  const [agentInfo, setAgentInfo] = useState(null);
  const [error, setError] = useState('');

  useEffect(() => {
    let active = true;

    async function load() {
      try {
        const [feedData, statusData] = await Promise.all([
          fetchAgentFeed(agentId, 50),
          fetchAgentStatus(),
        ]);
        if (!active) return;
        setFeed(feedData);
        const info = statusData.find((a) => a.agent_id === agentId);
        setAgentInfo(info || { agent_id: agentId, agent_name: feedData.agent_name, status: 'unknown', last_heartbeat: '?', signal_count: 0 });
        setError('');
      } catch (err) {
        if (active) setError(err.message);
      }
    }

    load();
    const interval = setInterval(load, 10000);
    return () => { active = false; clearInterval(interval); };
  }, [agentId]);

  const Formatter = FORMATTERS[agentId] || GenericEntry;

  return (
    <div>
      {/* Header */}
      <div className="flex items-center gap-4 mb-6">
        <button onClick={() => navigate('/agents')} className="p-2 rounded-lg hover:bg-[#141820] transition-colors">
          <ArrowLeft className="w-5 h-5 text-gray-400" />
        </button>
        <div className="flex items-center gap-3">
          <div className="w-10 h-10 rounded-lg bg-amber-500/10 flex items-center justify-center">
            <Activity className="w-5 h-5 text-amber-500" />
          </div>
          <div>
            <h2 className="text-lg font-bold text-white">{agentInfo?.agent_name || agentId}</h2>
            <p className="text-[10px] text-gray-500 font-mono">{agentId}</p>
          </div>
        </div>
        {agentInfo && (
          <div className="flex items-center gap-4 ml-auto">
            <div className="flex items-center gap-1.5">
              <span className={`w-2.5 h-2.5 rounded-full ${agentInfo.status === 'active' ? 'bg-emerald-500 animate-pulse' : 'bg-gray-600'}`} />
              <span className={`text-xs font-medium ${agentInfo.status === 'active' ? 'text-emerald-400' : 'text-gray-500'}`}>
                {agentInfo.status}
              </span>
            </div>
            <div className="flex items-center gap-1 text-[11px] text-gray-500">
              <Wifi className="w-3 h-3" />
              <span>{agentInfo.last_heartbeat}</span>
            </div>
            <span className="text-xs text-gray-400">{agentInfo.signal_count.toLocaleString()} signals</span>
          </div>
        )}
      </div>

      {error && (
        <div className="px-4 py-3 rounded-lg bg-red-500/10 border border-red-500/30 text-red-400 text-sm mb-4">
          {error}
        </div>
      )}

      {/* Feed */}
      <div className="bg-[#0d1117] border border-[#1e2433] rounded-xl">
        <div className="px-5 py-3 border-b border-[#1e2433]">
          <h3 className="text-sm font-semibold text-white">Activity Feed</h3>
          <p className="text-[10px] text-gray-500 mt-0.5">
            {feed?.stream || ''} — refreshes every 10s
          </p>
        </div>

        <div className="max-h-[calc(100vh-240px)] overflow-y-auto divide-y divide-[#1e2433]">
          {feed?.entries?.length === 0 && (
            <div className="px-5 py-8 text-center text-sm text-gray-600">No activity yet</div>
          )}
          {feed?.entries?.map((entry) => {
            const flat = flattenEntry(entry.data);
            return (
              <div key={entry.id} className="px-5 py-3 hover:bg-[#141820] transition-colors">
                <div className="flex items-start justify-between gap-4">
                  <div className="flex-1 min-w-0">
                    <Formatter d={flat} />
                  </div>
                  <span className="text-[10px] text-gray-600 whitespace-nowrap flex-shrink-0">
                    {formatTimestamp(flat)}
                  </span>
                </div>
              </div>
            );
          })}
        </div>
      </div>
    </div>
  );
}
