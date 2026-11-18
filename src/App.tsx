import { readResearchDraft } from "./services/researchDraft";
import { lazy, Suspense, useCallback, useEffect, useRef, useState } from 'react';
import { Area, AreaChart, Bar, CartesianGrid, ComposedChart, Legend, Line, ResponsiveContainer, Tooltip, XAxis, YAxis } from 'recharts';
import { Activity, BrainCircuit, ChartNoAxesCombined, ChevronLeft, ChevronRight, FlaskConical, LayoutDashboard, Newspaper, RotateCcw, Settings, ShieldCheck, Sparkles, TrendingDown, TrendingUp, Wallet, Waves, X, Zap, Upload, Download, AlertTriangle, CheckCircle2, Database, Cpu } from 'lucide-react';
import { api, type DatasetRecord, type AgentRunSummary } from './services/api';
import { ReviewCenter } from './components/review/ReviewCenter';
import { DhanWatchlistPanel } from './components/dhan/DhanWatchlistPanel';
import { PaperProposalsPanel } from './components/portfolio/PaperProposalsModal';

const TextRoll = lazy(() =>
  import('./components/ui/text-roll').then(({ TextRoll }) => ({
    default: TextRoll
  }))
);

type Page = 'Overview' | 'Market Lab' | 'Agent Center' | 'Portfolio & Risk' | 'Backtest Studio';
type Scenario =
  | 'VOLATILITY_SURGE'
  | 'RISK_OFF_PULLBACK'
  | 'UNVERIFIED_RUMOR'
  | 'LIQUIDITY_SQUEEZE'
  | 'CRASH'
  | 'RALLY'
  | 'MISLEADING_NEWS'
  | 'LIQUIDITY_SHOCK';
type Status = 'APPROVED' | 'RESIZED' | 'REJECTED' | 'PROPOSAL';
type Quote = {
  symbol: string;
  name: string;
  price: number | null;
  previous: number | null;
  change?: number | null;
  change_pct?: number | null;
  volume?: number | null;
  freshness_status?: string;
  is_stale?: boolean;
  market_session?: string;
  is_live?: boolean;
  price_type?: string;
  market_status?: string;
  feed_status?: string;
  observation_timestamp?: string | null;
  observation_age_seconds?: number | null;
  last_completed_session_date?: string | null;
  session_note?: string | null;
  timezone?: string;
  source?: string;
  provenance?: string;
  timestamp?: string | null;
  history?: { time: string; price: number; equity: number }[];
};
type Position = {
  symbol: string;
  qty: number;
  average: number;
  name?: string;
  current_price?: number | null;
  market_value?: number | null;
  unrealized_pnl?: number | null;
  allocation_pct?: number | null;
  val_status?: string;
};
type Event = { id: number; type: Scenario; severity: number; headline: string; time: string; outcome: Status };
type Order = { id: number; symbol: string; side: 'BUY'|'SELL'; requested: number; executed: number; price: number; fee: number; status: Status; reason: string; time: string };

const initialQuotes: Quote[] = [
  { symbol: 'RELIANCE', name: 'Reliance Industries Limited', price: null, previous: null, freshness_status: 'WAITING_FOR_FIRST_TICK', history: [] },
  { symbol: 'TCS', name: 'Tata Consultancy Services Limited', price: null, previous: null, freshness_status: 'WAITING_FOR_FIRST_TICK', history: [] },
  { symbol: 'INFY', name: 'Infosys Limited', price: null, previous: null, freshness_status: 'WAITING_FOR_FIRST_TICK', history: [] },
  { symbol: 'HDFCBANK', name: 'HDFC Bank Limited', price: null, previous: null, freshness_status: 'WAITING_FOR_FIRST_TICK', history: [] },
  { symbol: 'NIFTY50', name: 'NIFTY 50 Benchmark Index', price: null, previous: null, freshness_status: 'WAITING_FOR_FIRST_TICK', history: [] },
];

type AgentCardData = { name: string; status: string; value: string; text: string; execution_mode: string };
const defaultAgents: AgentCardData[] = [
  'Market Analyst', 'Sentiment Analyst', 'Quantitative Alpha',
  'Macro Strategist', 'Institutional Risk', 'Portfolio Manager',
].map(name => ({
  name, status: 'Idle', value: '', text: 'No recorded execution.', execution_mode: 'idle',
}));

const canonicalScenarios: Scenario[] = [
  'VOLATILITY_SURGE',
  'RISK_OFF_PULLBACK',
  'UNVERIFIED_RUMOR',
  'LIQUIDITY_SQUEEZE',
];

const scenarioCopy: Record<Scenario, { title: string; headline: string }> = {
  VOLATILITY_SURGE: { title: 'Volatility Surge Replay', headline: 'Historical market stress replay: elevated intraday volatility and widening spreads.' },
  RISK_OFF_PULLBACK: { title: 'Risk-Off Pullback Replay', headline: 'Historical macro replay: sovereign yield spikes trigger institutional risk-off rotation.' },
  UNVERIFIED_RUMOR: { title: 'Unverified Rumor Replay', headline: 'Historical sentiment test: unverified speculative rumor circulated on unvetted forums.' },
  LIQUIDITY_SQUEEZE: { title: 'Liquidity Contraction Replay', headline: 'Historical liquidity replay: market depth contracts and execution slippage increases.' },
  CRASH: { title: 'Risk-Off Pullback Replay', headline: 'Historical macro replay: sovereign yield spikes trigger institutional risk-off rotation.' },
  RALLY: { title: 'Volatility Surge Replay', headline: 'Historical market stress replay: elevated intraday volatility and widening spreads.' },
  MISLEADING_NEWS: { title: 'Unverified Rumor Replay', headline: 'Historical sentiment test: unverified speculative rumor circulated on unvetted forums.' },
  LIQUIDITY_SHOCK: { title: 'Liquidity Contraction Replay', headline: 'Historical liquidity replay: market depth contracts and execution slippage increases.' }
};

const scenarioIcons: Record<Scenario, typeof TrendingDown> = {
  VOLATILITY_SURGE: TrendingUp,
  RISK_OFF_PULLBACK: TrendingDown,
  UNVERIFIED_RUMOR: Newspaper,
  LIQUIDITY_SQUEEZE: Waves,
  CRASH: TrendingDown,
  RALLY: TrendingUp,
  MISLEADING_NEWS: Newspaper,
  LIQUIDITY_SHOCK: Waves
};

const nav: { name: Page; icon: typeof LayoutDashboard }[] = [
  { name: 'Overview', icon: LayoutDashboard },
  { name: 'Market Lab', icon: FlaskConical },
  { name: 'Agent Center', icon: BrainCircuit },
  { name: 'Portfolio & Risk', icon: Wallet },
  { name: 'Backtest Studio', icon: ChartNoAxesCombined },
];

const money = (n: number | null | undefined) => {
  if (n === null || n === undefined || isNaN(n)) return 'Unavailable';
  return new Intl.NumberFormat('en-IN', { style: 'currency', currency: 'INR', maximumFractionDigits: 0 }).format(n);
};
const pct = (n: number | null | undefined) => {
  if (n === null || n === undefined || isNaN(n)) return '--';
  return `${n >= 0 ? '+' : ''}${n.toFixed(2)}%`;
};

export default function App() {
  const toPage = (path: string): Page | null => ({
    '/app/overview': 'Overview',
    '/app/market-lab': 'Market Lab',
    '/app/agents': 'Agent Center',
    '/app/portfolio': 'Portfolio & Risk',
    '/app/backtest': 'Backtest Studio'
  }[path] as Page || null);

  const [page, setPage] = useState<Page | null>(() => toPage(window.location.pathname));
  const [quotes, setQuotes] = useState(initialQuotes);
  const [cash, setCash] = useState(1000000);
  const [positions, setPositions] = useState<Position[]>([]);
  const [events, setEvents] = useState<Event[]>([]);
  const [orders, setOrders] = useState<Order[]>([]);
  const [decisions, setDecisions] = useState<any[]>([]);
  const [monitor, setMonitor] = useState<any>(null);
  const [scenario, setScenario] = useState<Scenario>('RISK_OFF_PULLBACK');
  const [severity, setSeverity] = useState(60);
  const [selected, setSelected] = useState('RELIANCE');
  const [running, setRunning] = useState(false);
  const [workflowError, setWorkflowError] = useState<string | null>(null);
  const [drawer, setDrawer] = useState(false);
  const [autoExecute, setAutoExecute] = useState(true);
  const [settings, setSettings] = useState({ fee: 0.1, maxOrder: 10, maxAllocation: 25, drawdown: 10 });
  const [backendConnected, setBackendConnected] = useState(false);
  const [modelStatus, setModelStatus] = useState<any>(null);
  const [feedStatus, setFeedStatus] = useState<string>('CONNECTING');
  const [agents, setAgents] = useState<AgentCardData[]>(defaultAgents);

  const refreshFromBackend = async () => {
    try {
      const [summary, cfg, ordersRes, portRes, decsRes, monRes, mStatus, fStatus] = await Promise.all([
        api.getDashboardSummary(),
        api.getRiskConfig(),
        api.getOrders(),
        api.getPortfolio(),
        api.getDecisionsHistory(),
        api.getAgentsMonitor().catch(() => null),
        api.getModelStatus().catch(() => null),
        api.getDhanStatus().catch(() => null),
      ]);
      if (mStatus) setModelStatus(mStatus);
      if (fStatus && fStatus.status) setFeedStatus(fStatus.status);
      if (summary && summary.watchlist && summary.watchlist.length) {
        setQuotes(summary.watchlist);
        if (summary.agents && summary.agents.length) setAgents(summary.agents);
        if (summary.recent_activity) setEvents(summary.recent_activity);
      }
      if (portRes) {
        setCash(portRes.cash);
        setPositions(portRes.positions || []);
      }
      if (ordersRes) {
        setOrders(ordersRes);
      }
      if (decsRes) {
        setDecisions(decsRes);
      }
      if (monRes) {
        setMonitor(monRes);
      }
      if (cfg) {
        setSettings({
          fee: cfg.fee,
          maxOrder: cfg.maxOrder,
          maxAllocation: cfg.maxAllocation,
          drawdown: cfg.drawdown,
        });
        setAutoExecute(cfg.auto_execute);
      }
      setBackendConnected(true);
    } catch {
      setBackendConnected(false);
    }
  };

  useEffect(() => {
    document.title = 'HIVE — AI-Assisted Intelligence for Smarter Financial Decisions';
    refreshFromBackend();
  }, []);

  const prices = Object.fromEntries(quotes.map(q => [q.symbol, q.price]));
  const invested = positions.reduce((s, p) => {
    const cur = p.market_value ?? (p.current_price != null ? p.qty * p.current_price : (prices[p.symbol] != null ? p.qty * prices[p.symbol]! : null));
    return s + (cur ?? p.qty * p.average);
  }, 0);
  const equity = cash + invested;
  const current = quotes.find(q => q.symbol === selected) || quotes[0] || initialQuotes[0];
  const allocation = (symbol: string, qty: number) => {
    const p = prices[symbol] ?? current.price;
    return p != null && equity > 0 ? (qty * p) / equity * 100 : 0;
  };

  const reset = async (token: string) => {
    if (confirm('Reset the paper portfolio, order history, and simulated events?')) {
      await api.resetSimulation(token);
      await refreshFromBackend();
    }
  };

  const runAnalysis = async () => {
    setRunning(true);
    setWorkflowError(null);
    try {
      await api.runDecisionPipeline(selected, undefined, severity);
      await refreshFromBackend();
    } catch (error) {
      setWorkflowError(error instanceof Error ? error.message : String(error));
    } finally {
      setRunning(false);
    }
  };

  const inject = async () => {
    setRunning(true);
    setWorkflowError(null);
    try {
      await api.runDecisionPipeline(selected, scenario, severity);
      await refreshFromBackend();
    } catch (error) {
      setWorkflowError(error instanceof Error ? error.message : String(error));
    } finally {
      setRunning(false);
    }
  };

  const confirmProposal = async (orderId: number) => {
    try {
      await api.confirmOrder(orderId);
      await refreshFromBackend();
    } catch (err: any) {
      alert(err.message || 'Failed to confirm order');
    }
  };

  const handlePrimaryAction = async () => {
    if (page === 'Market Lab') {
      await inject();
    } else if (page === 'Agent Center') {
      setRunning(true);
      try {
        const storedPrompt = readResearchDraft() || 'Analyze 20-day SMA, RSI momentum, and annualized volatility for allocation sizing.';
        await api.triggerAgentRun({
          symbol: selected || 'RELIANCE',
          task_prompt: storedPrompt,
          task_type: 'MARKET_ANALYSIS',
        });
        await refreshFromBackend();
      } catch (err) {
        console.error('Agent Center trigger error:', err);
      } finally {
        setRunning(false);
      }
    } else {
      await runAnalysis();
    }
  };

  const navigate = (p: Page | null) => {
    const path = p ? ({
      'Overview': '/app/overview',
      'Market Lab': '/app/market-lab',
      'Agent Center': '/app/agents',
      'Portfolio & Risk': '/app/portfolio',
      'Backtest Studio': '/app/backtest'
    }[p]) : '/';
    window.history.pushState({}, '', path);
    setPage(p);
    window.scrollTo(0, 0);
  };

  useEffect(() => {
    const pop = () => setPage(toPage(window.location.pathname));
    window.addEventListener('popstate', pop);
    return () => window.removeEventListener('popstate', pop);
  }, []);

  useEffect(() => {
    const navButtons = document.querySelectorAll<HTMLButtonElement>('.app>.sidebar>nav button');
    navButtons.forEach(button => {
      const label = button.textContent?.trim();
      if (label) {
        button.setAttribute('aria-label', label);
        button.title = label;
      }
      if (button.classList.contains('active')) button.setAttribute('aria-current', 'page');
      else button.removeAttribute('aria-current');
    });
    const homeButton = document.querySelector<HTMLButtonElement>('.app>.sidebar>.home-link');
    if (homeButton) {
      homeButton.setAttribute('aria-label', 'Back to Home');
      homeButton.title = 'Back to Home';
    }
    const settingsButton = document.querySelector<HTMLButtonElement>('.app>.sidebar .settings-trigger');
    if (settingsButton) {
      settingsButton.setAttribute('aria-label', 'Settings');
      settingsButton.title = 'Settings';
    }
  }, [page]);

  const goMarket = (s?: Scenario) => {
    if (s) setScenario(s);
    navigate('Market Lab');
  };

  if (!page) return <HomeEnhanced navigate={navigate} />;

  return (
    <div className="app">
      <aside className="sidebar">
        <button className="home-link" onClick={() => navigate(null)}>
          ← <span>Back to Home</span>
        </button>
        <div className="brand">
          <div className="mark"><ChevronRight/></div>
          <div>
            <b>HIVE</b>
            <small>ANALYZE. EVALUATE. EVOLVE.</small>
          </div>
        </div>
        <nav>
          {nav.map(({ name, icon: Icon }) => (
            <button
              key={name}
              className={page === name ? 'active' : ''}
              onClick={() => navigate(name)}
            >
              <Icon/>
              <span>{name}</span>
            </button>
          ))}
        </nav>
        <div className="side-bottom">
          <div className="settings-anchor">
            <button
              className="settings-trigger"
              aria-expanded={drawer}
              onClick={() => setDrawer(value => !value)}
            >
              <Settings/> <span>Settings</span>
            </button>
            {drawer && (
              <SettingsDrawer
                close={() => setDrawer(false)}
                settings={settings}
                setSettings={setSettings}
                autoExecute={autoExecute}
                setAutoExecute={setAutoExecute}
                reset={reset}
              />
            )}
          </div>
        </div>
      </aside>

      <main>
        <header className="topbar">
          <div>
            <h1>{page}</h1>
            <p>{subtitle(page)}</p>
          </div>
          <div className="actions">
            <span className="data-badge">
              {backendConnected ? '● FASTAPI BACKEND' : '● PAPER SIMULATION'}
            </span>
            <span
              className={`ready ${backendConnected && (modelStatus?.ready || modelStatus?.ollama_reachable) ? 'online' : backendConnected ? 'warning' : 'offline'}`}
              title={modelStatus?.status_message || (backendConnected ? 'Backend online' : 'Backend offline')}
            >
              <span className="dot" />
              {!backendConnected
                ? 'Backend Offline'
                : modelStatus?.ready
                ? `Models Ready · ${feedStatus === 'MARKET_CLOSED' ? 'Market Closed' : feedStatus === 'DATA_FRESH' || feedStatus === 'LIVE' ? 'Feed Live' : feedStatus || 'Active'}`
                : modelStatus?.ollama_reachable
                ? 'Models Unavailable'
                : 'Ollama Unavailable'}
            </span>
            <button className="icon-button" title="Open simulation reset settings" aria-label="Open simulation reset settings" onClick={() => setDrawer(true)}>
              <RotateCcw/>
            </button>
            <button
              className="primary"
              onClick={handlePrimaryAction}
              disabled={running}
              title={
                page === 'Agent Center'
                  ? 'Execute LangGraph Qwen Executor ➔ Gemma Reviewer evaluation loop'
                  : page === 'Market Lab'
                  ? 'Inject deterministic market scenario'
                  : 'Execute 6-agent portfolio decision pipeline'
              }
            >
              {running ? <Activity className="spin"/> : <Zap/>}
              {page === 'Market Lab' ? 'Inject Event' : page === 'Agent Center' ? 'Run AI Assistant' : 'Run Consensus'}
            </button>
          </div>
        </header>
        {workflowError && <p role="alert">{workflowError}</p>}

        <section className="content">
          {page === 'Overview' && (
            <Overview
              equity={equity}
              cash={cash}
              invested={invested}
              positions={positions}
              prices={prices}
              quotes={quotes}
              events={events}
              running={running}
              goMarket={goMarket}
              agents={agents}
              onNavigateAgentCenter={() => setPage('Agent Center')}
            />
          )}
          {page === 'Market Lab' && (
            <MarketLab
              current={current}
              scenario={scenario}
              setScenario={setScenario}
              severity={severity}
              setSeverity={setSeverity}
              selected={selected}
              setSelected={setSelected}
              quotes={quotes}
              events={events}
              running={running}
              inject={inject}
              onRefresh={refreshFromBackend}
            />
          )}
          {page === 'Agent Center' && (
            <AgentCenter
              running={running}
              events={events}
              orders={orders}
              decisions={decisions}
              monitor={monitor}
              selected={selected}
              agents={agents}
              onConfirmOrder={confirmProposal}
              quotes={quotes}
              onSelectSymbol={setSelected}
              feedStatus={feedStatus}
              backendConnected={backendConnected}
            />
          )}
          {page === 'Portfolio & Risk' && (
            <Portfolio
              equity={equity}
              cash={cash}
              invested={invested}
              positions={positions}
              quotes={quotes}
              orders={orders}
              allocation={allocation}
              settings={settings}
              onRefresh={refreshFromBackend}
            />
          )}
          {page === 'Backtest Studio' && (
            <Backtest/>
          )}
        </section>
      </main>
    </div>
  );
}

function subtitle(p: Page) {
  return {
    Overview: 'Your autonomous market simulation at a glance.',
    'Market Lab': 'Inject a market event and observe the full decision pipeline.',
    'Agent Center': 'Inspect how specialist roles contribute to each simulated decision.',
    'Portfolio & Risk': 'Track holdings, simulated performance and the limits protecting the portfolio.',
    'Backtest Studio': 'Evaluate quantitative strategies against verified historical market data (NSE).',
  }[p];
}

function HomeEnhanced({ navigate }: { navigate: (p: Page | null) => void }) {
  return (
    <>
      <HomeLite navigate={navigate}/>
      <HomepageMotionNoCursor/>
    </>
  );
}

function HomepageMotionNoCursor() {
  useEffect(() => {
    const root = document.querySelector<HTMLElement>('.home-lite');
    if (!root || matchMedia('(prefers-reduced-motion: reduce)').matches) return;
    root.classList.add('motion-ready');
    const entries = Array.from(root.querySelectorAll<HTMLElement>('.hero-copy>*, .credibility, .home-section, .break-section'));
    entries.forEach((el, i) => {
      el.classList.add('reveal-item');
      el.style.setProperty('--reveal-delay', `${Math.min(i, 5) * 70}ms`);
    });
    const observer = new IntersectionObserver(items => items.forEach(item => {
      if (item.isIntersecting) {
        item.target.classList.add('is-revealed');
        observer.unobserve(item.target);
      }
    }), { threshold: 0.12, rootMargin: '0px 0px -40px' });
    entries.forEach(el => observer.observe(el));
    const cards = Array.from(root.querySelectorAll<HTMLElement>('.tilt-card'));
    const tilt = (event: PointerEvent) => {
      const card = event.currentTarget as HTMLElement;
      const rect = card.getBoundingClientRect();
      card.style.setProperty('--tilt-x', `${((event.clientY - rect.top) / rect.height - 0.5) * -3}deg`);
      card.style.setProperty('--tilt-y', `${((event.clientX - rect.left) / rect.width - 0.5) * 3}deg`);
      card.style.setProperty('--shine-x', `${(event.clientX - rect.left) / rect.width * 100}%`);
      card.style.setProperty('--shine-y', `${(event.clientY - rect.top) / rect.height * 100}%`);
    };
    const leave = (event: PointerEvent) => {
      const card = event.currentTarget as HTMLElement;
      card.style.setProperty('--tilt-x', '0deg');
      card.style.setProperty('--tilt-y', '0deg');
    };
    cards.forEach(card => {
      card.addEventListener('pointermove', tilt);
      card.addEventListener('pointerleave', leave);
    });
    return () => {
      observer.disconnect();
      cards.forEach(card => {
        card.removeEventListener('pointermove', tilt);
        card.removeEventListener('pointerleave', leave);
      });
      root.classList.remove('motion-ready');
    };
  }, []);
  return null;
}

function StockVisual() {
  return (
    <div className="stock-visual" aria-hidden="true">
      <svg viewBox="0 0 760 430" preserveAspectRatio="none">
        <defs>
          <linearGradient id="stock-stroke" x1="0" x2="1">
            <stop stopColor="#4a78b0" stopOpacity="0"/>
            <stop offset=".23" stopColor="#4a78b0" stopOpacity=".45"/>
            <stop offset=".84" stopColor="#4a78b0"/>
            <stop offset="1" stopColor="#4a78b0" stopOpacity=".1"/>
          </linearGradient>
          <linearGradient id="stock-fill" x1="0" x2="0" y1="0" y2="1">
            <stop stopColor="#4a78b0" stopOpacity=".18"/>
            <stop offset="1" stopColor="#4a78b0" stopOpacity="0"/>
          </linearGradient>
        </defs>
        <g className="market-grid">
          {[70, 140, 210, 280, 350].map(y => <path key={y} d={`M0 ${y}H760`}/>)}
          {[90, 190, 290, 390, 490, 590, 690].map(x => <path key={x} d={`M${x} 0V430`}/>)}
        </g>
        <path className="market-area" d="M0 311 C45 300 67 335 108 292 S172 230 218 268 S288 319 332 232 S405 207 447 245 S506 194 553 214 S619 130 667 165 S713 150 760 91 V430H0Z"/>
        <path className="market-line" d="M0 311 C45 300 67 335 108 292 S172 230 218 268 S288 319 332 232 S405 207 447 245 S506 194 553 214 S619 130 667 165 S713 150 760 91"/>
        <g className="candles">
          {[[382, 250, 285, 228], [421, 220, 267, 198], [461, 215, 250, 187], [501, 191, 236, 173], [541, 180, 225, 151], [581, 154, 206, 137]].map(([x, top, bottom, wick], i) => (
            <g key={x} className={i === 1 || i === 4 ? 'negative' : ''}>
              <path d={`M${x + 6} ${wick}V${bottom + 18}`}/>
              <rect x={x} y={top} width="12" height={bottom - top}/>
            </g>
          ))}
        </g>
        <circle className="market-point" cx="667" cy="165" r="5"/>
      </svg>
      <span className="stock-label label-one">RELIANCE · HISTORICAL NSE</span>
      <span className="stock-label label-two">MARKET INDEX</span>
      <span className="stock-label label-three">RISK SIGNAL</span>
    </div>
  );
}

function LiquidEffects({ host }: { host: React.RefObject<HTMLDivElement> }) {
  useEffect(() => {
    const root = host.current;
    if (!root || matchMedia('(prefers-reduced-motion: reduce)').matches) return;
    let last = 0;
    const add = (event: PointerEvent, burst = false) => {
      const box = root.getBoundingClientRect();
      const x = event.clientX - box.left;
      const y = event.clientY - box.top;
      const now = performance.now();
      if (!burst && now - last < 90) return;
      last = now;
      const total = burst ? 3 : 1;
      for (let i = 0; i < total; i++) {
        const ring = document.createElement('i');
        ring.className = burst ? 'water-ring burst' : 'water-ring';
        ring.style.left = `${x}px`;
        ring.style.top = `${y}px`;
        ring.style.setProperty('--ring-delay', `${i * 70}ms`);
        root.appendChild(ring);
        window.setTimeout(() => ring.remove(), 900);
      }
      const wake = document.createElement('i');
      wake.className = 'water-wake';
      wake.style.left = `${x}px`;
      wake.style.top = `${y}px`;
      root.appendChild(wake);
      window.setTimeout(() => wake.remove(), 650);
    };
    const move = (e: PointerEvent) => add(e);
    const down = (e: PointerEvent) => add(e, true);
    root.addEventListener('pointermove', move, { passive: true });
    root.addEventListener('pointerdown', down, { passive: true });
    return () => {
      root.removeEventListener('pointermove', move);
      root.removeEventListener('pointerdown', down);
    };
  }, [host]);
  return null;
}

function HomeLite({ navigate }: { navigate: (p: Page | null) => void }) {
  const root = useRef<HTMLDivElement>(null);
  const feature = [
    ['Multi-Agent Intelligence', 'Specialist financial-analysis agents work with structured evidence and configured local models to produce inspectable outputs and support risk-aware decisions.', BrainCircuit],
    ['AI Review & Observability', 'Inspect execution traces, independent reviewer findings, evidence references, and objective checks to understand where an agent succeeded or failed.', FlaskConical],
    ['Continuous Improvement', 'Turn genuine findings into bounded improvement proposals, compare baseline and candidate prompts, and require controlled approval before activating a qualifying change.', ShieldCheck],
    ['Risk-Governed Research', 'Explore market-stress scenarios, inspect paper-portfolio constraints, and evaluate quantitative strategies against configured historical data.', ChartNoAxesCombined]
  ] as const;

  return (
    <div className="home home-lite" ref={root}>
      <div className="liquid-light"/>
      <StockVisual/>
      <LiquidEffects host={root}/>
      <header className="marketing-nav minimal">
        <div className="home-brand">
          <span className="home-mark"><ChevronRight/></span>
          <b>HIVE</b>
        </div>
      </header>
      <main>
        <section className="hero hero-minimal">
          <div className="hero-copy">
            <span className="eyebrow">SELF-EVOLVING FINANCIAL INTELLIGENCE</span>
            <h1>
              <Suspense fallback={<><span>Analyze. Evaluate.</span><br/><i><span>Evolve.</span></i></>}>
                <TextRoll className="text-roll-line" duration={0.42} getEnterDelay={index => index * 0.035} getExitDelay={index => index * 0.035 + 0.16}>Analyze. Evaluate.</TextRoll>
                <br/>
                <i><TextRoll className="text-roll-line" duration={0.42} getEnterDelay={index => index * 0.035} getExitDelay={index => index * 0.035 + 0.16}>Evolve.</TextRoll></i>
              </Suspense>
            </h1>
            <p>HIVE evaluates financial AI agents through independent review, evidence-backed findings, objective checks, and benchmark-validated improvement—within a risk-governed research and paper-trading environment.</p>
            <div className="hero-actions">
              <button className="launch big" onClick={() => navigate('Overview')}>
                Launch Simulator <ChevronRight/>
              </button>
            </div>
            <div className="paper-note">
              <span/> Paper trading only <small>Historical research and simulation</small>
            </div>
          </div>
        </section>

        <section className="credibility">
          <div><Sparkles/>Multi-agent analysis</div>
          <div><FlaskConical/>AI review &amp; observability</div>
          <div><ShieldCheck/>Benchmark-validated improvement</div>
          <div><ChartNoAxesCombined/>Deterministic risk controls</div>
        </section>

        <section className="home-section">
          <span className="eyebrow">THE HIVE PLATFORM</span>
          <h2>Financial research meets <i>agent reliability.</i></h2>
          <p className="lead">Continuous review, evidence-backed findings, and benchmark-validated improvement for financial AI agents.</p>
          <div className="feature-grid">
            {feature.map(([title, text, Icon]) => (
              <article className="tilt-card" key={title}>
                <span className="feature-icon"><Icon/></span>
                <h3>{title}</h3>
                <p>{text}</p>
              </article>
            ))}
          </div>
        </section>

        <section className="home-section workflow-home">
          <span className="eyebrow">A CLEAR DECISION PIPELINE</span>
          <h2>Reasoned at every <i>step.</i></h2>
          <div className="home-flow">
            {[
              { label: 'Market Data', Icon: Activity },
              { label: 'Specialist Analysis', Icon: ChartNoAxesCombined },
              { label: 'Portfolio Proposal', Icon: Wallet },
              { label: 'Risk Gate', Icon: ShieldCheck },
              { label: 'Simulated Execution', Icon: Zap }
            ].map(({ label, Icon }, i) => (
              <div key={label} className={label === 'Risk Gate' ? 'gate tilt-card' : 'tilt-card'}>
                <b>0{i + 1}</b>
                <span className="step-icon"><Icon aria-hidden="true"/></span>
                <span>{label}</span>
                {i < 4 && <em>&rarr;</em>}
              </div>
            ))}
          </div>
          <p className="disclosure">Paper-trading workflow with deterministic risk controls. Simulation only.</p>
        </section>

        <section className="break-section">
          <div>
            <span className="eyebrow">SIMULATED SCENARIO</span>
            <h2>What happens when<br/>the market <i>breaks?</i></h2>
            <p>Market shocks generate a testable scenario in which a proposed action can be inspected and checked by the deterministic Risk Gate before a virtual order is applied.</p>
          </div>
          <div className="break-demo tilt-card">
            <span className="crash-label">EXAMPLE SCENARIO · 60%</span>
            <div className="crash-line"><i/><i/><i/><i/><i/><i/></div>
            <div className="risk-result">
              <ShieldCheck/>
              <div>
                <small>EXAMPLE RISK CHECK</small>
                <b>Scenario illustration</b>
              </div>
              <span>Simulation only</span>
            </div>
          </div>
        </section>
      </main>

      <footer>
        <div className="home-brand"><span className="home-mark"><ChevronRight/></span><b>HIVE</b></div>
        <p>Financial agent review and paper-trading simulator for educational research.</p>
        <small>© {new Date().getFullYear()} HIVE · Analyze. Evaluate. Evolve. · Simulation only. Not investment advice.</small>
      </footer>
    </div>
  );
}

function Card({ children, className = '', style }: { children: React.ReactNode; className?: string; style?: React.CSSProperties }) {
  return <section className={'card ' + className} style={style}>{children}</section>;
}

const getAgentIcon = (name: string) => {
  if (name.includes('Market')) return <ChartNoAxesCombined/>;
  if (name.includes('Sentiment')) return <Sparkles/>;
  if (name.includes('Quant')) return <Activity/>;
  if (name.includes('Macro')) return <Waves/>;
  if (name.includes('Risk')) return <ShieldCheck/>;
  return <BrainCircuit/>;
};

type TimeframeOption = '1M' | '3M' | '6M' | '1Y';

const TIMEFRAME_BARS: Record<TimeframeOption, number> = {
  '1M': 30,
  '3M': 60,
  '6M': 120,
  '1Y': 246,
};

function MarketPriceChart({ symbol }: { symbol: string }) {
  const [candles, setCandles] = useState<{
    time: string;
    rawDate: string;
    price: number;
    open: number;
    high: number;
    low: number;
    volume: number;
    candleType?: string;
  }[]>([]);
  const [candleType, setCandleType] = useState<string>('HISTORICAL_DAILY_BAR');
  const [timeframe, setTimeframe] = useState<TimeframeOption>('3M');
  const [loading, setLoading] = useState(false);

  useEffect(() => {
    let mounted = true;
    setLoading(true);
    const barsCount = TIMEFRAME_BARS[timeframe] || 60;
    api.getCandles(symbol, barsCount).then((data) => {
      if (!mounted || !data) return;
      if (data.length > 0 && data[0].candle_type) {
        setCandleType(data[0].candle_type);
      }
      const isHist = data.length > 0 && data[0].candle_type === 'HISTORICAL_DAILY_BAR';
      const pts = data.map((c: any) => {
        const rawTs = typeof c.timestamp === 'string' ? c.timestamp : String(c.timestamp);
        let timeLabel = rawTs;
        if (isHist) {
          timeLabel = rawTs.slice(0, 10);
        } else {
          timeLabel = rawTs.includes('T') ? rawTs.split('T')[1].slice(0, 5) : rawTs.slice(11, 16);
          if (!timeLabel || timeLabel.length < 3) {
            timeLabel = rawTs.slice(0, 10);
          }
        }
        return {
          time: timeLabel,
          rawDate: rawTs.slice(0, 10),
          price: Number(c.close),
          open: Number(c.open ?? c.close),
          high: Number(c.high ?? c.close),
          low: Number(c.low ?? c.close),
          volume: Number(c.volume ?? 0),
          candleType: c.candle_type,
        };
      });
      setCandles(pts);
    }).catch(() => {}).finally(() => {
      if (mounted) setLoading(false);
    });
    return () => { mounted = false; };
  }, [symbol, timeframe]);

  if (loading && candles.length === 0) {
    return (
      <div className="chart-empty-state" style={{ minHeight: '260px', display: 'flex', flexDirection: 'column', alignItems: 'center', justifyContent: 'center' }}>
        <Activity className="spin" size={24} style={{ color: 'var(--hive-accent, #4A78B0)', marginBottom: '8px' }} />
        <p style={{ color: 'var(--hive-text-secondary, #59627E)', fontSize: '13px', margin: 0 }}>Loading verified market data for {symbol}...</p>
      </div>
    );
  }

  if (candles.length === 0) {
    return (
      <div className="chart-empty-state" style={{ padding: '40px 16px', textAlign: 'center', minHeight: '260px', display: 'flex', flexDirection: 'column', alignItems: 'center', justifyContent: 'center' }}>
        <Activity size={28} style={{ opacity: 0.5, margin: '0 auto 10px', color: '#64748B' }} />
        <p style={{ fontWeight: 600, color: 'var(--hive-text-primary, #0B1730)', margin: '0 0 6px', fontSize: '14px' }}>No Chart Observations Available</p>
        <span style={{ fontSize: '12px', color: 'var(--hive-text-secondary, #59627E)', maxWidth: '380px', display: 'block', margin: '0 auto', lineHeight: '1.5' }}>
          Historical database records or live polling data for {symbol} are currently unavailable.
        </span>
      </div>
    );
  }

  const isHistorical = candleType === 'HISTORICAL_DAILY_BAR';
  const prices = candles.map(c => c.price).filter(p => !isNaN(p) && p > 0);
  const minP = prices.length > 0 ? Math.min(...prices) : 100;
  const maxP = prices.length > 0 ? Math.max(...prices) : 100;
  const pBuffer = maxP > minP ? (maxP - minP) * 0.08 : maxP * 0.04;
  const yDomain = [
    Math.max(0, Math.floor(minP - pBuffer)),
    Math.ceil(maxP + pBuffer)
  ];

  const firstPrice = candles[0]?.price || 0;
  const lastPrice = candles[candles.length - 1]?.price || 0;
  const periodDelta = firstPrice > 0 ? lastPrice - firstPrice : 0;
  const periodDeltaPct = firstPrice > 0 ? (periodDelta / firstPrice) * 100 : 0;
  const isUp = periodDelta >= 0;

  const totalVolume = candles.reduce((acc, c) => acc + (c.volume || 0), 0);
  const avgVolume = candles.length > 0 ? Math.round(totalVolume / candles.length) : 0;
  const maxVol = Math.max(...candles.map(c => c.volume || 0));
  const volDomain = [0, maxVol > 0 ? maxVol * 4.2 : 1000];

  const formatVol = (val: number) => {
    if (!val) return '0';
    if (val >= 10_000_000) return `${(val / 10_000_000).toFixed(2)} Cr`;
    if (val >= 100_000) return `${(val / 100_000).toFixed(1)} L`;
    if (val >= 1_000) return `${(val / 1_000).toFixed(0)}k`;
    return String(val);
  };

  const strokeColor = isUp ? '#10B981' : '#EF4444';
  const fillColor = isUp ? '#10B981' : '#EF4444';

  const CustomTooltip = ({ active, payload }: any) => {
    if (!active || !payload || !payload.length) return null;
    const pt = payload[0].payload;
    const candleChange = pt.open > 0 ? ((pt.price - pt.open) / pt.open) * 100 : 0;
    return (
      <div style={{
        background: 'rgba(255, 255, 255, 0.98)',
        backdropFilter: 'blur(16px)',
        border: '1px solid var(--hive-border, #D8E2EF)',
        borderRadius: 10,
        padding: '10px 14px',
        boxShadow: '0 8px 24px rgba(31, 53, 87, 0.12)',
        color: '#0B1730',
        fontSize: '11px',
        minWidth: '200px'
      }}>
        <div style={{ display: 'flex', justifyContent: 'space-between', borderBottom: '1px solid #E2EBF5', paddingBottom: '5px', marginBottom: '6px' }}>
          <span style={{ fontWeight: 700, color: 'var(--hive-text-primary, #0B1730)' }}>{symbol}</span>
          <span style={{ color: '#64748B', fontSize: '10px' }}>{pt.time}</span>
        </div>
        <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: '4px 12px', marginBottom: '6px' }}>
          <div><span style={{ color: '#64748B' }}>Close: </span><b style={{ color: 'var(--hive-text-primary, #0B1730)' }}>{money(pt.price)}</b></div>
          <div><span style={{ color: '#64748B' }}>Open: </span><b>{money(pt.open)}</b></div>
          <div><span style={{ color: '#64748B' }}>High: </span><b style={{ color: '#10B981' }}>{money(pt.high)}</b></div>
          <div><span style={{ color: '#64748B' }}>Low: </span><b style={{ color: '#EF4444' }}>{money(pt.low)}</b></div>
        </div>
        <div style={{ display: 'flex', justifyContent: 'space-between', borderTop: '1px dashed #E2EBF5', paddingTop: '5px', fontSize: '10px' }}>
          <span style={{ color: '#64748B' }}>Bar Change:</span>
          <span style={{ fontWeight: 600, color: candleChange >= 0 ? '#10B981' : '#EF4444' }}>
            {candleChange >= 0 ? '+' : ''}{candleChange.toFixed(2)}%
          </span>
        </div>
        {pt.volume > 0 && (
          <div style={{ display: 'flex', justifyContent: 'space-between', fontSize: '10px', marginTop: '2px' }}>
            <span style={{ color: '#64748B' }}>Volume:</span>
            <span style={{ fontWeight: 600, color: '#0B1730' }}>{formatVol(pt.volume)}</span>
          </div>
        )}
      </div>
    );
  };

  return (
    <div style={{ display: 'flex', flexDirection: 'column', gap: '12px' }}>
      {/* Chart Sub-Header Controls & Range Metrics */}
      <div style={{
        display: 'flex',
        justifyContent: 'space-between',
        alignItems: 'center',
        flexWrap: 'wrap',
        gap: '8px',
        padding: '0 2px'
      }}>
        <div style={{ display: 'flex', alignItems: 'center', gap: '8px', flexWrap: 'wrap' }}>
          <span style={{
            display: 'inline-flex',
            alignItems: 'center',
            gap: '5px',
            padding: '2px 8px',
            borderRadius: '4px',
            background: isHistorical ? 'rgba(148, 163, 184, 0.14)' : 'rgba(16, 185, 129, 0.14)',
            color: isHistorical ? '#64748B' : '#10B981',
            fontSize: '10px',
            fontWeight: 600,
            fontFamily: 'monospace'
          }}>
            {isHistorical ? 'HISTORICAL DAILY BARS (NSE) — MARKET CLOSED' : 'LIVE POLLING INTRADAY BARS'}
          </span>
          <div style={{ display: 'flex', alignItems: 'center', gap: '10px', fontSize: '11px', color: '#64748B' }}>
            <span>High: <b style={{ color: 'var(--hive-text-primary, #0B1730)' }}>{money(maxP)}</b></span>
            <span>Low: <b style={{ color: 'var(--hive-text-primary, #0B1730)' }}>{money(minP)}</b></span>
            <span>Range Return: <b style={{ color: isUp ? '#10B981' : '#EF4444' }}>
              {isUp ? '+' : ''}{money(periodDelta)} ({isUp ? '+' : ''}{periodDeltaPct.toFixed(2)}%)
            </b></span>
            {avgVolume > 0 && (
              <span className="hide-mobile">Avg Vol: <b style={{ color: 'var(--hive-text-primary, #0B1730)' }}>{formatVol(avgVolume)}</b></span>
            )}
          </div>
        </div>

        {/* Timeframe Selector Pills */}
        <div style={{
          display: 'inline-flex',
          background: 'rgba(255, 255, 255, 0.75)',
          padding: '2px',
          borderRadius: '8px',
          border: '1px solid var(--hive-border, #D8E2EF)'
        }}>
          {(['1M', '3M', '6M', '1Y'] as TimeframeOption[]).map(tf => (
            <button
              key={tf}
              type="button"
              onClick={() => setTimeframe(tf)}
              style={{
                border: 0,
                background: timeframe === tf ? 'var(--hive-accent, #4A78B0)' : 'transparent',
                color: timeframe === tf ? '#ffffff' : 'var(--hive-text-secondary, #59627E)',
                padding: '3px 8px',
                fontSize: '11px',
                fontWeight: 600,
                borderRadius: '6px',
                cursor: 'pointer',
                transition: 'all 0.15s ease'
              }}
            >
              {tf}
            </button>
          ))}
        </div>
      </div>

      {/* Primary Financial Chart: Composed Area + Volume Bars */}
      <div className="chart" style={{ height: 320, width: '100%', margin: '8px 0 0', position: 'relative' }}>
        <ResponsiveContainer width="100%" height={320}>
          <ComposedChart data={candles} margin={{ top: 12, right: 18, left: 6, bottom: 22 }}>
            <defs>
              <linearGradient id="marketPriceGrad" x1="0" y1="0" x2="0" y2="1">
                <stop offset="5%" stopColor={fillColor} stopOpacity={0.28} />
                <stop offset="95%" stopColor={fillColor} stopOpacity={0.0} />
              </linearGradient>
            </defs>
            <CartesianGrid stroke="#E2EBF5" strokeDasharray="3 3" vertical={false} />
            <XAxis
              dataKey="time"
              height={22}
              dy={6}
              minTickGap={28}
              tickLine={false}
              axisLine={{ stroke: '#D8E2EF' }}
              stroke="#7D8BA5"
              fontSize={10}
              tickFormatter={(t) => (t && t.length >= 10 ? t.slice(5) : t)}
            />
            <YAxis
              yAxisId="price"
              domain={yDomain}
              tickLine={false}
              axisLine={false}
              stroke="#7D8BA5"
              fontSize={10}
              tickFormatter={(v) => money(Number(v))}
              width={75}
            />
            <YAxis
              yAxisId="vol"
              domain={volDomain}
              orientation="right"
              hide={true}
            />
            <Tooltip content={<CustomTooltip />} />
            <Bar
              yAxisId="vol"
              dataKey="volume"
              fill={isUp ? 'rgba(16, 185, 129, 0.22)' : 'rgba(239, 68, 68, 0.22)'}
              radius={[2, 2, 0, 0]}
              isAnimationActive={false}
            />
            <Area
              yAxisId="price"
              type="monotone"
              dataKey="price"
              stroke={strokeColor}
              strokeWidth={2}
              fill="url(#marketPriceGrad)"
              isAnimationActive={false}
            />
          </ComposedChart>
        </ResponsiveContainer>
      </div>
    </div>
  );
}

type AgentPerformanceMode = 'outcomes' | 'latency';

function AgentPerformancePanel({ onNavigateAgentCenter }: { onNavigateAgentCenter?: () => void }) {
  const [runs, setRuns] = useState<AgentRunSummary[]>([]);
  const [summary, setSummary] = useState<any>(null);
  const [chartMode, setChartMode] = useState<AgentPerformanceMode>('outcomes');
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  const loadData = async () => {
    try {
      setLoading(true);
      setError(null);
      const [runsData, summaryData] = await Promise.all([
        api.getAgentRuns(15),
        api.getEvaluationSummary().catch(() => null),
      ]);
      setRuns(runsData || []);
      setSummary(summaryData || null);
    } catch (err: any) {
      console.error('Failed to load agent runs for overview:', err);
      setError(err?.message || 'Failed to fetch agent evaluation runs');
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => {
    loadData();
  }, []);

  // Compute metrics from real persisted runs & summary
  const totalEvaluatedRuns = summary?.total_runs ?? runs.length;
  const completedRuns = summary?.completed_runs ?? runs.filter(r => r.status === 'COMPLETED').length;

  const avgScore = summary?.average_score != null
    ? summary.average_score
    : runs.length > 0
    ? (runs.reduce((acc, r) => acc + (r.overall_score || 0), 0) / runs.length)
    : 0;

  const totalFindings = summary?.total_findings_count != null
    ? summary.total_findings_count
    : runs.reduce((acc, r) => acc + (r.findings_count || 0), 0);

  const avgLatencySec = summary?.average_latency_ms
    ? summary.average_latency_ms / 1000
    : runs.length > 0
    ? (runs.reduce((acc, r) => acc + (r.total_latency_ms || 0), 0) / runs.length) / 1000
    : 0;

  const p95LatencySec = summary?.p95_latency_ms
    ? summary.p95_latency_ms / 1000
    : avgLatencySec;

  // Chronological sorting for the chart: oldest first
  const sortedRuns = [...runs].sort(
    (a, b) => new Date(a.created_at).getTime() - new Date(b.created_at).getTime()
  );

  const chartData = sortedRuns.map((r, idx) => {
    const dateObj = new Date(r.created_at);
    const timeLabel = isNaN(dateObj.getTime())
      ? `Run ${idx + 1}`
      : dateObj.toLocaleTimeString([], { hour: '2-digit', minute: '2-digit', second: '2-digit' });
    const dateLabel = isNaN(dateObj.getTime())
      ? ''
      : dateObj.toLocaleDateString([], { month: 'short', day: 'numeric' });
    const totalLatencySec = Number(((r.total_latency_ms || 0) / 1000).toFixed(2));
    const execLatencySec = Number(((r.executor_latency_ms || 0) / 1000).toFixed(2));
    const revLatencySec = Number(((r.reviewer_latency_ms || 0) / 1000).toFixed(2));
    const objectivePass = r.objective_pass_pct != null
      ? r.objective_pass_pct
      : (r.review_verdict === 'PASS' ? 100 : 0);

    return {
      run_id: r.run_id,
      displayLabel: `${r.symbol || 'RUN'} (${timeLabel})`,
      shortLabel: timeLabel,
      fullTime: `${dateLabel} ${timeLabel}`.trim(),
      symbol: r.symbol,
      task_type: r.task_type,
      status: r.status,
      review_verdict: r.review_verdict,
      overall_score: r.overall_score ?? 0,
      objective_pass_pct: objectivePass,
      findings_count: r.findings_count || 0,
      total_latency_sec: totalLatencySec,
      executor_latency_sec: execLatencySec,
      reviewer_latency_sec: revLatencySec,
    };
  });

  return (
    <div>
      <div className="card-title" style={{ alignItems: 'flex-start', flexWrap: 'wrap', gap: '12px' }}>
        <div>
          <div style={{ display: 'flex', alignItems: 'center', gap: '8px' }}>
            <BrainCircuit style={{ width: 18, height: 18, color: '#3b82f6' }} />
            <h2 style={{ margin: 0, fontSize: '15px' }}>Agent Performance & Evaluation</h2>
          </div>
          <p style={{ margin: '3px 0 0', fontSize: '12px', color: 'var(--hive-ui-muted-secondary, #6b7796)' }}>
            {chartMode === 'outcomes' && 'Gemma qualitative rubric review score (0-100 pts) and audit verdicts'}
            {chartMode === 'latency' && 'Execution and review turnaround latency in seconds'}
          </p>
        </div>
        <div className="segmented" style={{ display: 'flex', gap: '2px' }}>
          <button
            className={chartMode === 'outcomes' ? 'selected' : ''}
            onClick={() => setChartMode('outcomes')}
            title="Gemma qualitative review score (0-100 pts) and verdicts"
          >
            Reviewer Scores & Verdicts
          </button>
          <button
            className={chartMode === 'latency' ? 'selected' : ''}
            onClick={() => setChartMode('latency')}
            title="Qwen execution and Gemma review latency in seconds"
          >
            Latency (s)
          </button>
        </div>
      </div>

      {/* Mini KPI Strip */}
      <div style={{
        display: 'grid',
        gridTemplateColumns: 'repeat(auto-fit, minmax(130px, 1fr))',
        gap: '10px',
        marginTop: '14px',
        marginBottom: '10px',
        padding: '8px 12px',
        background: 'rgba(243, 246, 251, 0.75)',
        border: '1px solid var(--hive-border, #D8E2EF)',
        borderRadius: '10px'
      }}>
        <div>
          <span style={{ fontSize: '10px', textTransform: 'uppercase', letterSpacing: '0.5px', color: 'var(--hive-text-secondary, #5E6F8F)', display: 'block' }}>
            Evaluated Runs
          </span>
          <strong style={{ fontSize: '16px', fontWeight: 700, color: 'var(--hive-text-primary, #0B1730)', fontVariantNumeric: 'tabular-nums' }}>
            {totalEvaluatedRuns}
          </strong>
          <span style={{ fontSize: '10px', color: 'var(--hive-text-muted, #7D8BA5)', display: 'block' }}>
            {completedRuns} completed
          </span>
        </div>
        <div>
          <span style={{ fontSize: '10px', textTransform: 'uppercase', letterSpacing: '0.5px', color: 'var(--hive-text-secondary, #5E6F8F)', display: 'block' }}>
            Avg Review Score
          </span>
          <strong style={{
            fontSize: '16px',
            fontWeight: 700,
            fontVariantNumeric: 'tabular-nums',
            color: avgScore >= 80 ? 'var(--hive-success, #168568)' : avgScore >= 60 ? 'var(--hive-warning, #B7791F)' : 'var(--hive-error, #C84D5B)'
          }}>
            {avgScore.toFixed(0)} pts
          </strong>
          <span style={{ fontSize: '10px', color: 'var(--hive-text-muted, #7D8BA5)', display: 'block' }}>
            Gemma 3 Rubric
          </span>
        </div>
        <div>
          <span style={{ fontSize: '10px', textTransform: 'uppercase', letterSpacing: '0.5px', color: 'var(--hive-text-secondary, #5E6F8F)', display: 'block' }}>
            Open Findings
          </span>
          <strong style={{
            fontSize: '16px',
            fontWeight: 700,
            fontVariantNumeric: 'tabular-nums',
            color: totalFindings > 0 ? 'var(--hive-warning, #B7791F)' : 'var(--hive-success, #168568)'
          }}>
            {totalFindings}
          </strong>
          <span style={{ fontSize: '10px', color: 'var(--hive-text-muted, #7D8BA5)', display: 'block' }}>
            Qualitative critique
          </span>
        </div>
        <div>
          <span style={{ fontSize: '10px', textTransform: 'uppercase', letterSpacing: '0.5px', color: 'var(--hive-text-secondary, #5E6F8F)', display: 'block' }}>
            Avg Latency
          </span>
          <strong style={{ fontSize: '16px', fontWeight: 700, color: 'var(--hive-blue-accent, #4B7FBD)', fontVariantNumeric: 'tabular-nums' }}>
            {avgLatencySec.toFixed(1)}s
          </strong>
          <span style={{ fontSize: '10px', color: 'var(--hive-text-muted, #7D8BA5)', display: 'block' }}>
            P95: {p95LatencySec.toFixed(1)}s
          </span>
        </div>
      </div>

      {/* Main Chart Area */}
      <div className="chart" style={{ height: '220px', position: 'relative' }}>
        {loading ? (
          <div style={{ height: '100%', display: 'flex', flexDirection: 'column', alignItems: 'center', justifyContent: 'center', gap: 10, color: 'var(--hive-text-secondary, #5E6F8F)' }}>
            <Activity className="spin" style={{ width: 24, height: 24, color: 'var(--hive-blue-accent, #4B7FBD)' }} />
            <span style={{ fontSize: '12px' }}>Loading evaluated agent runs...</span>
          </div>
        ) : error ? (
          <div style={{
            height: '100%',
            display: 'flex',
            flexDirection: 'column',
            alignItems: 'center',
            justifyContent: 'center',
            textAlign: 'center',
            padding: '16px',
            background: 'rgba(200, 77, 91, 0.06)',
            borderRadius: '10px',
            border: '1px dashed rgba(200, 77, 91, 0.35)'
          }}>
            <AlertTriangle style={{ width: 28, height: 28, color: 'var(--hive-error, #C84D5B)', marginBottom: 6 }} />
            <strong style={{ fontSize: '13px', color: 'var(--hive-error, #C84D5B)', marginBottom: 4 }}>
              Failed to load agent evaluation records
            </strong>
            <p style={{ fontSize: '11px', color: 'var(--hive-text-secondary, #5E6F8F)', margin: '0 0 10px', maxWidth: 380 }}>
              {error}
            </p>
            <button
              onClick={loadData}
              style={{
                display: 'inline-flex',
                alignItems: 'center',
                gap: '6px',
                padding: '6px 12px',
                borderRadius: '6px',
                background: 'rgba(255, 255, 255, 0.85)',
                border: '1px solid var(--hive-border, #D8E2EF)',
                color: 'var(--hive-text-primary, #0B1730)',
                fontSize: '11px',
                cursor: 'pointer',
                boxShadow: 'var(--hive-shadow-sm, 0 1px 3px rgba(14, 28, 61, 0.05))'
              }}
            >
              <RotateCcw style={{ width: 12, height: 12 }} /> Retry
            </button>
          </div>
        ) : chartData.length === 0 ? (
          <div style={{
            height: '100%',
            display: 'flex',
            flexDirection: 'column',
            alignItems: 'center',
            justifyContent: 'center',
            textAlign: 'center',
            padding: '20px',
            background: 'rgba(243, 246, 251, 0.5)',
            borderRadius: '10px',
            border: '1px dashed var(--hive-border, #D8E2EF)'
          }}>
            <Sparkles style={{ width: 28, height: 28, color: 'var(--hive-blue-accent, #4B7FBD)', marginBottom: 6 }} />
            <strong style={{ fontSize: '14px', color: 'var(--hive-text-primary, #0B1730)', marginBottom: 4 }}>
              No evaluations recorded yet
            </strong>
            <p style={{ fontSize: '11px', color: 'var(--hive-text-secondary, #5E6F8F)', maxWidth: 360, margin: '0 0 12px' }}>
              Execute an AI review loop in the Agent Center to generate Qwen executions and Gemma review audits.
            </p>
            {onNavigateAgentCenter && (
              <button
                className="primary"
                onClick={onNavigateAgentCenter}
                style={{ fontSize: '11px', padding: '6px 12px' }}
              >
                <BrainCircuit style={{ width: 14, height: 14 }} /> Open Agent Center
              </button>
            )}
          </div>
        ) : (
          <ResponsiveContainer width="100%" height="100%">
            <AreaChart data={chartData} margin={{ top: 10, right: 18, left: -10, bottom: 0 }}>
              <defs>
                <linearGradient id="evalEmeraldGrad" x1="0" y1="0" x2="0" y2="1">
                  <stop offset="5%" stopColor="#168568" stopOpacity={0.28}/>
                  <stop offset="95%" stopColor="#168568" stopOpacity={0.0}/>
                </linearGradient>
                <linearGradient id="evalBlueGrad" x1="0" y1="0" x2="0" y2="1">
                  <stop offset="5%" stopColor="#1B3A6B" stopOpacity={0.24}/>
                  <stop offset="95%" stopColor="#1B3A6B" stopOpacity={0.0}/>
                </linearGradient>
                <linearGradient id="evalSkyGrad" x1="0" y1="0" x2="0" y2="1">
                  <stop offset="5%" stopColor="#4B7FBD" stopOpacity={0.26}/>
                  <stop offset="95%" stopColor="#4B7FBD" stopOpacity={0.0}/>
                </linearGradient>
              </defs>
              <CartesianGrid stroke="#E2EBF5" strokeDasharray="3 3" vertical={false}/>
              <XAxis
                dataKey="shortLabel"
                tickLine={false}
                axisLine={false}
                stroke="#7D8BA5"
                fontSize={10}
              />
              <YAxis
                domain={chartMode === 'latency' ? [0, 'auto'] : [0, 100]}
                ticks={chartMode === 'latency' ? undefined : [0, 25, 50, 75, 100]}
                tickLine={false}
                axisLine={false}
                stroke="#7D8BA5"
                fontSize={10}
                tickFormatter={(v) => (chartMode === 'latency' ? `${v}s` : chartMode === 'outcomes' ? `${v} pts` : `${v}%`)}
                width={55}
              />
              <Tooltip
                content={({ active, payload }) => {
                  if (!active || !payload || !payload.length) return null;
                  const d = payload[0].payload;
                  return (
                    <div style={{
                      background: 'rgba(255, 255, 255, 0.96)',
                      border: '1px solid var(--hive-border, #D8E2EF)',
                      borderRadius: 10,
                      padding: '10px 14px',
                      color: 'var(--hive-text-primary, #0B1730)',
                      fontSize: '11px',
                      boxShadow: 'var(--hive-shadow-md, 0 8px 28px rgba(31, 53, 87, 0.08))',
                      minWidth: 230,
                    }}>
                      <div style={{
                        display: 'flex',
                        justifyContent: 'space-between',
                        alignItems: 'center',
                        marginBottom: 6,
                        borderBottom: '1px solid #EAF0F8',
                        paddingBottom: 4
                      }}>
                        <b style={{ color: 'var(--hive-navy-mid, #1B3A6B)' }}>{d.symbol || 'AGENT RUN'}</b>
                        <span style={{ color: 'var(--hive-text-muted, #7D8BA5)', fontSize: '10px', fontVariantNumeric: 'tabular-nums' }}>{d.fullTime}</span>
                      </div>
                      <div style={{ fontSize: '9px', color: 'var(--hive-text-secondary, #5E6F8F)', marginBottom: 6, fontFamily: 'monospace' }}>
                        {d.run_id}
                      </div>
                      <div style={{ display: 'grid', gridTemplateColumns: '1fr auto', gap: '4px', marginBottom: 4 }}>
                        <span style={{ color: 'var(--hive-text-secondary, #5E6F8F)' }}>Execution Status:</span>
                        <b style={{ color: d.status === 'COMPLETED' ? 'var(--hive-success, #168568)' : 'var(--hive-error, #C84D5B)', fontVariantNumeric: 'tabular-nums' }}>
                          {d.status}
                        </b>
                      </div>
                      <div style={{ display: 'grid', gridTemplateColumns: '1fr auto', gap: '4px', marginBottom: 4 }}>
                        <span style={{ color: 'var(--hive-text-secondary, #5E6F8F)' }}>Objective Checks:</span>
                        <b style={{ color: d.objective_pass_pct >= 80 ? 'var(--hive-success, #168568)' : d.objective_pass_pct >= 50 ? 'var(--hive-warning, #B7791F)' : 'var(--hive-error, #C84D5B)', fontVariantNumeric: 'tabular-nums' }}>
                          {d.objective_pass_pct}% Pass (Deterministic)
                        </b>
                      </div>
                      <div style={{ display: 'grid', gridTemplateColumns: '1fr auto', gap: '4px', marginBottom: 4 }}>
                        <span style={{ color: 'var(--hive-text-secondary, #5E6F8F)' }}>Reviewer Verdict:</span>
                        <b style={{ color: d.review_verdict === 'PASS' ? 'var(--hive-success, #168568)' : d.review_verdict === 'FLAG' ? 'var(--hive-warning, #B7791F)' : 'var(--hive-error, #C84D5B)', fontVariantNumeric: 'tabular-nums' }}>
                          {d.review_verdict} ({d.overall_score} pts)
                        </b>
                      </div>
                      <div style={{ display: 'grid', gridTemplateColumns: '1fr auto', gap: '4px', marginBottom: 4 }}>
                        <span style={{ color: 'var(--hive-text-secondary, #5E6F8F)' }}>Review Findings:</span>
                        <b style={{ color: d.findings_count > 0 ? 'var(--hive-warning, #B7791F)' : 'var(--hive-success, #168568)', fontVariantNumeric: 'tabular-nums' }}>
                          {d.findings_count} item{d.findings_count === 1 ? '' : 's'}
                        </b>
                      </div>
                      <div style={{ display: 'grid', gridTemplateColumns: '1fr auto', gap: '4px' }}>
                        <span style={{ color: 'var(--hive-text-secondary, #5E6F8F)' }}>Total Latency:</span>
                        <b style={{ color: 'var(--hive-blue-accent, #4B7FBD)', fontVariantNumeric: 'tabular-nums' }}>{d.total_latency_sec}s</b>
                      </div>
                      {(d.executor_latency_sec > 0 || d.reviewer_latency_sec > 0) && (
                        <div style={{ fontSize: '9px', color: 'var(--hive-text-muted, #7D8BA5)', marginTop: 4, textAlign: 'right', fontVariantNumeric: 'tabular-nums' }}>
                          Qwen: {d.executor_latency_sec}s · Gemma: {d.reviewer_latency_sec}s
                        </div>
                      )}
                    </div>
                  );
                }}
              />
              {chartMode === 'outcomes' && (
                <Area
                  type="monotone"
                  dataKey="overall_score"
                  stroke="#1B3A6B"
                  strokeWidth={2}
                  fill="url(#evalBlueGrad)"
                  dot={{ r: 3, fill: '#1B3A6B', strokeWidth: 1, stroke: '#ffffff' }}
                  activeDot={{ r: 5, fill: '#1B3A6B', strokeWidth: 2, stroke: '#ffffff' }}
                />
              )}
              {chartMode === 'latency' && (
                <Area
                  type="monotone"
                  dataKey="total_latency_sec"
                  stroke="#4B7FBD"
                  strokeWidth={2}
                  fill="url(#evalSkyGrad)"
                  dot={{ r: 3, fill: '#4B7FBD', strokeWidth: 1, stroke: '#ffffff' }}
                  activeDot={{ r: 5, fill: '#4B7FBD', strokeWidth: 2, stroke: '#ffffff' }}
                />
              )}
            </AreaChart>
          </ResponsiveContainer>
        )}
      </div>
    </div>
  );
}

function Overview({
  equity,
  cash,



  quotes,
  events,
  running,

  agents,
  onNavigateAgentCenter,
}: {
  equity: number;
  cash: number;
  invested: number;
  positions: Position[];
  prices: Record<string, number | null>;
  quotes: Quote[];
  events: Event[];
  running: boolean;
  goMarket: (s?: Scenario) => void;
  agents: AgentCardData[];
  onNavigateAgentCenter?: () => void;
}) {
  const pnl = equity - 1000000;
  const [activeAgentIndex, setActiveAgentIndex] = useState(0);
  const recentEvents = events;
  const agentCount = agents.length;
  const currentAgent = agentCount ? agents[activeAgentIndex % agentCount] : null;

  const navigateAgent = (direction: number) => {
    if (agentCount) {
      setActiveAgentIndex(index => (index + direction + agentCount) % agentCount);
    }
  };

  return (
    <>
      <div className="metrics">
        <Metric label="Portfolio Equity" value={money(equity)} note="Cash + marked positions"/>
        <Metric label="Total P&L" value={money(pnl)} note={pct((pnl / 1e6) * 100)} positive={pnl >= 0}/>
        <Metric label="Available Cash" value={money(cash)} note="Available for simulated orders"/>
        <Metric label="Risk Status" value="Guarded" note="Risk gate active"/>
      </div>

      <div className="overview-grid">
        <Card className="performance">
          <AgentPerformancePanel onNavigateAgentCenter={onNavigateAgentCenter} />
        </Card>

        <Card className="watch">
          <div className="card-title">
            <div>
              <h2>Market Watchlist</h2>
              <p>0xramm Indian Stock Market API • NSE Equities</p>
            </div>
          </div>
          {quotes.slice(0, 8).map((q) => {
            const hasPrice = q.price !== null && q.price !== undefined;
            const priceTypeLabel = q.price_type === 'OFFICIAL_SESSION_CLOSE'
              ? 'Official Close'
              : q.price_type === 'LAST_SESSION_CLOSE'
              ? 'Session Close'
              : q.price_type === 'LAST_OBSERVED_PRICE'
              ? 'Last Observed'
              : (q.is_live ? 'Live' : 'Last Available');

            return (
              <div className="watch-row" key={q.symbol}>
                <div>
                  <b>{q.symbol}</b>
                  <span style={{
                    fontSize: '9px',
                    marginLeft: '6px',
                    padding: '2px 5px',
                    borderRadius: '4px',
                    background: q.is_live ? 'rgba(16, 185, 129, 0.12)' : 'rgba(148, 163, 184, 0.14)',
                    color: q.is_live ? '#168568' : '#61718B',
                    fontFamily: 'monospace',
                    whiteSpace: 'nowrap',
                    display: 'inline-block'
                  }}>
                    {q.is_live ? 'LIVE' : 'CLOSED'}
                  </span>
                </div>
                <div style={{ textAlign: 'right' }}>
                  <div style={{ fontWeight: 600, fontSize: '13px' }}>
                    {hasPrice ? money(q.price) : <span style={{ color: '#888', fontSize: '12px' }}>Awaiting data</span>}
                  </div>
                  {hasPrice && (
                    <div style={{ fontSize: '9px', color: '#94a3b8', marginTop: '1px' }}>
                      {priceTypeLabel}
                    </div>
                  )}
                </div>
                {hasPrice && q.change_pct !== null && q.change_pct !== undefined ? (
                  <em className={q.change_pct >= 0 ? 'up' : 'down'}>{pct(q.change_pct)}</em>
                ) : (
                  <em style={{ color: '#888' }}>--</em>
                )}
              </div>
            );
          })}
        </Card>
      </div>

      <div className="activity-layout">
        <Card className="activity-panel agent-activity">
          <div className="card-title">
            <div>
              <h2>Agent activity</h2>
              <p>{running ? 'Workflow running…' : `${agentCount} committee roles active`}</p>
            </div>
            <div className="activity-carousel-controls" aria-label="Agent activity navigation">
              <button type="button" aria-label="Previous agent" disabled={agentCount < 2} onClick={() => navigateAgent(-1)}>
                <ChevronLeft size={16}/>
              </button>
              <span aria-live="polite">{agentCount ? `${(activeAgentIndex % agentCount) + 1} / ${agentCount}` : '0 / 0'}</span>
              <button type="button" aria-label="Next agent" disabled={agentCount < 2} onClick={() => navigateAgent(1)}>
                <ChevronRight size={16}/>
              </button>
            </div>
          </div>
          {currentAgent ? (
            <div className="activity-carousel-slide" key={currentAgent.name}>
              <Agent
                name={currentAgent.name}
                icon={getAgentIcon(currentAgent.name)}
                status={running ? 'Analyzing' : currentAgent.status}
                value={currentAgent.value}
                text={currentAgent.text}
                execution_mode={currentAgent.execution_mode}
              />
            </div>
          ) : (
            <div className="empty">No agent activity available.</div>
          )}
        </Card>

        <Card className="activity-panel recent-activity">
          <div className="card-title">
            <div>
              <h2>Recent activity</h2>
              <p>{recentEvents.length ? `${recentEvents.length} latest simulation events` : 'Simulation event log'}</p>
            </div>
          </div>
          <div className="recent-activity-list" aria-label="Latest simulation activities" tabIndex={0}>
            {recentEvents.length ? (
              recentEvents.map(event => (
                <div className="timeline activity-event" key={event.id}>
                  <span className={'dot ' + event.outcome.toLowerCase()}/>
                  <div>
                    <b>{scenarioCopy[event.type]?.title || event.type} replayed</b>
                    <p>{event.headline}</p>
                  </div>
                  <small>{event.time}</small>
                </div>
              ))
            ) : (
              <div className="timeline activity-event">
                <span className="dot approved"/>
                <div>
                  <b>Simulator initialized</b>
                  <p>Virtual portfolio and verified historical market data ready.</p>
                </div>
                <small>09:30</small>
              </div>
            )}
          </div>
        </Card>
      </div>
    </>
  );
}

function Metric({ label, value, note, positive }: { label: string; value: string; note: string; positive?: boolean }) {
  return (
    <Card className="metric">
      <p>{label}</p>
      <strong className={positive === undefined ? '' : positive ? 'up' : 'down'}>{value}</strong>
      <small>{note}</small>
    </Card>
  );
}

function Agent({
  name,
  icon,
  status,
  value,
  text,
  execution_mode,
}: {
  name: string;
  icon: React.ReactNode;
  status: string;
  value: string;
  text: string;
  execution_mode?: string;
}) {
  const isLlm = execution_mode === 'local_llm';
  return (
    <Card className="agent">
      <div className="agent-head">
        <span className="agent-icon">{icon}</span>
        <div style={{ display: 'flex', gap: '6px', alignItems: 'center' }}>
          {isLlm ? (
            <span className="badge-llm">
              <Cpu size={11}/> LOCAL OLLAMA
            </span>
          ) : execution_mode === 'deterministic_fallback' ? (
            <span className="badge-deterministic">
              <ShieldCheck size={11}/> DETERMINISTIC FALLBACK
            </span>
          ) : null}
          <span className={status === 'Analyzing' ? 'status running' : 'status'}>{status}</span>
        </div>
      </div>
      <h3>{name}</h3>
      <b>{value}</b>
      <p>{text}</p>
    </Card>
  );
}

function MarketLab({
  current,
  scenario,
  setScenario,
  severity,
  setSeverity,
  selected,
  setSelected,
  quotes,
  events,
  running,
  inject,
  onRefresh,
}: {
  current: Quote;
  scenario: Scenario;
  setScenario: (s: Scenario) => void;
  severity: number;
  setSeverity: (n: number) => void;
  selected: string;
  setSelected: (s: string) => void;
  quotes: Quote[];
  events: Event[];
  running: boolean;
  inject: () => void;
  onRefresh?: () => void;
}) {
  return (
    <>
      <DhanWatchlistPanel
        selectedSymbol={selected}
        onSelectSymbol={setSelected}
        onTriggerAnalysis={async (sym) => {
          setSelected(sym);
          if (onRefresh) onRefresh();
        }}
      />
      <div className="lab-grid">
        <Card className="market-chart">
          <div className="card-title">
            <div>
              <span className="eyebrow">PROVISIONAL MARKET FEED (0XRAMM)</span>
              <h2>
                {current.name} <span className="ticker">{current.symbol}</span>
              </h2>
              <div style={{ display: 'flex', alignItems: 'center', gap: '8px', marginTop: '4px', flexWrap: 'wrap' }}>
                {current.price !== null && current.price !== undefined ? (
                  <>
                    <p style={{ margin: 0, fontWeight: 700, fontSize: '18px' }}>
                      {money(current.price)}{' '}
                      {current.previous !== null && current.previous !== undefined && (
                        <em className={current.price >= current.previous ? 'up' : 'down'}>
                          {pct(((current.price - current.previous) / current.previous) * 100)}
                        </em>
                      )}
                    </p>
                    <span style={{
                      fontSize: '10px',
                      padding: '2px 8px',
                      borderRadius: '4px',
                      background: current.is_live ? 'rgba(16, 185, 129, 0.15)' : 'rgba(148, 163, 184, 0.18)',
                      color: current.is_live ? '#34d399' : '#cbd5e1',
                      fontFamily: 'monospace',
                      fontWeight: 600
                    }}>
                      {current.is_live
                        ? 'LIVE'
                        : current.price_type === 'OFFICIAL_SESSION_CLOSE'
                        ? 'MARKET CLOSED — OFFICIAL CLOSE'
                        : 'MARKET CLOSED — LAST SESSION CLOSE'}
                    </span>
                    {current.observation_timestamp && (
                      <span style={{ fontSize: '11px', color: '#94a3b8' }}>
                        Obs: {current.observation_timestamp.slice(0, 16).replace('T', ' ')} UTC
                      </span>
                    )}
                  </>
                ) : (
                  <div style={{ display: 'flex', alignItems: 'center', gap: '6px' }}>
                    <span style={{ fontSize: '15px', fontWeight: 600, color: '#94a3b8' }}>
                      Price Unavailable
                    </span>
                    <span style={{
                      fontSize: '10px',
                      padding: '2px 8px',
                      borderRadius: '4px',
                      background: 'rgba(234, 179, 8, 0.15)',
                      color: '#fbbf24',
                      fontFamily: 'monospace'
                    }}>
                      {current.freshness_status || 'WAITING_FOR_DATA'}
                    </span>
                  </div>
                )}
              </div>
            </div>
            <select value={selected} onChange={e => setSelected(e.target.value)}>
              {quotes.map(q => (
                <option value={q.symbol} key={q.symbol}>
                  {q.symbol} — {q.name}
                </option>
              ))}
            </select>
          </div>
          <MarketPriceChart symbol={selected}/>
        </Card>

        <Card className="scenario-panel">
          <span className="eyebrow">DETERMINISTIC STRESS SIMULATION</span>
          <h2>Market scenario simulation</h2>
          <div className="scenario-grid">
            {canonicalScenarios.map(s => {
              const Icon = scenarioIcons[s] || TrendingDown;
              return (
                <button
                  key={s}
                  className={scenario === s ? 'selected' : ''}
                  onClick={() => setScenario(s)}
                >
                  <span className="scenario-icon">
                    <Icon size={17} strokeWidth={1.8}/>
                  </span>
                  <b>{scenarioCopy[s].title}</b>
                </button>
              );
            })}
          </div>
          <label>
            Severity <b className="severity-value">{severity}%</b>
            <input
              type="range"
              min="10"
              max="100"
              value={severity}
              onChange={e => setSeverity(+e.target.value)}
            />
          </label>
          <div className="scenario-info">
            <b>{scenarioCopy[scenario]?.title || scenario}</b>
            <p>{scenarioCopy[scenario]?.headline || 'Replay market stress scenario.'}</p>
            {!current.is_live && current.price !== null && (
              <span style={{ fontSize: '11px', color: '#94a3b8', display: 'block', marginTop: '6px', fontStyle: 'italic' }}>
                Simulated market event evaluated against verified closing baseline (exchange closed).
              </span>
            )}
          </div>
          <button
            className="primary"
            onClick={inject}
            disabled={running || current.price === null}
            title={current.price === null ? 'Scenario execution requires a verified observation from the 0xramm provisional feed' : undefined}
          >
            <Zap size={14}/>
            {running ? 'Simulating Pipeline...' : 'Replay Scenario'}
          </button>
          {current.price === null && (
            <span style={{ fontSize: '11px', color: '#fbbf24', display: 'block', marginTop: '6px' }}>
              ⚠️ Execution paused: Waiting for verified market price for {selected} (0xramm provisional adapter)
            </span>
          )}
        </Card>
      </div>

      <div className="section-label">
        <h2>Replay history</h2>
        <span>Recent historical scenario runs</span>
      </div>

      <Card>
        {events.length ? (
          events.map(e => (
            <div className="timeline" key={e.id}>
              <span className={'dot ' + e.outcome.toLowerCase()}/>
              <div>
                <b>{scenarioCopy[e.type]?.title || e.type} · Severity {e.severity}%</b>
                <p>{e.headline}</p>
              </div>
              <span className={'badge ' + e.outcome.toLowerCase()}>{e.outcome}</span>
            </div>
          ))
        ) : (
          <div className="empty">No historical scenarios replayed yet. Select a scenario above to test the pipeline.</div>
        )}
      </Card>
    </>
  );
}

function AgentCenter({
  running,
  events,
  orders,
  decisions,
  monitor,
  selected,
  agents,
  onConfirmOrder,
  quotes = [],
  onSelectSymbol,
  feedStatus,
  backendConnected,
}: {
  running: boolean;
  events: Event[];
  orders: Order[];
  decisions: any[];
  monitor: any;
  selected: string;
  agents: AgentCardData[];
  onConfirmOrder: (orderId: number) => void;
  quotes?: Quote[];
  onSelectSymbol?: (symbol: string) => void;
  feedStatus?: string;
  backendConnected?: boolean;
}) {
  return (
    <ReviewCenter
      running={running}
      events={events}
      orders={orders}
      decisions={decisions}
      monitor={monitor}
      selected={selected}
      agents={agents}
      onConfirmOrder={onConfirmOrder}
      quotes={quotes}
      onSelectSymbol={onSelectSymbol}
      feedStatus={feedStatus}
      backendConnected={backendConnected}
    />
  );
}

function Portfolio({
  equity,
  cash,
  invested,
  positions,
  quotes,
  orders,
  allocation,
  settings,
  onRefresh,
}: {
  equity: number;
  cash: number;
  invested: number;
  positions: Position[];
  quotes: Quote[];
  orders: Order[];
  allocation: (s: string, q: number) => number;
  settings: { fee: number; maxOrder: number; maxAllocation: number; drawdown: number };
  onRefresh?: () => void;
}) {
  const [orderLedgerOpen, setOrderLedgerOpen] = useState(false);
  const hasIncompleteValuation = positions.some(p => p.val_status === 'MISSING_LIVE_QUOTE' || p.current_price == null);
  const unrealizedPnl = positions.reduce((s, p) => {
    if (p.unrealized_pnl != null) return s + p.unrealized_pnl;
    const q = quotes.find(x => x.symbol === p.symbol);
    const curPrice = p.current_price ?? (q?.price ?? null);
    if (curPrice == null) return s;
    return s + (curPrice - p.average) * p.qty;
  }, 0);

  useEffect(() => {
    if (!orderLedgerOpen) return;
    const handleKeyDown = (event: KeyboardEvent) => {
      if (event.key === 'Escape') setOrderLedgerOpen(false);
    };
    document.addEventListener('keydown', handleKeyDown);
    return () => document.removeEventListener('keydown', handleKeyDown);
  }, [orderLedgerOpen]);

  const renderOrder = (order: Order) => (
    <div className="timeline" key={order.id}>
      <span className={'dot ' + order.status.toLowerCase()}/>
      <div>
        <b>{order.side} {order.symbol} · {order.executed || order.requested} units</b>
        <p>{order.reason}</p>
      </div>
      <span className={'badge ' + order.status.toLowerCase()}>{order.status}</span>
    </div>
  );

  const isMarkedToClose = positions.length > 0 && positions.some(p => p.val_status && p.val_status !== 'LIVE_MARKED' && p.val_status !== 'LIVE_VALUED');
  const valuationNote = isMarkedToClose ? "Marked to verified last session close" : "Marked to verified live market prices";

  return (
    <>
      <div className="metrics six">
        <Metric label="Portfolio Equity" value={money(equity)} note={valuationNote}/>
        <Metric label="Cash Balance" value={money(cash)} note="Available balance"/>
        <Metric label="Invested Value" value={money(invested)} note="Current holdings"/>
        <Metric
          label="Unrealized P&L"
          value={hasIncompleteValuation ? 'Unavailable' : money(unrealizedPnl)}
          note={hasIncompleteValuation ? 'Awaiting market observation' : (isMarkedToClose ? 'Closing valuation' : 'Open positions')}
          positive={unrealizedPnl >= 0}
        />
        <Metric label="Realized P&L" value="₹0" note="Simulation period"/>
        <Metric label="Drawdown" value="0.00%" note={`Halt at ${settings.drawdown}%`}/>
      </div>

      <Card>
        <div className="card-title">
          <div>
            <h2>Virtual Portfolio Holdings</h2>
            <p>{isMarkedToClose ? "Paper trading positions marked to verified last session close (exchange closed)" : "Paper trading positions marked to verified 0xramm market feed prices"}</p>
          </div>
        </div>
        <div className="table-wrap">
          <table>
            <thead>
              <tr>
                <th>Asset</th>
                <th>Quantity</th>
                <th>Average entry</th>
                <th>Current price</th>
                <th>Market value</th>
                <th>Unrealized P&L</th>
                <th>Allocation</th>
              </tr>
            </thead>
            <tbody>
              {positions.length > 0 ? (
                positions.map(p => {
                  const q = quotes.find(x => x.symbol === p.symbol);
                  const curPrice = p.current_price ?? (q?.price ?? null);
                  const hasValuation = curPrice !== null && p.val_status !== 'VALUATION_UNAVAILABLE';
                  const pl = hasValuation ? (curPrice! - p.average) * p.qty : null;
                  const mktVal = hasValuation ? curPrice! * p.qty : null;
                  return (
                    <tr key={p.symbol}>
                      <td>
                        <b>{p.symbol}</b>
                        <small>{q?.name || p.name || p.symbol}</small>
                        {p.val_status && p.val_status !== 'LIVE_MARKED' && p.val_status !== 'LIVE_VALUED' && (
                          <span style={{ fontSize: '10px', color: '#94a3b8', display: 'block', fontFamily: 'monospace' }}>
                            {p.val_status}
                          </span>
                        )}
                      </td>
                      <td>{p.qty}</td>
                      <td>{money(p.average)}</td>
                      <td>{hasValuation ? money(curPrice) : <span style={{ color: '#888' }}>Unavailable</span>}</td>
                      <td>{hasValuation ? money(mktVal) : <span style={{ color: '#888' }}>Unavailable</span>}</td>
                      <td>
                        {hasValuation && pl !== null ? (
                          <span className={pl >= 0 ? 'up' : 'down'}>{money(pl)}</span>
                        ) : (
                          <span style={{ color: '#888' }}>Unavailable</span>
                        )}
                      </td>
                      <td>{hasValuation ? `${allocation(p.symbol, p.qty).toFixed(1)}%` : '--'}</td>
                    </tr>
                  );
                })
              ) : (
                <tr>
                  <td colSpan={7} style={{ textAlign: 'center', padding: '28px', opacity: 0.65 }}>
                    No active paper positions. Submit simulated orders based on verified provisional 0xramm prices.
                  </td>
                </tr>
              )}
            </tbody>
          </table>
        </div>
      </Card>

      <PaperProposalsPanel onProposalExecuted={onRefresh} />

      <div className="agent-center-grid">
        <Card className="portfolio-risk-card">
          <h2>Risk monitor</h2>
          <RiskBar
            label="Largest position allocation"
            value={positions.length ? Math.max(...positions.map(p => allocation(p.symbol, p.qty))) : 0}
            limit={settings.maxAllocation}
          />
          <RiskBar
            label="Cash utilization"
            value={equity > 0 ? (invested / equity) * 100 : 0}
            limit={100}
          />
          <RiskBar
            label="Current drawdown"
            value={0.0}
            limit={settings.drawdown}
          />
        </Card>

        <Card className="portfolio-order-ledger-card">
          <div className="order-ledger-heading">
            <h2>Order ledger</h2>
            <button
              type="button"
              className="order-ledger-expand"
              aria-haspopup="dialog"
              onClick={() => setOrderLedgerOpen(true)}
            >
              View all ({orders.length})
            </button>
          </div>
          {orders.length ? (
            <div className="order-ledger-preview">
              {orders.slice(0, 3).map(renderOrder)}
            </div>
          ) : (
            <div className="empty">No simulated orders yet.</div>
          )}
        </Card>
      </div>

      {orderLedgerOpen && (
        <div className="modal-backdrop order-ledger-backdrop" onClick={() => setOrderLedgerOpen(false)}>
          <section
            className="modal-dialog order-ledger-dialog"
            role="dialog"
            aria-modal="true"
            aria-labelledby="order-ledger-title"
            onClick={event => event.stopPropagation()}
          >
            <div className="card-title">
              <div>
                <span className="eyebrow">PAPER TRADING HISTORY</span>
                <h2 id="order-ledger-title">Order ledger</h2>
                <p>{orders.length} simulated {orders.length === 1 ? 'order' : 'orders'}</p>
              </div>
              <button
                type="button"
                className="icon-button"
                aria-label="Close order ledger"
                onClick={() => setOrderLedgerOpen(false)}
              >
                <X />
              </button>
            </div>
            <div className="order-ledger-full-list">
              {orders.length ? orders.map(renderOrder) : (
                <div className="empty">No simulated orders yet.</div>
              )}
            </div>
          </section>
        </div>
      )}
    </>
  );
}

function RiskBar({ label, value, limit }: { label: string; value: number; limit: number }) {
  const pc = Math.min(100, (value / limit) * 100);
  return (
    <div className="riskbar">
      <div>
        <b>{label}</b>
        <span>{value.toFixed(1)}% / {limit}%</span>
      </div>
      <i><em style={{ width: `${pc}%` }}/></i>
    </div>
  );
}

function BacktestEquityChart({
  data,
  ran,
  strategy,
  symbol,
}: {
  data: { time: string; equity: number; benchmark: number }[];
  ran: boolean;
  strategy: string;
  symbol: string;
}) {
  if (!ran || !data || data.length === 0) {
    return (
      <div className="chart-empty-state">
        <ChartNoAxesCombined size={32}/>
        <p><b>No backtest executed yet for {symbol}</b></p>
        <span style={{ fontSize: 11, maxWidth: 420, marginTop: 4 }}>
          Select your strategy parameters above and click <b>Run Backtest</b> to compare strategy returns against the buy-and-hold benchmark on verified historical data.
        </span>
      </div>
    );
  }

  return (
    <div className="chart">
      <ResponsiveContainer width="100%" height="100%">
        <ComposedChart data={data} margin={{ top: 10, right: 20, left: 20, bottom: 0 }}>
          <defs>
            <linearGradient id="btStrategyGrad" x1="0" y1="0" x2="0" y2="1">
              <stop offset="5%" stopColor="#168568" stopOpacity={0.28}/>
              <stop offset="95%" stopColor="#168568" stopOpacity={0.0}/>
            </linearGradient>
          </defs>
          <CartesianGrid stroke="#E2EBF5" vertical={false}/>
          <XAxis
            dataKey="time"
            tickLine={false}
            axisLine={false}
            stroke="#7D8BA5"
            fontSize={10}
            tickFormatter={(t) => (t && t.length >= 10 ? t.slice(5) : t)}
          />
          <YAxis
            domain={['auto', 'auto']}
            tickLine={false}
            axisLine={false}
            stroke="#7D8BA5"
            fontSize={10}
            tickFormatter={(v) => money(Number(v))}
            width={80}
          />
          <Tooltip
            contentStyle={{ background: 'rgba(255, 255, 255, 0.96)', border: '1px solid var(--hive-border, #D8E2EF)', borderRadius: 10, color: 'var(--hive-text-primary, #0B1730)', fontSize: 11, boxShadow: 'var(--hive-shadow-md, 0 8px 24px rgba(31, 53, 87, 0.08))' }}
            formatter={(v: any, name: string) => [money(Number(v)), name]}
            labelFormatter={(label) => `Date: ${label}`}
          />
          <Legend verticalAlign="top" height={36} wrapperStyle={{ fontSize: '11px', color: 'var(--hive-text-secondary, #5E6F8F)' }}/>
          <Area
            type="monotone"
            dataKey="equity"
            isAnimationActive={false}
            stroke="#168568"
            strokeWidth={2}
            fill="url(#btStrategyGrad)"
            name={`${strategy} Equity`}
          />
          <Line
            type="monotone"
            dataKey="benchmark"
            isAnimationActive={false}
            stroke="#4B7FBD"
            strokeDasharray="4 4"
            dot={false}
            strokeWidth={2}
            name="Buy & Hold Benchmark"
          />
        </ComposedChart>
      </ResponsiveContainer>
    </div>
  );
}

function TradeLedgerTable({ trades }: { trades: any[] }) {
  if (!trades || trades.length === 0) {
    return (
      <div style={{ textAlign: 'center', padding: '24px 16px', color: 'var(--text-muted, #888)', fontSize: 12 }}>
        No closed trades generated for this strategy/parameter configuration.
      </div>
    );
  }

  return (
    <div className="table-wrapper" style={{ overflowX: 'auto', marginTop: 12 }}>
      <table className="trade-ledger-table tabular-nums" style={{ width: '100%', borderCollapse: 'collapse', fontSize: 12 }}>
        <thead>
          <tr style={{ borderBottom: '1px solid var(--hive-border, #D8E2EF)', textAlign: 'left', color: 'var(--hive-text-secondary, #5E6F8F)' }}>
            <th style={{ padding: '8px 12px' }}>#</th>
            <th style={{ padding: '8px 12px' }}>Side</th>
            <th style={{ padding: '8px 12px' }}>Qty</th>
            <th style={{ padding: '8px 12px' }}>Entry Date</th>
            <th style={{ padding: '8px 12px' }}>Entry Price</th>
            <th style={{ padding: '8px 12px' }}>Exit Date</th>
            <th style={{ padding: '8px 12px' }}>Exit Price</th>
            <th style={{ padding: '8px 12px', textAlign: 'right' }}>PnL (₹)</th>
            <th style={{ padding: '8px 12px', textAlign: 'right' }}>PnL (%)</th>
            <th style={{ padding: '8px 12px', textAlign: 'center' }}>Outcome</th>
          </tr>
        </thead>
        <tbody>
          {trades.map((t) => {
            const isWin = t.pnl > 0;
            return (
              <tr key={t.id} style={{ borderBottom: '1px solid var(--hive-border-subtle, #EAF0F8)' }}>
                <td style={{ padding: '8px 12px', color: 'var(--hive-text-muted, #7D8BA5)' }}>{t.id}</td>
                <td style={{ padding: '8px 12px' }}>
                  <span className="badge" style={{ fontSize: 10, padding: '2px 6px', background: 'rgba(75, 127, 189, 0.12)', color: 'var(--hive-blue-accent, #4B7FBD)' }}>
                    {t.side}
                  </span>
                </td>
                <td style={{ padding: '8px 12px', fontWeight: 600, color: 'var(--hive-text-primary, #0B1730)' }}>{t.quantity}</td>
                <td style={{ padding: '8px 12px', color: 'var(--hive-text-secondary, #5E6F8F)' }}>{t.entry_time}</td>
                <td style={{ padding: '8px 12px', color: 'var(--hive-text-primary, #0B1730)' }}>₹{t.entry_price.toLocaleString('en-IN', { minimumFractionDigits: 2 })}</td>
                <td style={{ padding: '8px 12px', color: 'var(--hive-text-secondary, #5E6F8F)' }}>{t.exit_time}</td>
                <td style={{ padding: '8px 12px', color: 'var(--hive-text-primary, #0B1730)' }}>₹{t.exit_price.toLocaleString('en-IN', { minimumFractionDigits: 2 })}</td>
                <td style={{ padding: '8px 12px', textAlign: 'right', fontWeight: 600, color: isWin ? 'var(--hive-success, #168568)' : 'var(--hive-error, #C84D5B)' }}>
                  {isWin ? '+' : ''}₹{t.pnl.toLocaleString('en-IN', { minimumFractionDigits: 2 })}
                </td>
                <td style={{ padding: '8px 12px', textAlign: 'right', fontWeight: 600, color: isWin ? 'var(--hive-success, #168568)' : 'var(--hive-error, #C84D5B)' }}>
                  {isWin ? '+' : ''}{t.pnl_pct.toFixed(2)}%
                </td>
                <td style={{ padding: '8px 12px', textAlign: 'center' }}>
                  <span className={`badge ${isWin ? 'badge-validated' : 'badge-warnings'}`} style={{ fontSize: 10, padding: '2px 8px' }}>
                    {t.status}
                  </span>
                </td>
              </tr>
            );
          })}
        </tbody>
      </table>
    </div>
  );
}

function Backtest() {
  const [ran, setRan] = useState(false);
  const [strategy, setStrategy] = useState('SMA crossover');
  const [datasets, setDatasets] = useState<DatasetRecord[]>([]);
  const [selectedDatasetId, setSelectedDatasetId] = useState<string>('');
  const [capital, setCapital] = useState(1000000);
  const [rsiOversold, setRsiOversold] = useState(35);
  const [rsiOverbought, setRsiOverbought] = useState(65);
  const [loading, setLoading] = useState(false);
  const [errorMsg, setErrorMsg] = useState<string | null>(null);
  const [importModalOpen, setImportModalOpen] = useState(false);
  const [downloadModalOpen, setDownloadModalOpen] = useState(false);
  const [btData, setBtData] = useState<{
    total_return_pct: number;
    max_drawdown_pct: number;
    trade_count: number;
    win_rate_pct: number;
    sharpe_ratio: number;
    profit_factor: number;
    notes?: string;
    observation_count?: number;
    raw_candle_count?: number;
    non_trading_artifacts_excluded_count?: number;
    date_range?: { start_date?: string; end_date?: string };
    equity_curve: { time: string; benchmark: number; equity: number }[];
    trades?: any[];
  } | null>(null);

  const loadDatasets = useCallback(async () => {
    try {
      const datasets = await api.getDatasets();
      setDatasets(datasets);
      setSelectedDatasetId(current =>
        datasets.some(dataset => dataset.id === current) ? current : (datasets[0]?.id ?? ''),
      );
    } catch (error) {
      setErrorMsg(error instanceof Error ? error.message : 'Could not load historical datasets.');
    }
  }, []);

  useEffect(() => {
    void loadDatasets();
  }, [loadDatasets]);

  const activeDataset = datasets.find(d => d.id === selectedDatasetId) || datasets[0];

  const handleDatasetChange = (id: string) => {
    setSelectedDatasetId(id);
    setRan(false);
    setBtData(null);
  };

  const handleStrategyChange = (strat: string) => {
    setStrategy(strat);
    setRan(false);
    setBtData(null);
  };

  const runBt = async () => {
    setLoading(true);
    setErrorMsg(null);
    try {
      const activeSym = activeDataset?.symbol || 'RELIANCE';
      const res = await api.runBacktest({
        strategy,
        symbol: activeSym,
        timeframe: '1d',
        starting_capital: capital,
        rsi_oversold: rsiOversold,
        rsi_overbought: rsiOverbought,
        data_source: 'historical',
        dataset_id: activeDataset?.id,
      });

      setBtData({
        total_return_pct: res.total_return_pct,
        max_drawdown_pct: res.max_drawdown_pct,
        trade_count: res.trade_count,
        win_rate_pct: res.win_rate_pct,
        sharpe_ratio: res.sharpe_ratio,
        profit_factor: res.profit_factor,
        notes: res.notes,
        observation_count: res.observation_count,
        raw_candle_count: res.raw_candle_count,
        non_trading_artifacts_excluded_count: res.non_trading_artifacts_excluded_count,
        date_range: res.date_range,
        equity_curve: res.equity_curve.map(pt => ({ time: pt.time, benchmark: pt.benchmark, equity: pt.equity })),
        trades: res.trades || [],
      });
      setRan(true);
    } catch (err: any) {
      setErrorMsg(err.message || 'Backtest failed. Ensure historical candles are available.');
      setRan(false);
    } finally {
      setLoading(false);
    }
  };

  return (
    <>
      <div className="dataset-header-row">
        <div style={{ display: 'flex', alignItems: 'center', gap: '8px' }}>
          <span className="badge badge-validated">
            <Database size={13} style={{ marginRight: 5, verticalAlign: 'middle' }}/>
            Verified Historical Datasets (NSE)
          </span>
          <span className="badge" style={{ background: 'rgba(99, 102, 241, 0.15)', color: '#818cf8', border: '1px solid rgba(99, 102, 241, 0.3)' }}>
            MODE: HISTORICAL_RESEARCH
          </span>
        </div>

        <div style={{ display: 'flex', gap: '8px' }}>
          <button className="btn-secondary" onClick={() => setImportModalOpen(true)}>
            <Upload size={13} style={{ marginRight: 5, verticalAlign: 'middle' }}/>
            Import CSV
          </button>
          <button className="btn-secondary" onClick={() => setDownloadModalOpen(true)}>
            <Download size={13} style={{ marginRight: 5, verticalAlign: 'middle' }}/>
            Fetch Online (yfinance)
          </button>
        </div>
      </div>

      {datasets.length === 0 && (
        <Card className="dataset-meta-card" style={{ textAlign: 'center', padding: '36px 20px', border: '1px dashed rgba(255, 255, 255, 0.15)' }}>
          <Database size={42} style={{ opacity: 0.5, marginBottom: 12 }} />
          <h3>No Historical Datasets Registered</h3>
          <p style={{ maxWidth: 520, margin: '8px auto 20px', color: 'var(--text-muted, #888)', fontSize: 13, lineHeight: 1.5 }}>
            Backtest Studio strictly isolates historical research from live quotes to prevent simulation bias and market pollution. Import an official NSE daily CSV or fetch a historical dataset via Yahoo Finance.
          </p>
          <div style={{ display: 'flex', gap: '12px', justifyContent: 'center' }}>
            <button className="primary" onClick={() => setImportModalOpen(true)}>
              <Upload size={14} style={{ marginRight: 6 }}/> Import Historical CSV
            </button>
            <button className="btn-secondary" onClick={() => setDownloadModalOpen(true)}>
              <Download size={14} style={{ marginRight: 6 }}/> Fetch via yfinance
            </button>
          </div>
        </Card>
      )}

      {activeDataset && (
        <Card className="dataset-meta-card">
          <div className="card-title">
            <div>
              <span className="eyebrow">ACTIVE HISTORICAL DATASET</span>
              <h2>{activeDataset.name} ({activeDataset.symbol})</h2>
              <p>{activeDataset.asset_name || activeDataset.symbol} · {activeDataset.exchange} Exchange</p>
            </div>
            <div style={{ display: 'flex', gap: '6px', alignItems: 'center' }}>
              <span className={`badge ${activeDataset.quality_status === 'VALIDATED' ? 'badge-validated' : 'badge-warnings'}`}>
                <CheckCircle2 size={12}/> {activeDataset.quality_status}
              </span>
              <span className="badge badge-unadjusted">
                {activeDataset.adjustment_status}
              </span>
            </div>
          </div>

          <div className="meta-grid">
            <div className="meta-item">
              <small>Candle Interval</small>
              <strong>{activeDataset.timeframe.toUpperCase()} (Daily)</strong>
            </div>
            <div className="meta-item">
              <small>Valid Candles</small>
              <strong>{activeDataset.candle_count} bars</strong>
            </div>
            <div className="meta-item">
              <small>Date Coverage</small>
              <strong>
                {activeDataset.start_date.slice(0, 10)} → {activeDataset.end_date.slice(0, 10)}
              </strong>
            </div>
            <div className="meta-item">
              <small>Data Source</small>
              <strong>{activeDataset.source}</strong>
            </div>
          </div>

          <div className="provenance-box">
            <b>Provenance:</b> {activeDataset.provenance} · <b>License:</b> {activeDataset.license_info}
          </div>

          {activeDataset.validation_report?.warnings && activeDataset.validation_report.warnings.length > 0 && (
            <div className="warning-callout">
              <AlertTriangle size={13} style={{ marginRight: 6, verticalAlign: 'middle' }}/>
              <b>Quality Notices:</b> {activeDataset.validation_report.warnings.join(' · ')}
            </div>
          )}
        </Card>
      )}

      {errorMsg && (
        <div className="error-callout">
          <AlertTriangle size={16}/>
          <div>
            <b>Historical Backtest Error:</b> {errorMsg}
            <div style={{ fontSize: 11, opacity: 0.85, marginTop: 2 }}>
              HIVE strictly preserves simulation honesty and never silently substitutes synthetic data for a requested historical test.
            </div>
          </div>
        </div>
      )}

      <Card className="backtest-controls">
        <div>
          <span className="eyebrow">HISTORICAL QUANTITATIVE BACKTEST (NSE)</span>
          <h2>{strategy} ({activeDataset?.symbol || 'RELIANCE'})</h2>
        </div>

        <select
          value={selectedDatasetId}
          onChange={e => handleDatasetChange(e.target.value)}
          aria-label="Select historical dataset"
        >
          {datasets.map(d => (
            <option value={d.id} key={d.id}>
              {d.symbol} — {d.name} ({d.candle_count} bars)
            </option>
          ))}
        </select>

        <select value={strategy} onChange={e => handleStrategyChange(e.target.value)}>
          <option>SMA crossover</option>
          <option>Buy and hold</option>
          <option>RSI-based strategy</option>
          <option>MACD-based strategy</option>
        </select>

        <input
          type="number"
          value={capital}
          onChange={e => setCapital(Number(e.target.value))}
          aria-label="Starting capital"
          title="Starting virtual capital (INR)"
        />

        {strategy.includes('RSI') && (
          <>
            <input
              type="number"
              value={rsiOversold}
              min={10}
              max={50}
              onChange={e => setRsiOversold(Number(e.target.value))}
              aria-label="RSI oversold threshold"
              title="RSI Oversold (Entry)"
              style={{ width: '75px' }}
            />
            <input
              type="number"
              value={rsiOverbought}
              min={50}
              max={90}
              onChange={e => setRsiOverbought(Number(e.target.value))}
              aria-label="RSI overbought threshold"
              title="RSI Overbought (Exit)"
              style={{ width: '75px' }}
            />
          </>
        )}

        <button className="primary" onClick={runBt} disabled={loading}>
          <ChartNoAxesCombined/>
          {loading ? 'Running...' : 'Run Backtest'}
        </button>
      </Card>

      {ran && btData && (
        <>
          <div className="metrics six">
            <Metric
              label="Total return"
              value={`${(btData.total_return_pct >= 0 ? '+' : '') + btData.total_return_pct.toFixed(2)}%`}
              note="Net after fees"
              positive={btData.total_return_pct >= 0}
            />
            <Metric
              label="Max drawdown"
              value={`-${btData.max_drawdown_pct.toFixed(2)}%`}
              note="Peak-to-trough"
            />
            <Metric
              label="Trade count"
              value={String(btData.trade_count)}
              note="Simulated trades"
            />
            <Metric
              label="Win rate"
              value={`${btData.win_rate_pct.toFixed(1)}%`}
              note="Profitable trades"
            />
            <Metric
              label="Sharpe ratio"
              value={String(btData.sharpe_ratio)}
              note="Annualized est."
            />
            <Metric
              label="Profit factor"
              value={String(btData.profit_factor)}
              note="Win/Loss ratio"
            />
          </div>

          {btData.notes && (
            <div className="notes-callout">
              <b>Simulation Provenance:</b> {btData.notes}
            </div>
          )}
        </>
      )}

      <Card className="performance">
        <div className="card-title">
          <div>
            <h2>Equity curve</h2>
            <p>
              {strategy} on {activeDataset?.symbol || 'RELIANCE'} versus buy-and-hold benchmark
              {btData?.date_range?.start_date && (
                <span style={{ marginLeft: 6, opacity: 0.85, fontSize: 11 }}>
                  (Aligned Range: {btData.date_range.start_date} to {btData.date_range.end_date} · {btData.observation_count ?? activeDataset?.candle_count} bars)
                </span>
              )}
            </p>
          </div>
        </div>
        <BacktestEquityChart
          data={btData?.equity_curve || []}
          ran={ran}
          strategy={strategy}
          symbol={activeDataset?.symbol || 'RELIANCE'}
        />
      </Card>

      {ran && btData && (
        <Card className="trade-ledger-card" style={{ marginTop: 16 }}>
          <div className="card-title" style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center' }}>
            <div>
              <span className="eyebrow">AUDITABLE EXECUTION LOG</span>
              <h2>Simulated Trade Ledger</h2>
              <p>Next-bar Open executions · 10% single-order limit · 25% max allocation · Fee & slippage accounted</p>
            </div>
            <span className="badge badge-validated">
              {btData.trades?.length || 0} Trades Executed
            </span>
          </div>
          <TradeLedgerTable trades={btData.trades || []} />
        </Card>
      )}

      <p className="disclosure footnote">
        Backtests fill close-derived signals at the next eligible open and include fees and slippage. Results describe historical simulations.
      </p>

      {importModalOpen && (
        <ImportCsvModal
          close={() => setImportModalOpen(false)}
          onImportSuccess={(newId) => {
            loadDatasets();
            setSelectedDatasetId(newId);
            setImportModalOpen(false);
          }}
        />
      )}

      {downloadModalOpen && (
        <DownloadModal
          close={() => setDownloadModalOpen(false)}
          onDownloadSuccess={(newId) => {
            loadDatasets();
            setSelectedDatasetId(newId);
            setDownloadModalOpen(false);
          }}
        />
      )}
    </>
  );
}

function ImportCsvModal({ close, onImportSuccess }: { close: () => void; onImportSuccess: (id: string) => void }) {
  const [symbol, setSymbol] = useState('HDFCBANK');
  const [name, setName] = useState('HDFC Bank Ltd');
  const [source, setSource] = useState('LOCAL_CSV');
  const [csvText, setCsvText] = useState(`Date,Open,High,Low,Close,Volume
2025-01-02,1710.0,1725.5,1702.0,1718.0,4500000
2025-01-03,1719.0,1732.0,1712.0,1728.5,4800000
2025-01-06,1730.0,1745.0,1724.0,1741.0,5200000
2025-01-07,1740.0,1748.0,1731.0,1736.0,3900000
2025-01-08,1735.0,1752.0,1730.0,1749.0,4600000
2025-01-09,1750.0,1762.0,1744.0,1758.0,5100000
2025-01-10,1759.0,1765.0,1748.0,1751.0,4200000
2025-01-13,1752.0,1768.0,1745.0,1763.0,4700000
2025-01-14,1765.0,1774.0,1758.0,1770.0,4900000
2025-01-15,1771.0,1780.0,1762.0,1776.0,5300000
2025-01-16,1775.0,1785.0,1768.0,1782.0,5500000
2025-01-17,1781.0,1790.0,1772.0,1778.0,4800000
2025-01-20,1779.0,1788.0,1770.0,1784.0,4300000
2025-01-21,1785.0,1795.0,1778.0,1791.0,5100000
2025-01-22,1792.0,1804.0,1786.0,1799.0,5600000
2025-01-23,1798.0,1810.0,1790.0,1805.0,5800000`);
  const [preview, setPreview] = useState<any>(null);
  const [loading, setLoading] = useState(false);
  const [err, setErr] = useState<string | null>(null);

  const handlePreview = async () => {
    setLoading(true);
    setErr(null);
    try {
      const p = await api.previewCsv(csvText, symbol, '1d');
      setPreview(p);
    } catch (e: any) {
      setErr(e.message || 'Preview failed');
    } finally {
      setLoading(false);
    }
  };

  const handleImport = async () => {
    setLoading(true);
    setErr(null);
    try {
      const res = await api.importCsv({
        csv_text: csvText,
        symbol: symbol.toUpperCase(),
        dataset_name: `${symbol.toUpperCase()} Historical Daily (${source})`,
        asset_name: name,
        exchange: 'NSE',
        source: source,
        provenance: `Manual CSV upload into HIVE`,
        timeframe: '1d',
      });
      onImportSuccess(res.dataset_id);
    } catch (e: any) {
      setErr(e.message || 'Import failed');
    } finally {
      setLoading(false);
    }
  };

  return (
    <div className="modal-backdrop" onClick={close}>
      <div className="modal-dialog" onClick={e => e.stopPropagation()}>
        <div className="card-title">
          <div>
            <span className="eyebrow">WORKFLOW A</span>
            <h2>Import Historical CSV Data</h2>
          </div>
          <button className="icon-button" onClick={close}><X size={16}/></button>
        </div>
        <p>Import verified OHLCV candles into HIVE's SQLite database with strict validation and duplicate prevention.</p>

        {err && <div className="error-callout"><AlertTriangle size={14}/> {err}</div>}

        <label>Asset Symbol</label>
        <input value={symbol} onChange={e => setSymbol(e.target.value.toUpperCase())} placeholder="e.g. HDFCBANK"/>

        <label>Asset Name</label>
        <input value={name} onChange={e => setName(e.target.value)} placeholder="e.g. HDFC Bank Ltd"/>

        <label>Source Type</label>
        <select value={source} onChange={e => setSource(e.target.value)}>
          <option value="LOCAL_CSV">Local CSV File</option>
          <option value="NSE_INDIA_OFFICIAL">Official NSE Historical Report</option>
          <option value="KAGGLE_ARCHIVE">Kaggle Historical Market Dataset</option>
        </select>

        <label>CSV Data (Paste or Edit)</label>
        <textarea
          value={csvText}
          onChange={e => setCsvText(e.target.value)}
          rows={7}
          placeholder="Date,Open,High,Low,Close,Volume..."
        />

        {preview && (
          <div className="preview-box">
            <b>Validation Report:</b>
            <ul>
              <li>Accepted Rows: <b style={{ color: '#168761' }}>{preview.validation_report.accepted_rows}</b></li>
              <li>Rejected Rows: <b>{preview.validation_report.rejected_rows}</b></li>
              <li>Duplicates: <b>{preview.validation_report.duplicate_count}</b></li>
              <li>Quality Status: <b>{preview.validation_report.status}</b></li>
            </ul>
          </div>
        )}

        <div className="modal-actions">
          <button className="btn-secondary" onClick={handlePreview} disabled={loading}>
            {loading ? 'Checking...' : 'Preview & Validate'}
          </button>
          <button className="primary" onClick={handleImport} disabled={loading}>
            <Upload size={14}/> {loading ? 'Importing...' : 'Confirm & Save Dataset'}
          </button>
        </div>
      </div>
    </div>
  );
}

function DownloadModal({ close, onDownloadSuccess }: { close: () => void; onDownloadSuccess: (id: string) => void }) {
  const [symbol, setSymbol] = useState('TATAMOTORS');
  const [period, setPeriod] = useState('1y');
  const [interval, setInterval] = useState('1d');
  const [preview, setPreview] = useState<any>(null);
  const [loading, setLoading] = useState(false);
  const [err, setErr] = useState<string | null>(null);

  const handlePreview = async () => {
    setLoading(true);
    setErr(null);
    try {
      const p = await api.previewDownload(symbol, period, interval);
      setPreview(p);
    } catch (e: any) {
      setErr(e.message || 'Scope preview failed');
    } finally {
      setLoading(false);
    }
  };

  const handleDownload = async () => {
    setLoading(true);
    setErr(null);
    try {
      const res = await api.executeDownload(symbol, period, interval);
      onDownloadSuccess(res.dataset_id);
    } catch (e: any) {
      setErr(e.message || 'Download failed');
    } finally {
      setLoading(false);
    }
  };

  return (
    <div className="modal-backdrop" onClick={close}>
      <div className="modal-dialog" onClick={e => e.stopPropagation()}>
        <div className="card-title">
          <div>
            <span className="eyebrow">WORKFLOW B</span>
            <h2>Optional Historical Downloader</h2>
          </div>
          <button className="icon-button" onClick={close}><X size={16}/></button>
        </div>
        <p>Explicitly initiated download via open-source yfinance. Disabled by default, never runs on startup.</p>

        {err && <div className="error-callout"><AlertTriangle size={14}/> {err}</div>}

        <label>Indian Stock Symbol (NSE)</label>
        <input value={symbol} onChange={e => setSymbol(e.target.value.toUpperCase())} placeholder="e.g. TATAMOTORS, HDFCBANK, INFY"/>

        <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: '10px' }}>
          <div>
            <label>Period Scope</label>
            <select value={period} onChange={e => setPeriod(e.target.value)}>
              <option value="1mo">1 Month</option>
              <option value="3mo">3 Months</option>
              <option value="6mo">6 Months</option>
              <option value="1y">1 Year</option>
              <option value="2y">2 Years</option>
            </select>
          </div>
          <div>
            <label>Interval</label>
            <select value={interval} onChange={e => setInterval(e.target.value)}>
              <option value="1d">Daily (1d)</option>
              <option value="1wk">Weekly (1wk)</option>
              <option value="1mo">Monthly (1mo)</option>
            </select>
          </div>
        </div>

        <div className="provenance-box" style={{ marginTop: 14 }}>
          <b>Notice:</b> Yahoo Finance is a third-party source. Data is unadjusted and subject to provider terms. Not official exchange data.
        </div>

        {preview && (
          <div className="preview-box">
            <b>Resolved Scope:</b>
            <ul>
              <li>Ticker: <b>{preview.resolved_ticker}</b></li>
              <li>Source: <b>{preview.source}</b></li>
              <li>Terms: <b>{preview.license_terms}</b></li>
            </ul>
          </div>
        )}

        <div className="modal-actions">
          <button className="btn-secondary" onClick={handlePreview} disabled={loading}>
            Preview Scope
          </button>
          <button className="primary" onClick={handleDownload} disabled={loading}>
            <Download size={14}/> {loading ? 'Fetching...' : 'Download & Ingest'}
          </button>
        </div>
      </div>
    </div>
  );
}

function SettingsDrawer({
  close,
  settings,
  setSettings,
  autoExecute,
  setAutoExecute,
  reset,
}: {
  close: () => void;
  settings: { fee: number; maxOrder: number; maxAllocation: number; drawdown: number };
  setSettings: (s: { fee: number; maxOrder: number; maxAllocation: number; drawdown: number }) => void;
  autoExecute: boolean;
  setAutoExecute: (b: boolean) => void;
  reset: (token: string) => Promise<void>;
}) {
  const [token, setToken] = useState('');
  const [draft, setDraft] = useState({ ...settings, auto_execute: autoExecute });
  const [saving, setSaving] = useState(false);
  const [settingsError, setSettingsError] = useState<string | null>(null);

  const saveSettings = async () => {
    setSettingsError(null);
    setSaving(true);
    try {
      const saved = await api.updateRiskConfig(draft, token);
      setDraft(saved);
      setSettings(saved);
      setAutoExecute(saved.auto_execute);
    } catch (error) {
      setSettingsError(error instanceof Error ? error.message : String(error));
    } finally {
      setSaving(false);
    }
  };
  const resetWithToken = async () => {
    setSettingsError(null);
    try {
      await reset(token);
    } catch (error) {
      setSettingsError(error instanceof Error ? error.message : String(error));
    }
  };

  useEffect(() => {
    const onPointerDown = (event: PointerEvent) => {
      if (event.target instanceof Element && !event.target.closest('.settings-anchor')) close();
    };
    const onKeyDown = (event: KeyboardEvent) => {
      if (event.key === 'Escape') close();
    };
    document.addEventListener('pointerdown', onPointerDown);
    document.addEventListener('keydown', onKeyDown);
    return () => {
      document.removeEventListener('pointerdown', onPointerDown);
      document.removeEventListener('keydown', onKeyDown);
    };
  }, [close]);

  return (
    <aside className="drawer" role="dialog" aria-label="Simulation settings">
      <div className="card-title">
      <label>Local operator token <input type="password" autoComplete="off" value={token}
        onChange={(event) => setToken(event.target.value)} /></label>
      {settingsError && <p role="alert">{settingsError}</p>}
        <div>
          <span className="eyebrow">SIMULATION SETTINGS</span>
          <h2>Configure rules</h2>
        </div>
        <button className="icon-button" aria-label="Close settings" onClick={close}><X/></button>
      </div>
      {(
        [
          ['Transaction fee (%)', 'fee'],
          ['Maximum new order (%)', 'maxOrder'],
          ['Maximum asset concentration (%)', 'maxAllocation'],
          ['Drawdown halt (%)', 'drawdown'],
        ] as const
      ).map(([l, k]) => (
        <label className="setting" key={k}>
          {l}
          <input
            type="number"
            value={draft[k]}
            onChange={event => setDraft(value => ({ ...value, [k]: Number(event.target.value) }))}
          />
        </label>
      ))}
      <label className="toggle">
        Auto-execute approved simulated orders
        <input
          type="checkbox"
          checked={draft.auto_execute}
          onChange={event => setDraft(value => ({ ...value, auto_execute: event.target.checked }))}
        />
      </label>
      <button className="primary" onClick={saveSettings} disabled={!token || saving}>
        {saving ? 'Saving…' : 'Save settings'}
      </button>
      <button className="danger" onClick={resetWithToken} disabled={!token || saving}>
        Reset simulation
      </button>
      <p className="disclosure">These are educational simulation rules, not investment advice.</p>
    </aside>
  );
}
