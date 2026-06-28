import { useEffect, useState } from 'react'
import { useParams, Link } from 'react-router-dom'

const VERTICAL_INFO: Record<string, any> = {
  mlb: {
    name: 'MLB Props',
    icon: '⚾',
    description: 'Pitcher strikeout predictions',
    color: 'blue',
  },
  'ai-releases': {
    name: 'AI Releases',
    icon: '⚡',
    description: 'AI model release predictions',
    color: 'purple',
  },
  economics: {
    name: 'Fed & Economics',
    icon: '📊',
    description: 'Economic indicator predictions',
    color: 'green',
  },
  earnings: {
    name: 'Company Earnings',
    icon: '📈',
    description: 'Earnings beat/miss predictions',
    color: 'amber',
  },
  crypto: {
    name: 'Crypto Events',
    icon: '₿',
    description: 'Crypto market predictions',
    color: 'orange',
  },
}

interface Prediction {
  event: string
  market_price: number
  model_probability: number
  edge: number
  kelly: number
  confidence: string
  action: string
}

export function VerticalPage() {
  const { vertical } = useParams<{ vertical: string }>()
  const [predictions, setPredictions] = useState<Prediction[]>([])
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState<string | null>(null)

  const info = VERTICAL_INFO[vertical || ''] || { name: 'Unknown', icon: '?', description: '' }

  useEffect(() => {
    const fetchPredictions = async () => {
      try {
        const response = await fetch(`/api/verticals/${vertical}`)
        const data = await response.json()
        setPredictions(data.predictions || [])
      } catch (err) {
        setError(err instanceof Error ? err.message : 'Failed to load predictions')
      } finally {
        setLoading(false)
      }
    }

    if (vertical) {
      fetchPredictions()
    }
  }, [vertical])

  const getEdgeColor = (edge: number) => {
    if (edge > 0.15) return 'text-green-400'
    if (edge > 0.08) return 'text-yellow-400'
    return 'text-red-400'
  }

  const getActionColor = (action: string) => {
    if (action === 'BUY') return 'bg-green-900 text-green-200'
    if (action === 'SELL') return 'bg-red-900 text-red-200'
    return 'bg-gray-700 text-gray-200'
  }

  return (
    <div className="min-h-screen bg-gray-900 text-white">
      {/* Header */}
      <div className="bg-gradient-to-r from-gray-800 to-gray-900 py-12 px-4 border-b border-gray-700">
        <div className="max-w-6xl mx-auto">
          <Link to="/" className="text-blue-400 hover:text-blue-300 mb-4 inline-block">
            ← Back to All Markets
          </Link>
          <div className="flex items-center gap-4">
            <div className="text-5xl">{info.icon}</div>
            <div>
              <h1 className="text-4xl font-bold">{info.name}</h1>
              <p className="text-gray-400">{info.description}</p>
            </div>
          </div>
        </div>
      </div>

      {/* Content */}
      <div className="max-w-6xl mx-auto px-4 py-12">
        {loading && (
          <div className="text-center text-gray-400">Loading predictions...</div>
        )}

        {error && (
          <div className="bg-red-900 border border-red-700 rounded-lg p-4 text-red-200">
            Error: {error}
          </div>
        )}

        {!loading && !error && predictions.length === 0 && (
          <div className="text-center text-gray-400">No predictions available yet</div>
        )}

        {!loading && !error && predictions.length > 0 && (
          <div>
            <h2 className="text-2xl font-bold mb-6">Top Opportunities</h2>

            <div className="space-y-4">
              {predictions.map((pred, idx) => (
                <div
                  key={idx}
                  className="bg-gray-800 border border-gray-700 rounded-lg p-6 hover:border-gray-600 transition"
                >
                  <div className="grid grid-cols-1 md:grid-cols-6 gap-4 items-center">
                    <div className="md:col-span-2">
                      <h3 className="text-lg font-bold">{pred.event}</h3>
                    </div>

                    <div className="text-center">
                      <p className="text-xs text-gray-400 mb-1">Book Price</p>
                      <p className="text-lg font-bold">{(pred.market_price * 100).toFixed(0)}%</p>
                    </div>

                    <div className="text-center">
                      <p className="text-xs text-gray-400 mb-1">Model Prob</p>
                      <p className="text-lg font-bold">{(pred.model_probability * 100).toFixed(0)}%</p>
                    </div>

                    <div className="text-center">
                      <p className="text-xs text-gray-400 mb-1">Edge</p>
                      <p className={`text-lg font-bold ${getEdgeColor(pred.edge)}`}>
                        {(pred.edge * 100).toFixed(1)}%
                      </p>
                    </div>

                    <div className="text-center">
                      <p className={`inline-block px-3 py-1 rounded font-bold text-sm ${getActionColor(pred.action)}`}>
                        {pred.action}
                      </p>
                    </div>
                  </div>

                  <div className="mt-4 pt-4 border-t border-gray-700 grid grid-cols-2 md:grid-cols-4 gap-4 text-sm">
                    <div>
                      <p className="text-gray-400">Kelly %</p>
                      <p className="font-bold">{(pred.kelly * 100).toFixed(2)}%</p>
                    </div>
                    <div>
                      <p className="text-gray-400">Confidence</p>
                      <p className="font-bold capitalize">{pred.confidence}</p>
                    </div>
                  </div>
                </div>
              ))}
            </div>
          </div>
        )}
      </div>
    </div>
  )
}
