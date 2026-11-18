import React, { useState, useEffect } from 'react';
import { Radio } from 'lucide-react';
import { api } from '../../services/api';

export function DhanConfigSection() {
  const [operatorToken, setOperatorToken] = useState('');
  const [clientId, setClientId] = useState<string>('');
  const [accessToken, setAccessToken] = useState<string>('');
  const [feedEnabled, setFeedEnabled] = useState<boolean>(false);
  const [stalenessSec, setStalenessSec] = useState<number>(15);
  const [feedStatus, setFeedStatus] = useState<any>(null);
  const [isSaving, setIsSaving] = useState<boolean>(false);
  const [message, setMessage] = useState<string | null>(null);

  const loadStatus = async () => {
    try {
      const res = await api.getDhanStatus();
      setFeedStatus(res);
      setFeedEnabled(res.feed_enabled);
      setStalenessSec(res.staleness_threshold_seconds || 15);
    } catch (e) {
      console.error('Error fetching Dhan status:', e);
    }
  };

  useEffect(() => {
    loadStatus();
  }, []);

  const handleSave = async (e: React.FormEvent) => {
    e.preventDefault();
    setIsSaving(true);
    setMessage(null);
    try {
      const res = await api.updateDhanConfig({
        client_id: clientId || undefined,
        access_token: accessToken || undefined,
        feed_enabled: feedEnabled,
        staleness_threshold_seconds: Number(stalenessSec),
      }, operatorToken);
      setAccessToken('');
      setOperatorToken('');
      setMessage(res.message);
      await loadStatus();
    } catch (err: any) {
      setMessage(`Failed to update settings: ${err.message || err}`);
    } finally {
      setIsSaving(false);
      setTimeout(() => setMessage(null), 6000);
    }
  };

  return (
    <div className="dhan-settings-panel">
      <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center' }}>
        <div style={{ display: 'flex', alignItems: 'center', gap: '8px' }}>
          <Radio size={16} color="#60a5fa" />
          <span style={{ fontSize: '13px', fontWeight: 700, color: '#f8fafc' }}>
            DhanHQ-py Live Market-Data Ingestion
          </span>
        </div>
        <span style={{
          fontSize: '11px',
          fontWeight: 700,
          padding: '2px 8px',
          borderRadius: '4px',
          background: feedStatus?.status === 'LIVE' ? 'rgba(16, 185, 129, 0.15)' : 'rgba(255, 255, 255, 0.05)',
          color: feedStatus?.status === 'LIVE' ? '#34d399' : '#94a3b8'
        }}>
          {feedStatus?.status || 'UNCONFIGURED'}
        </span>
      </div>

      <p style={{ fontSize: '11px', color: '#94a3b8', margin: 0, lineHeight: '1.4' }}>
        DhanHQ credentials enable WebSocket market-data ingestion. Put persistent feed settings in the backend environment.
      </p>

      <form onSubmit={handleSave} style={{ display: 'flex', flexDirection: 'column', gap: '10px' }}>
        <label>Local operator token <input type="password" autoComplete="off" value={operatorToken}
          onChange={(event) => setOperatorToken(event.target.value)} /></label>
        <div className="dhan-input-group">
          <label>Dhan Client ID</label>
          <input
            type="text"
            placeholder={feedStatus?.credentials_configured ? '•••••••• (Configured)' : 'Enter Dhan Client ID'}
            value={clientId}
            onChange={(e) => setClientId(e.target.value)}
          />
        </div>

        <div className="dhan-input-group">
          <label>Dhan Access Token</label>
          <input
            type="password"
            placeholder={feedStatus?.credentials_configured ? '•••••••••••••••• (Configured)' : 'Enter Dhan Access Token'}
            value={accessToken}
            onChange={(e) => setAccessToken(e.target.value)}
          />
        </div>

        <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', padding: '6px 0' }}>
          <div>
            <b style={{ fontSize: '12px', color: '#e2e8f0', display: 'block' }}>Enable Live Feed</b>
            <span style={{ fontSize: '10px', color: '#64748b' }}>Connect to live Dhan MarketFeed WebSocket</span>
          </div>
          <input
            type="checkbox"
            checked={feedEnabled}
            onChange={(e) => setFeedEnabled(e.target.checked)}
            style={{ width: '16px', height: '16px', cursor: 'pointer' }}
          />
        </div>

        <div className="dhan-input-group">
          <label>Staleness Threshold (Seconds)</label>
          <input
            type="number"
            min={5}
            max={60}
            value={stalenessSec}
            onChange={(e) => setStalenessSec(Number(e.target.value))}
          />
        </div>

        {message && (
          <div style={{ fontSize: '11px', color: '#60a5fa', background: 'rgba(59, 130, 246, 0.1)', padding: '6px 10px', borderRadius: '4px' }}>
            {message}
          </div>
        )}

        <button
          type="submit"
          disabled={isSaving || !operatorToken}
          style={{
            background: 'linear-gradient(135deg, #2563eb, #1d4ed8)',
            color: '#ffffff',
            border: 'none',
            padding: '8px 14px',
            borderRadius: '6px',
            fontSize: '12px',
            fontWeight: 600,
            cursor: 'pointer',
            marginTop: '4px'
          }}
        >
          {isSaving ? 'Updating...' : 'Save & Update Feed Settings'}
        </button>
      </form>
    </div>
  );
}
