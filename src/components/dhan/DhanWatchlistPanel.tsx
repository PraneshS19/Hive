import { useState, useEffect } from 'react';
import { Server, Clock, Play, RefreshCw, TrendingUp, TrendingDown, AlertTriangle, Radio } from 'lucide-react';
import { api } from '../../services/api';

const MAX_DISPLAYED_INSTRUMENTS = 20;

type DhanWatchlistPanelProps = {
  selectedSymbol: string;
  onSelectSymbol: (symbol: string) => void;
  onTriggerAnalysis?: (symbol: string, reason: string) => void;
};

export function DhanWatchlistPanel({
  selectedSymbol,
  onSelectSymbol,
  onTriggerAnalysis,
}: DhanWatchlistPanelProps) {
  const [feedStatus, setFeedStatus] = useState<any>(null);
  const [watchlist, setWatchlist] = useState<any[]>([]);
  const [recentEvents, setRecentEvents] = useState<any[]>([]);
  const [filterQuery, setFilterQuery] = useState<string>('');
  const [isRefreshing, setIsRefreshing] = useState<boolean>(false);
  const [actionMessage, setActionMessage] = useState<string | null>(null);

  const loadFeedData = async () => {
    try {
      const [statusRes, watchRes, eventsRes] = await Promise.allSettled([
        api.getDhanStatus(),
        api.getDhanWatchlist(),
        api.getDhanEvents(10)
      ]);
      if (statusRes.status === 'fulfilled') setFeedStatus(statusRes.value);
      if (watchRes.status === 'fulfilled') setWatchlist(watchRes.value);
      if (eventsRes.status === 'fulfilled') setRecentEvents(eventsRes.value);
    } catch (e) {
      console.error('Error fetching Dhan feed data:', e);
    }
  };

  useEffect(() => {
    loadFeedData();
    const interval = setInterval(loadFeedData, 5000);
    return () => clearInterval(interval);
  }, []);

  const handleManualRefresh = async () => {
    setIsRefreshing(true);
    await loadFeedData();
    setIsRefreshing(false);
  };

  const handleTriggerEvent = async (symbol: string, reason: string) => {
    try {
      setActionMessage(`Triggering event analysis for ${symbol}...`);
      const res = await api.triggerDhanEvent(symbol, reason);
      setActionMessage(`Event created: ${res.headline}`);
      await loadFeedData();
      if (onTriggerAnalysis) {
        onTriggerAnalysis(symbol, reason);
      }
    } catch (err: any) {
      setActionMessage(`Failed to trigger event: ${err.message || err}`);
    } finally {
      setTimeout(() => setActionMessage(null), 6000);
    }
  };

  const filteredWatchlist = watchlist.filter(
    (item) =>
      item.symbol.toLowerCase().includes(filterQuery.toLowerCase()) ||
      (item.name && item.name.toLowerCase().includes(filterQuery.toLowerCase()))
  );
  const displayedWatchlist = filteredWatchlist.slice(0, MAX_DISPLAYED_INSTRUMENTS);

  const getStatusBadge = () => {
    if (!feedStatus) return <span className="badge-unconfigured"><Radio size={12}/> Connecting...</span>;
    if (!feedStatus.is_market_session) {
      return (
        <span className="badge-closed" style={{ background: 'rgba(100, 116, 139, 0.2)', color: '#94a3b8', border: '1px solid rgba(148, 163, 184, 0.3)' }}>
          <Clock size={12}/> MARKET CLOSED — LAST AVAILABLE PRICES
        </span>
      );
    }
    switch (feedStatus.status) {
      case 'DATA_FRESH':
      case 'LIVE':
        return <span className="badge-live"><Radio size={12}/> LIVE (0xramm REST Adapter)</span>;
      case 'STALE':
        return <span className="badge-stale"><Clock size={12}/> FEED STALE</span>;
      case 'MARKET_CLOSED':
        return <span className="badge-closed"><Clock size={12}/> MARKET CLOSED</span>;
      case 'WAITING_FOR_FIRST_POLL':
      case 'WAITING_FOR_FIRST_TICK':
        return <span className="badge-stale"><Clock size={12}/> WAITING FOR FIRST POLL</span>;
      case 'PROVIDER_ERROR':
      case 'ERROR':
        return <span className="badge-unconfigured"><AlertTriangle size={12}/> PROVIDER ERROR</span>;
      default:
        return <span className="badge-unconfigured"><Server size={12}/> {feedStatus.status}</span>;
    }
  };

  return (
    <div className="dhan-watchlist-container">
      {/* 1. Feed Health & Session Status Banner */}
      <div style={{
        background: 'rgba(18, 24, 38, 0.85)',
        border: '1px solid rgba(80, 110, 170, 0.25)',
        borderRadius: '10px',
        padding: '14px 18px',
        display: 'flex',
        justifyContent: 'space-between',
        alignItems: 'center',
        flexWrap: 'wrap',
        gap: '12px'
      }}>
        <div style={{ display: 'flex', alignItems: 'center', gap: '14px', flexWrap: 'wrap' }}>
          <div>
            <span style={{ fontSize: '11px', textTransform: 'uppercase', color: '#64748b', letterSpacing: '0.08em', display: 'block' }}>
              MARKET-DATA INGESTION (PROVISIONAL REST ADAPTER)
            </span>
            <span style={{ fontSize: '15px', fontWeight: 700, color: '#f8fafc' }}>
              0xramm Indian Stock Market API
            </span>
            <span style={{ fontSize: '11px', color: '#94a3b8', display: 'block', marginTop: '2px' }}>
              Provisional REST adapter backed by Yahoo Finance • Educational research & paper trading only
            </span>
          </div>

          <div>{getStatusBadge()}</div>

          <span style={{ fontSize: '12px', color: '#94a3b8' }}>
            {feedStatus?.market_session_note || 'Checking NSE trading session...'}
          </span>
        </div>

        <div style={{ display: 'flex', alignItems: 'center', gap: '10px' }}>
          {actionMessage && (
            <span style={{ fontSize: '12px', color: '#60a5fa', background: 'rgba(59, 130, 246, 0.1)', padding: '4px 10px', borderRadius: '4px' }}>
              {actionMessage}
            </span>
          )}
          <button
            onClick={handleManualRefresh}
            style={{
              background: 'rgba(255, 255, 255, 0.05)',
              border: '1px solid rgba(255, 255, 255, 0.1)',
              color: '#cbd5e1',
              padding: '6px 12px',
              borderRadius: '6px',
              fontSize: '12px',
              cursor: 'pointer',
              display: 'inline-flex',
              alignItems: 'center',
              gap: '6px'
            }}
          >
            <RefreshCw size={13} className={isRefreshing ? 'spin' : ''} /> Poll Now
          </button>
        </div>
      </div>

      {/* 2. Telemetry Quick Stats */}
      <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fit, minmax(180px, 1fr))', gap: '10px' }}>
        <div className="rubric-card">
          <span style={{ fontSize: '11px', color: '#64748b', textTransform: 'uppercase' }}>Displayed Instruments</span>
          <span style={{ fontSize: '20px', fontWeight: 700, color: '#f8fafc' }}>
            {displayedWatchlist.length} Instruments
          </span>
          <span style={{ fontSize: '10px', color: '#94a3b8' }}>NSE Listed Equity & Index</span>
        </div>

        <div className="rubric-card">
          <span style={{ fontSize: '11px', color: '#64748b', textTransform: 'uppercase' }}>Polled Observations</span>
          <span style={{ fontSize: '20px', fontWeight: 700, color: '#38bdf8', fontFamily: 'monospace' }}>
            {feedStatus?.valid_polls_count ?? feedStatus?.valid_ticks_count ?? 0}
          </span>
          <span style={{ fontSize: '10px', color: '#10b981' }}>
            {feedStatus?.poll_interval_seconds ? `${feedStatus.poll_interval_seconds}s cadence` : 'Single-flight polling'}
          </span>
        </div>

        <div className="rubric-card">
          <span style={{ fontSize: '11px', color: '#64748b', textTransform: 'uppercase' }}>Feed Freshness</span>
          <span style={{ fontSize: '16px', fontWeight: 700, color: feedStatus?.status === 'LIVE' ? '#34d399' : '#fbbf24' }}>
            {feedStatus?.status === 'LIVE' ? 'Freshly Polled' : feedStatus?.status || 'Awaiting poll'}
          </span>
          <span style={{ fontSize: '10px', color: '#94a3b8' }}>
            {feedStatus?.last_ingestion_timestamp ? `Last: ${feedStatus.last_ingestion_timestamp.slice(11, 19)} UTC` : 'No poll data yet'}
          </span>
        </div>

        <div className="rubric-card">
          <span style={{ fontSize: '11px', color: '#64748b', textTransform: 'uppercase' }}>Operating Mode</span>
          <span style={{ fontSize: '16px', fontWeight: 700, color: '#38bdf8' }}>
            LIVE ONLY
          </span>
          <span style={{ fontSize: '10px', color: '#94a3b8' }}>
            0xramm REST Adapter
          </span>
        </div>
      </div>

      {/* 3. Filter & Action Bar */}
      <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', gap: '12px', flexWrap: 'wrap' }}>
        <input
          type="text"
          placeholder="Search market instruments..."
          value={filterQuery}
          onChange={(e) => setFilterQuery(e.target.value)}
          style={{
            background: '#0a0e17',
            border: '1px solid rgba(80, 110, 170, 0.3)',
            color: '#e2e8f0',
            padding: '8px 14px',
            borderRadius: '6px',
            fontSize: '13px',
            width: '280px',
            outline: 'none'
          }}
        />

        <div style={{ display: 'flex', gap: '8px' }}>
          <button
            onClick={() => handleTriggerEvent(selectedSymbol, 'Triggered intraday momentum surge analysis')}
            style={{
              background: 'linear-gradient(135deg, #2563eb, #1d4ed8)',
              color: '#ffffff',
              border: 'none',
              padding: '7px 14px',
              borderRadius: '6px',
              fontSize: '12px',
              fontWeight: 600,
              cursor: 'pointer',
              display: 'inline-flex',
              alignItems: 'center',
              gap: '6px'
            }}
          >
            <Play size={13} /> Analyze {selectedSymbol} (Qwen ➔ Gemma)
          </button>
        </div>
      </div>

      {/* 4. Broad Watchlist Grid */}
      <div className="dhan-watchlist-grid">
        {displayedWatchlist.map((item) => {
          const isSelected = item.symbol === selectedSymbol;
          const isUp = item.change >= 0;
          return (
            <div
              key={item.symbol}
              className={`dhan-instrument-card ${isSelected ? 'selected' : ''}`}
              onClick={() => onSelectSymbol(item.symbol)}
            >
              <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'flex-start' }}>
                <div>
                  <b style={{ fontSize: '14px', color: '#ffffff' }}>{item.symbol}</b>
                  <div style={{ fontSize: '11px', color: '#94a3b8', maxWidth: '140px', textOverflow: 'ellipsis', overflow: 'hidden', whiteSpace: 'nowrap' }}>
                    {item.name}
                  </div>
                </div>
                <span
                  className={`instrument-status ${item.is_live ? 'live' : 'waiting'}`}
                  style={{
                  fontSize: '9px',
                  padding: '2px 6px',
                  borderRadius: '4px',
                  background: item.is_live
                    ? 'rgba(16, 185, 129, 0.15)'
                    : item.price_type === 'OFFICIAL_SESSION_CLOSE'
                    ? 'rgba(99, 102, 241, 0.18)'
                    : item.price_type === 'LAST_SESSION_CLOSE'
                    ? 'rgba(148, 163, 184, 0.18)'
                    : 'rgba(234, 179, 8, 0.15)',
                  color: item.is_live
                    ? '#34d399'
                    : item.price_type === 'OFFICIAL_SESSION_CLOSE'
                    ? '#818cf8'
                    : item.price_type === 'LAST_SESSION_CLOSE'
                    ? '#cbd5e1'
                    : '#fbbf24',
                  fontFamily: 'monospace'
                }}>
                  {item.is_live
                    ? 'LIVE'
                    : item.price_type === 'OFFICIAL_SESSION_CLOSE'
                    ? 'OFFICIAL CLOSE'
                    : item.price_type === 'LAST_SESSION_CLOSE'
                    ? 'SESSION CLOSE'
                    : item.price_type === 'LAST_OBSERVED_PRICE'
                    ? 'LAST OBSERVED'
                    : (item.freshness_status || 'CLOSED')}
                </span>
              </div>

              <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'baseline', marginTop: '4px' }}>
                <span style={{ fontSize: '16px', fontWeight: 700, color: '#f8fafc', fontFamily: 'monospace' }}>
                  {item.price != null && item.price > 0 ? `₹${item.price.toFixed(2)}` : 'Awaiting observation'}
                </span>
                <span className={`instrument-change ${item.price != null ? (isUp ? 'up' : 'down') : ''}`} style={{
                  fontSize: '12px',
                  fontWeight: 600,
                  color: item.price != null ? (isUp ? '#34d399' : '#f87171') : '#64748b',
                  display: 'inline-flex',
                  alignItems: 'center',
                  gap: '2px'
                }}>
                  {item.price != null ? (
                    <>
                      {isUp ? <TrendingUp size={12} /> : <TrendingDown size={12} />}
                      {item.change_pct != null ? `${item.change_pct > 0 ? '+' : ''}${item.change_pct.toFixed(2)}%` : '0.00%'}
                    </>
                  ) : (
                    '--'
                  )}
                </span>
              </div>

              <div style={{ display: 'flex', justifyContent: 'space-between', fontSize: '10px', color: '#64748b', marginTop: '2px' }}>
                <span>Vol: {item.volume ? item.volume.toLocaleString() : 'N/A'}</span>
                <span>
                  {item.observation_timestamp
                    ? `Obs: ${item.observation_timestamp.slice(11, 16)} UTC`
                    : (item.source_timestamp ? item.source_timestamp.slice(11, 16) : '')}
                </span>
              </div>
            </div>
          );
        })}
      </div>

      {/* 5. Detected Market Events Timeline */}
      {recentEvents.length > 0 && (
        <div className="market-events-panel" style={{
          background: 'rgba(18, 24, 38, 0.85)',
          border: '1px solid rgba(80, 110, 170, 0.25)',
          borderRadius: '10px',
          padding: '16px',
          marginTop: '6px'
        }}>
          <span style={{ fontSize: '13px', fontWeight: 700, color: '#f8fafc' }}>
            Deterministic Market Events Detected
          </span>
          <div style={{ display: 'flex', flexDirection: 'column', gap: '8px', marginTop: '10px' }}>
            {recentEvents.map((ev) => (
              <div className="market-event-card" key={ev.event_id} style={{
                background: '#090d16',
                border: '1px solid rgba(255, 255, 255, 0.06)',
                borderRadius: '6px',
                padding: '10px 14px',
                display: 'flex',
                justifyContent: 'space-between',
                alignItems: 'center',
                flexWrap: 'wrap',
                gap: '8px'
              }}>
                <div>
                  <div style={{ display: 'flex', alignItems: 'center', gap: '8px' }}>
                    <span className={`market-event-type ${ev.event_type === 'PRICE_SURGE' ? 'surge' : 'other'}`} style={{
                      fontSize: '10px',
                      fontWeight: 700,
                      padding: '2px 6px',
                      borderRadius: '4px',
                      background: ev.event_type === 'PRICE_SURGE' ? 'rgba(59, 130, 246, 0.15)' : 'rgba(245, 158, 11, 0.15)',
                      color: ev.event_type === 'PRICE_SURGE' ? '#93c5fd' : '#fbbf24'
                    }}>
                      {ev.event_type}
                    </span>
                    <b style={{ fontSize: '13px', color: '#e2e8f0' }}>{ev.headline}</b>
                  </div>
                  <span className="market-event-detail" style={{ fontSize: '11px', color: '#94a3b8' }}>
                    Severity: {ev.severity}/100 · {ev.event_time ? ev.event_time.slice(11, 19) : ''}
                  </span>
                </div>

                <button
                  onClick={() => handleTriggerEvent(ev.symbol, `Analyze event ${ev.event_id}`)}
                  style={{
                    background: 'rgba(59, 130, 246, 0.15)',
                    border: '1px solid rgba(59, 130, 246, 0.3)',
                    color: '#93c5fd',
                    padding: '5px 10px',
                    borderRadius: '4px',
                    fontSize: '11px',
                    cursor: 'pointer'
                  }}
                >
                  Analyze Event ➔
                </button>
              </div>
            ))}
          </div>
        </div>
      )}
    </div>
  );
}
