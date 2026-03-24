import PositionsTable from '../components/PositionsTable';
import usePortfolioData from '../hooks/usePortfolioData';

export default function Positions() {
  const { positions, loading } = usePortfolioData();

  return (
    <div>
      <h2 className="text-lg font-bold text-white mb-4">Positions</h2>
      <PositionsTable positions={positions} loading={loading} />
    </div>
  );
}
