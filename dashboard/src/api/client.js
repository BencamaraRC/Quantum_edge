const API_BASE = import.meta.env.VITE_API_URL || 'http://localhost:8001';

const TOKEN_KEY = 'qe_token';

export function getToken() {
  return localStorage.getItem(TOKEN_KEY);
}

export function setToken(token) {
  localStorage.setItem(TOKEN_KEY, token);
}

export function clearToken() {
  localStorage.removeItem(TOKEN_KEY);
}

export async function login(username, password) {
  const res = await fetch(`${API_BASE}/auth/login`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/x-www-form-urlencoded' },
    body: new URLSearchParams({ username, password }),
  });
  if (!res.ok) {
    const err = await res.json().catch(() => ({}));
    throw new Error(err.detail || 'Login failed');
  }
  const data = await res.json();
  setToken(data.access_token);
  return data;
}

async function fetchJSON(path) {
  const token = getToken();
  const headers = {};
  if (token) {
    headers['Authorization'] = `Bearer ${token}`;
  }

  const res = await fetch(`${API_BASE}${path}`, { headers });

  if (res.status === 401) {
    clearToken();
    window.location.href = '/login';
    throw new Error('Session expired');
  }

  if (!res.ok) throw new Error(`API ${res.status}: ${path}`);
  return res.json();
}

export function fetchActiveMemos() {
  return fetchJSON('/memos/active');
}

export function fetchRecentMemos(limit = 20) {
  return fetchJSON(`/memos/recent?limit=${limit}`);
}

export function fetchPortfolio() {
  return fetchJSON('/portfolio');
}

export function fetchHealth() {
  return fetchJSON('/health');
}

export function fetchAgentStatus() {
  return fetchJSON('/agents/status');
}

export function fetchAgentFeed(agentId, limit = 50) {
  return fetchJSON(`/agents/${agentId}/feed?limit=${limit}`);
}

export function fetchPortfolioLive() {
  return fetchJSON('/portfolio/live');
}

export function fetchTrades(limit = 50) {
  return fetchJSON(`/trades?limit=${limit}`);
}

export function fetchRegime() {
  return fetchJSON('/regime');
}

export async function activateKillSwitch() {
  const token = getToken();
  const res = await fetch(`${API_BASE}/kill-switch`, {
    method: 'POST',
    headers: token ? { 'Authorization': `Bearer ${token}` } : {},
  });
  if (res.status === 401) {
    clearToken();
    window.location.href = '/login';
    throw new Error('Session expired');
  }
  if (!res.ok) throw new Error(`Kill switch failed: ${res.status}`);
  return res.json();
}
