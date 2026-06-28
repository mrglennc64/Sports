import { Link } from 'react-router-dom'

const verticals = [
  {
    id: 'mlb',
    name: 'MLB Props',
    icon: '⚾',
    description: 'Pitcher strikeout predictions vs DraftKings/FanDuel',
    color: 'from-blue-600 to-blue-800',
    path: '/verticals/mlb',
    markets: ['DraftKings', 'FanDuel'],
  },
  {
    id: 'ai-releases',
    name: 'AI Releases',
    icon: '⚡',
    description: 'Claude, GPT, xAI release date predictions',
    color: 'from-purple-600 to-purple-800',
    path: '/verticals/ai-releases',
    markets: ['Polymarket'],
  },
  {
    id: 'economics',
    name: 'Fed & Economics',
    icon: '📊',
    description: 'CPI, interest rates, unemployment predictions',
    color: 'from-green-600 to-green-800',
    path: '/verticals/economics',
    markets: ['Polymarket', 'Kalshi'],
  },
  {
    id: 'earnings',
    name: 'Company Earnings',
    icon: '📈',
    description: 'Beat/miss probability predictions',
    color: 'from-amber-600 to-amber-800',
    path: '/verticals/earnings',
    markets: ['Options Market'],
  },
  {
    id: 'crypto',
    name: 'Crypto Events',
    icon: '₿',
    description: 'Bitcoin price targets, ETF approvals, milestones',
    color: 'from-orange-600 to-orange-800',
    path: '/verticals/crypto',
    markets: ['Polymarket'],
  },
]

export function LandingPage() {
  return (
    <div className="min-h-screen bg-gray-900 text-white">
      {/* Header */}
      <div className="bg-gradient-to-r from-gray-900 to-gray-800 py-20 px-4">
        <div className="max-w-6xl mx-auto text-center">
          <h1 className="text-5xl font-bold mb-4">Edge AI</h1>
          <p className="text-xl text-gray-300 mb-8">
            Multi-Vertical Prediction Platform
          </p>
          <p className="text-lg text-gray-400">
            Identify market mispricings across sports, economics, AI releases, earnings, and crypto
          </p>
        </div>
      </div>

      {/* Verticals Grid */}
      <div className="max-w-6xl mx-auto px-4 py-16">
        <h2 className="text-3xl font-bold mb-12 text-center">Choose Your Market</h2>

        <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-5 gap-4">
          {verticals.map((vertical) => (
            <Link
              key={vertical.id}
              to={vertical.path}
              className="group"
            >
              <div className={`bg-gradient-to-br ${vertical.color} rounded-lg p-6 h-full transform transition hover:scale-105 hover:shadow-2xl`}>
                <div className="text-4xl mb-4">{vertical.icon}</div>
                <h3 className="text-xl font-bold mb-2">{vertical.name}</h3>
                <p className="text-sm text-gray-100 mb-4">{vertical.description}</p>
                <div className="flex flex-wrap gap-1">
                  {vertical.markets.map((market) => (
                    <span
                      key={market}
                      className="text-xs bg-black bg-opacity-30 px-2 py-1 rounded"
                    >
                      {market}
                    </span>
                  ))}
                </div>
              </div>
            </Link>
          ))}
        </div>
      </div>

      {/* Features Section */}
      <div className="bg-gray-800 py-16 px-4 mt-16">
        <div className="max-w-6xl mx-auto">
          <h2 className="text-3xl font-bold mb-12 text-center">How It Works</h2>

          <div className="grid grid-cols-1 md:grid-cols-4 gap-8">
            <div className="text-center">
              <div className="text-3xl mb-4">📊</div>
              <h3 className="text-lg font-bold mb-2">Collect Data</h3>
              <p className="text-gray-300">
                Aggregate data from multiple sources
              </p>
            </div>
            <div className="text-center">
              <div className="text-3xl mb-4">🧠</div>
              <h3 className="text-lg font-bold mb-2">Predict</h3>
              <p className="text-gray-300">
                AI models estimate true probability
              </p>
            </div>
            <div className="text-center">
              <div className="text-3xl mb-4">⚖️</div>
              <h3 className="text-lg font-bold mb-2">Compare</h3>
              <p className="text-gray-300">
                Compare to market implied probability
              </p>
            </div>
            <div className="text-center">
              <div className="text-3xl mb-4">💰</div>
              <h3 className="text-lg font-bold mb-2">Act</h3>
              <p className="text-gray-300">
                Kelly-sized bets on mispricings
              </p>
            </div>
          </div>
        </div>
      </div>

      {/* CTA Section */}
      <div className="max-w-4xl mx-auto px-4 py-16 text-center">
        <h2 className="text-3xl font-bold mb-6">Ready to Find Edges?</h2>
        <Link
          to="/verticals/mlb"
          className="bg-blue-600 hover:bg-blue-700 text-white font-bold py-3 px-8 rounded-lg text-lg inline-block transition"
        >
          Start with MLB Props
        </Link>
      </div>
    </div>
  )
}
