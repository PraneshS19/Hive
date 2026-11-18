import { useEffect, useState } from 'react';
import { Area, AreaChart, Bar, CartesianGrid, ComposedChart, Legend, Line, ResponsiveContainer, Tooltip, XAxis, YAxis } from 'recharts';
import { Activity, BrainCircuit, ChartNoAxesCombined, RotateCcw, Sparkles, AlertTriangle } from 'lucide-react';
import { api, type AgentRunSummary } from '../services/api';
import { money } from '../services/formatNumbers';

type TimeframeOption = '1M' | '3M' | '6M' | '1Y';

const TIMEFRAME_BARS: Record<TimeframeOption, number> = {
  '1M': 30,
  '3M': 60,
  '6M': 120,
  '1Y': 246,
};

export function MarketPriceChart({ symbol }: { symbol: string }) {
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

export function AgentPerformancePanel({ onNavigateAgentCenter }: { onNavigateAgentCenter?: () => void }) {
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

export function BacktestEquityChart({
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
