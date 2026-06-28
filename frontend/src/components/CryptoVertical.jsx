import { useState, useEffect } from "react";

const pct = (x) => (x == null ? "—" : `${(x * 100).toFixed(1)}%`);
const fmt = (x) => (x == null ? "—" : typeof x === "number" ? x.toFixed(2) : x);

export default function CryptoVertical() {
  const [predictions, setPredictions] = useState([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState(null);
  const [selectedEvent, setSelectedEvent] = useState(null);
  const [detailLoading, setDetailLoading] = useState(false);
  const [detail, setDetail] = useState(null);

  const BASE = import.meta.env.VITE_API_BASE || "http://localhost:8000";

  useEffect(() => {
    const fetchPredictions = async () => {
      try {
        setLoading(true);
        const res = await fetch(`${BASE}/verticals/crypto`);
        if (!res.ok) throw new Error(`Request failed: ${res.status}`);
        const data = await res.json();
        setPredictions(data.predictions || []);
        setError(null);
      } catch (err) {
        setError(err.message);
        setPredictions([]);
      } finally {
        setLoading(false);
      }
    };

    fetchPredictions();
  }, [BASE]);

  const fetchEventDetail = async (eventId) => {
    try {
      setDetailLoading(true);
      const res = await fetch(
        `${BASE}/verticals/crypto/event/${encodeURIComponent(eventId)}`
      );
      if (!res.ok) throw new Error(`Request failed: ${res.status}`);
      const data = await res.json();
      setDetail(data);
      setSelectedEvent(eventId);
    } catch (err) {
      setError(err.message);
      setDetail(null);
    } finally {
      setDetailLoading(false);
    }
  };

  if (loading) {
    return <div className="loading">Loading crypto predictions...</div>;
  }

  if (error) {
    return (
      <div className="error">
        <p>Error loading predictions: {error}</p>
      </div>
    );
  }

  if (predictions.length === 0) {
    return (
      <div className="empty">
        <p>No crypto predictions available at this time.</p>
      </div>
    );
  }

  // Split into main events and show detail for selected
  const mainPredictions = predictions;

  return (
    <div className="crypto-vertical">
      <div className="crypto-header">
        <h2>Crypto Events</h2>
        <p className="subtitle">
          Bitcoin price targets, ETF approvals, Solana milestones — powered by
          XGBoost + CoinGecko + on-chain metrics
        </p>
      </div>

      <div className="crypto-cards">
        {mainPredictions.map((pred, idx) => {
          const actionDecision = pred.edge && pred.edge > 0.03 ? "BUY" : "PASS";
          const confColor =
            pred.confidence > 0.8
              ? "#4CAF50"
              : pred.confidence > 0.6
              ? "#FFC107"
              : "#ff6b6b";

          return (
            <div
              key={idx}
              className="crypto-card"
              style={{
                border: `2px solid ${
                  actionDecision === "BUY" ? "#4CAF50" : "#ccc"
                }`,
              }}
            >
              <div className="card-header">
                <h3>{pred.event}</h3>
                <span
                  className="action-badge"
                  style={{
                    backgroundColor: actionDecision === "BUY" ? "#4CAF50" : "#ccc",
                    color: "white",
                    padding: "4px 8px",
                    borderRadius: "4px",
                    fontSize: "12px",
                    fontWeight: "bold",
                  }}
                >
                  {actionDecision}
                </span>
              </div>

              <div className="card-grid">
                <div className="metric">
                  <label>Model Probability</label>
                  <div className="value">{pct(pred.model_probability)}</div>
                </div>

                {pred.market_price != null && (
                  <div className="metric">
                    <label>Polymarket Reference</label>
                    <div className="value">{pct(pred.market_price)}</div>
                  </div>
                )}

                {pred.edge != null && (
                  <div className="metric">
                    <label>Edge</label>
                    <div
                      className="value"
                      style={{
                        color: pred.edge > 0 ? "#4CAF50" : "#ff6b6b",
                        fontWeight: "bold",
                      }}
                    >
                      {pred.edge > 0 ? "+" : ""}
                      {pct(pred.edge)}
                    </div>
                  </div>
                )}

                <div className="metric">
                  <label>Confidence</label>
                  <div className="confidence-bar">
                    <div
                      className="confidence-fill"
                      style={{
                        width: `${(pred.confidence || 0.5) * 100}%`,
                        backgroundColor: confColor,
                        height: "24px",
                        borderRadius: "4px",
                        display: "flex",
                        alignItems: "center",
                        justifyContent: "center",
                        fontSize: "12px",
                        color: "white",
                        fontWeight: "bold",
                      }}
                    >
                      {pct(pred.confidence)}
                    </div>
                  </div>
                </div>
              </div>

              {pred.key_factors && Object.keys(pred.key_factors).length > 0 && (
                <div className="factors">
                  <label>Key Factors</label>
                  <div className="factor-list">
                    {Object.entries(pred.key_factors)
                      .sort(([, a], [, b]) => b - a)
                      .slice(0, 3)
                      .map(([factor, importance]) => (
                        <div key={factor} className="factor">
                          <span>{factor}</span>
                          <span className="importance">
                            {(importance * 100).toFixed(0)}%
                          </span>
                        </div>
                      ))}
                  </div>
                </div>
              )}

              <button
                className="detail-btn"
                onClick={() => fetchEventDetail(pred.event)}
                style={{
                  marginTop: "12px",
                  padding: "8px 16px",
                  backgroundColor: "#007BFF",
                  color: "white",
                  border: "none",
                  borderRadius: "4px",
                  cursor: "pointer",
                  fontSize: "12px",
                }}
              >
                {selectedEvent === pred.event && detailLoading
                  ? "Loading..."
                  : "Details"}
              </button>
            </div>
          );
        })}
      </div>

      {detail && selectedEvent && (
        <div className="crypto-detail">
          <div className="detail-header">
            <h3>{detail.event}</h3>
            <button
              onClick={() => setDetail(null)}
              style={{
                backgroundColor: "#ff6b6b",
                color: "white",
                border: "none",
                padding: "4px 12px",
                borderRadius: "4px",
                cursor: "pointer",
              }}
            >
              Close
            </button>
          </div>

          <div className="detail-content">
            {detail.predictions && detail.predictions.length > 0 && (
              <div className="detail-section">
                <h4>Prediction Analysis</h4>
                {detail.predictions.map((pred, idx) => (
                  <div key={idx} className="detail-pred">
                    <p>
                      <strong>Predicted Probability:</strong>{" "}
                      {pct(pred.predicted_probability)}
                    </p>
                    {pred.polymarket_reference != null && (
                      <p>
                        <strong>Polymarket Reference:</strong>{" "}
                        {pct(pred.polymarket_reference)}
                      </p>
                    )}
                    {pred.edge != null && (
                      <p>
                        <strong>Edge:</strong>{" "}
                        <span
                          style={{
                            color: pred.edge > 0 ? "#4CAF50" : "#ff6b6b",
                            fontWeight: "bold",
                          }}
                        >
                          {pred.edge > 0 ? "+" : ""}
                          {pct(pred.edge)}
                        </span>
                      </p>
                    )}
                    <p>
                      <strong>Confidence:</strong> {pct(pred.confidence)}
                    </p>

                    {pred.key_factors &&
                      Object.keys(pred.key_factors).length > 0 && (
                        <div className="key-factors">
                          <strong>Key Factors:</strong>
                          <ul>
                            {Object.entries(pred.key_factors)
                              .sort(([, a], [, b]) => b - a)
                              .map(([factor, importance]) => (
                                <li key={factor}>
                                  {factor}: {(importance * 100).toFixed(1)}%
                                </li>
                              ))}
                          </ul>
                        </div>
                      )}
                  </div>
                ))}
              </div>
            )}

            {detail.data_quality != null && (
              <div className="detail-section">
                <p>
                  <strong>Data Quality Score:</strong>{" "}
                  {(detail.data_quality * 100).toFixed(0)}%
                </p>
              </div>
            )}

            {detail.timestamp && (
              <div className="detail-section">
                <p className="timestamp">
                  Updated: {new Date(detail.timestamp).toLocaleString()}
                </p>
              </div>
            )}
          </div>
        </div>
      )}

      <style>{`
        .crypto-vertical {
          padding: 20px;
        }

        .crypto-header {
          margin-bottom: 24px;
        }

        .crypto-header h2 {
          margin: 0 0 8px 0;
          font-size: 24px;
          color: #333;
        }

        .subtitle {
          margin: 0;
          font-size: 13px;
          color: #666;
        }

        .crypto-cards {
          display: grid;
          grid-template-columns: repeat(auto-fill, minmax(350px, 1fr));
          gap: 16px;
          margin-bottom: 24px;
        }

        .crypto-card {
          background: white;
          border-radius: 8px;
          padding: 16px;
          box-shadow: 0 2px 4px rgba(0, 0, 0, 0.1);
          transition: box-shadow 0.2s;
        }

        .crypto-card:hover {
          box-shadow: 0 4px 8px rgba(0, 0, 0, 0.15);
        }

        .card-header {
          display: flex;
          justify-content: space-between;
          align-items: flex-start;
          margin-bottom: 12px;
        }

        .card-header h3 {
          margin: 0;
          font-size: 16px;
          color: #333;
          flex: 1;
        }

        .action-badge {
          white-space: nowrap;
          margin-left: 8px;
        }

        .card-grid {
          display: grid;
          grid-template-columns: repeat(2, 1fr);
          gap: 12px;
          margin-bottom: 12px;
        }

        .metric {
          padding: 8px;
          background: #f5f5f5;
          border-radius: 4px;
        }

        .metric label {
          display: block;
          font-size: 11px;
          color: #666;
          margin-bottom: 4px;
          text-transform: uppercase;
          font-weight: 600;
        }

        .metric .value {
          font-size: 18px;
          font-weight: bold;
          color: #333;
        }

        .confidence-bar {
          width: 100%;
          height: 24px;
          background: #e0e0e0;
          border-radius: 4px;
          overflow: hidden;
        }

        .confidence-fill {
          transition: width 0.3s;
        }

        .factors {
          padding: 8px 0;
          font-size: 12px;
        }

        .factors label {
          display: block;
          color: #666;
          margin-bottom: 8px;
          font-weight: 600;
          text-transform: uppercase;
          font-size: 11px;
        }

        .factor-list {
          display: flex;
          flex-direction: column;
          gap: 6px;
        }

        .factor {
          display: flex;
          justify-content: space-between;
          align-items: center;
          padding: 6px;
          background: #f0f0f0;
          border-radius: 3px;
          font-size: 12px;
        }

        .factor span:first-child {
          text-transform: capitalize;
          color: #333;
        }

        .factor .importance {
          color: #666;
          font-weight: 600;
        }

        .detail-btn {
          width: 100%;
        }

        .crypto-detail {
          background: white;
          border-radius: 8px;
          padding: 20px;
          border-left: 4px solid #007BFF;
          box-shadow: 0 2px 4px rgba(0, 0, 0, 0.1);
          margin-top: 20px;
        }

        .detail-header {
          display: flex;
          justify-content: space-between;
          align-items: center;
          margin-bottom: 16px;
          border-bottom: 1px solid #e0e0e0;
          padding-bottom: 12px;
        }

        .detail-header h3 {
          margin: 0;
          font-size: 18px;
          color: #333;
        }

        .detail-content {
          display: grid;
          grid-template-columns: repeat(auto-fit, minmax(250px, 1fr));
          gap: 20px;
        }

        .detail-section {
          padding: 12px;
          background: #f9f9f9;
          border-radius: 4px;
        }

        .detail-section h4 {
          margin: 0 0 12px 0;
          color: #333;
          font-size: 14px;
        }

        .detail-section p {
          margin: 8px 0;
          font-size: 13px;
          color: #555;
        }

        .detail-pred {
          padding: 12px;
          background: white;
          border-left: 3px solid #007BFF;
          border-radius: 4px;
          margin-bottom: 8px;
        }

        .key-factors {
          margin-top: 12px;
          padding-top: 12px;
          border-top: 1px solid #e0e0e0;
        }

        .key-factors strong {
          display: block;
          margin-bottom: 8px;
          color: #333;
        }

        .key-factors ul {
          margin: 0;
          padding-left: 20px;
          list-style: disc;
        }

        .key-factors li {
          font-size: 12px;
          color: #555;
          margin-bottom: 4px;
        }

        .timestamp {
          font-size: 11px;
          color: #999;
          margin: 0 !important;
        }

        .loading,
        .empty,
        .error {
          padding: 20px;
          text-align: center;
          color: #666;
          background: #f5f5f5;
          border-radius: 8px;
          margin: 20px 0;
        }

        .error {
          background: #ffe0e0;
          color: #c33;
        }
      `}</style>
    </div>
  );
}
