import CryptoVertical from "../components/CryptoVertical";

export default function CryptoPage() {
  return (
    <div className="page crypto-page">
      <header className="page-header">
        <h1>Crypto Events</h1>
        <p className="description">
          Prediction market for Bitcoin price targets, Ethereum ETF approvals, and Solana milestones.
          Powered by XGBoost + CoinGecko + on-chain metrics.
        </p>
      </header>

      <main className="page-content">
        <CryptoVertical />
      </main>

      <style>{`
        .crypto-page {
          min-height: 100vh;
          background: linear-gradient(135deg, #f5f5f5 0%, #ffffff 100%);
        }

        .page-header {
          background: linear-gradient(135deg, #1a1a2e 0%, #16213e 100%);
          color: white;
          padding: 40px 20px;
          text-align: center;
          border-bottom: 3px solid #00d4ff;
        }

        .page-header h1 {
          margin: 0 0 16px 0;
          font-size: 36px;
          font-weight: 800;
        }

        .page-header .description {
          margin: 0;
          font-size: 16px;
          color: #b0b0b0;
          max-width: 600px;
          margin-left: auto;
          margin-right: auto;
          line-height: 1.6;
        }

        .page-content {
          max-width: 1400px;
          margin: 0 auto;
          padding: 40px 20px;
        }

        @media (max-width: 768px) {
          .page-header h1 {
            font-size: 28px;
          }

          .page-header .description {
            font-size: 14px;
          }

          .page-content {
            padding: 20px 10px;
          }
        }
      `}</style>
    </div>
  );
}
