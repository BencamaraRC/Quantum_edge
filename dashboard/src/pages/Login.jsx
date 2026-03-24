import { useState } from 'react';
import { useNavigate } from 'react-router-dom';
import { Zap } from 'lucide-react';
import { login } from '../api/client';

export default function Login({ onLogin }) {
  const [username, setUsername] = useState('');
  const [password, setPassword] = useState('');
  const [error, setError] = useState('');
  const [loading, setLoading] = useState(false);
  const navigate = useNavigate();

  async function handleSubmit(e) {
    e.preventDefault();
    setError('');
    setLoading(true);
    try {
      await login(username, password);
      onLogin?.();
      navigate('/');
    } catch (err) {
      setError(err.message);
    } finally {
      setLoading(false);
    }
  }

  return (
    <div className="min-h-screen bg-[#080b12] flex items-center justify-center p-4">
      <div className="w-full max-w-sm">
        {/* Logo */}
        <div className="flex items-center justify-center gap-3 mb-8">
          <div className="w-10 h-10 rounded-lg bg-amber-500/15 flex items-center justify-center">
            <Zap className="w-6 h-6 text-amber-500" />
          </div>
          <div>
            <h1 className="text-xl font-bold text-white tracking-tight">Quantum Edge</h1>
            <p className="text-[10px] text-gray-500 uppercase tracking-widest">Trading System</p>
          </div>
        </div>

        {/* Form */}
        <form onSubmit={handleSubmit} className="bg-[#0d1117] border border-[#1e2433] rounded-xl p-6 space-y-4">
          <h2 className="text-lg font-semibold text-white text-center">Sign In</h2>

          {error && (
            <div className="px-3 py-2 rounded-lg bg-red-500/10 border border-red-500/30 text-red-400 text-sm">
              {error}
            </div>
          )}

          <div>
            <label className="block text-xs font-medium text-gray-400 mb-1.5">Username</label>
            <input
              type="text"
              value={username}
              onChange={(e) => setUsername(e.target.value)}
              required
              autoFocus
              className="w-full px-3 py-2.5 rounded-lg bg-[#141820] border border-[#1e2433] text-white text-sm placeholder-gray-600 focus:outline-none focus:border-amber-500/50 transition-colors"
              placeholder="admin"
            />
          </div>

          <div>
            <label className="block text-xs font-medium text-gray-400 mb-1.5">Password</label>
            <input
              type="password"
              value={password}
              onChange={(e) => setPassword(e.target.value)}
              required
              className="w-full px-3 py-2.5 rounded-lg bg-[#141820] border border-[#1e2433] text-white text-sm placeholder-gray-600 focus:outline-none focus:border-amber-500/50 transition-colors"
            />
          </div>

          <button
            type="submit"
            disabled={loading}
            className="w-full py-2.5 rounded-lg text-sm font-medium bg-amber-500 text-black hover:bg-amber-400 disabled:opacity-50 disabled:cursor-not-allowed transition-colors"
          >
            {loading ? 'Signing in...' : 'Sign In'}
          </button>
        </form>
      </div>
    </div>
  );
}
