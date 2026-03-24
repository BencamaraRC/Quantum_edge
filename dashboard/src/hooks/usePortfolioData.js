import { useState, useEffect, useCallback } from 'react';
import { fetchPortfolioLive } from '../api/client';

export default function usePortfolioData(pollInterval = 5000) {
  const [portfolio, setPortfolio] = useState(null);
  const [positions, setPositions] = useState([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState(null);

  const fetchData = useCallback(async () => {
    try {
      const data = await fetchPortfolioLive();
      setPortfolio(data);
      setPositions(data.positions || []);
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

  return { portfolio, positions, loading, error };
}
