import { useState, useEffect } from 'react';
import { useNavigate } from 'react-router-dom';
import AgentCard from '../components/AgentCard';
import { fetchAgentStatus } from '../api/client';

export default function Agents() {
  const [agents, setAgents] = useState([]);
  const navigate = useNavigate();

  useEffect(() => {
    let active = true;

    async function load() {
      try {
        const data = await fetchAgentStatus();
        if (active) setAgents(data);
      } catch {
        // keep stale data on error
      }
    }

    load();
    const interval = setInterval(load, 15000);
    return () => { active = false; clearInterval(interval); };
  }, []);

  return (
    <div>
      <h2 className="text-lg font-bold text-white mb-4">Agent Fleet</h2>
      <div className="grid grid-cols-3 gap-4">
        {agents.map((agent) => (
          <AgentCard
            key={agent.agent_id}
            agent={{
              id: agent.agent_id,
              name: agent.agent_name,
              status: agent.status,
              signals: agent.signal_count,
              lastHeartbeat: agent.last_heartbeat,
            }}
            onClick={() => navigate(`/agents/${agent.agent_id}`)}
          />
        ))}
      </div>
    </div>
  );
}
