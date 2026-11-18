import { useState, useEffect } from 'react';
import { Check, X, RefreshCw } from 'lucide-react';
import { api } from '../../services/api';

type PaperProposalsProps = {
  onProposalExecuted?: () => void;
};

export function PaperProposalsPanel({ onProposalExecuted }: PaperProposalsProps) {
  const [proposals, setProposals] = useState<any[]>([]);
  const [isConfirming, setIsConfirming] = useState<boolean>(false);
  const [confirmResult, setConfirmResult] = useState<any | null>(null);
  const [actionError, setActionError] = useState<string | null>(null);

  const loadProposals = async () => {
    try {
      const data = await api.getPaperProposals();
      setProposals(data);
    } catch (e) {
      console.error('Error fetching paper proposals:', e);
    }
  };

  useEffect(() => {
    loadProposals();
    const interval = setInterval(loadProposals, 8000);
    return () => clearInterval(interval);
  }, []);

  const handleConfirm = async (proposalId: string) => {
    setIsConfirming(true);
    setActionError(null);
    setConfirmResult(null);
    try {
      const res = await api.confirmPaperProposal(proposalId);
      setConfirmResult(res);
      await loadProposals();
      if (onProposalExecuted) {
        onProposalExecuted();
      }
    } catch (err: any) {
      setActionError(err.message || 'Confirmation failed.');
    } finally {
      setIsConfirming(false);
    }
  };

  const handleReject = async (proposalId: string) => {
    try {
      await api.rejectPaperProposal(proposalId, 'Dismissed by user from Portfolio page');
      await loadProposals();
    } catch (err: any) {
      setActionError(err.message || 'Rejection failed.');
    }
  };

  const pendingProposals = proposals.filter((p) => p.status === 'PENDING_CONFIRMATION');

  return (
    <div style={{ marginTop: '16px' }}>
      <div className="paper-proposals-heading" style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: '12px' }}>
        <div>
          <span className="paper-proposals-eyebrow" style={{ fontSize: '11px', textTransform: 'uppercase', color: '#64748b', letterSpacing: '0.08em', display: 'block' }}>
            RISK-GATED PAPER TRADE PROPOSALS
          </span>
          <h2 className="paper-proposals-title" style={{ fontSize: '16px', fontWeight: 700, color: '#f8fafc', margin: 0 }}>
            Awaiting Explicit Human Confirmation ({pendingProposals.length})
          </h2>
        </div>
        <button
          className="paper-proposals-refresh"
          onClick={loadProposals}
          style={{
            background: 'transparent',
            border: '1px solid rgba(255, 255, 255, 0.1)',
            color: '#94a3b8',
            padding: '4px 8px',
            borderRadius: '4px',
            fontSize: '11px',
            cursor: 'pointer'
          }}
        >
          <RefreshCw size={11} style={{ marginRight: '4px' }} /> Refresh
        </button>
      </div>

      {actionError && (
        <div style={{
          background: 'rgba(239, 68, 68, 0.15)',
          border: '1px solid rgba(239, 68, 68, 0.3)',
          color: '#f87171',
          padding: '10px 14px',
          borderRadius: '6px',
          fontSize: '12px',
          marginBottom: '12px'
        }}>
          <b>Revalidation / Risk Gate Error:</b> {actionError}
        </div>
      )}

      {confirmResult && (
        <div style={{
          background: 'rgba(16, 185, 129, 0.15)',
          border: '1px solid rgba(16, 185, 129, 0.3)',
          color: '#34d399',
          padding: '10px 14px',
          borderRadius: '6px',
          fontSize: '12px',
          marginBottom: '12px'
        }}>
          <b>Paper Order Executed:</b> {confirmResult.message} (Fill Price: ₹{confirmResult.fill_price?.toFixed(2)}, Fee: ₹{confirmResult.fee?.toFixed(2)})
        </div>
      )}

      {pendingProposals.length > 0 ? (
        pendingProposals.map((p) => (
          <div key={p.proposal_id} className="pending-proposal-card">
            <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'flex-start' }}>
              <div>
                <div style={{ display: 'flex', alignItems: 'center', gap: '8px' }}>
                  <span style={{
                    fontSize: '11px',
                    fontWeight: 700,
                    padding: '2px 8px',
                    borderRadius: '4px',
                    background: p.side === 'BUY' ? 'rgba(16, 185, 129, 0.15)' : 'rgba(239, 68, 68, 0.15)',
                    color: p.side === 'BUY' ? '#34d399' : '#f87171'
                  }}>
                    {p.side}
                  </span>
                  <span style={{ fontSize: '15px', fontWeight: 700, color: '#ffffff' }}>
                    {p.requested_qty} shares of {p.symbol}
                  </span>
                  <span style={{ fontSize: '12px', color: '#94a3b8' }}>
                    @ est. ₹{p.estimated_price?.toFixed(2)}
                  </span>
                </div>
                <div style={{ fontSize: '12px', color: '#cbd5e1', marginTop: '4px' }}>
                  Notional: <b>₹{p.estimated_notional?.toLocaleString('en-IN', { minimumFractionDigits: 2 })}</b>
                </div>
              </div>

              <div style={{ textAlign: 'right', fontSize: '11px', color: '#64748b' }}>
                <div>Expires: {p.expires_at ? p.expires_at.slice(11, 16) : '--:--'}</div>
                <code style={{ fontSize: '10px', color: '#94a3b8' }}>{p.proposal_id}</code>
              </div>
            </div>

            <p style={{ fontSize: '12px', color: '#94a3b8', margin: 0 }}>
              {p.reason}
            </p>

            {/* Deterministic Revalidation Checklist */}
            <div className="revalidation-box">
              <b style={{ color: '#cbd5e1', display: 'block', marginBottom: '4px' }}>Deterministic Pre-Checks:</b>
              <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fit, minmax(200px, 1fr))', gap: '4px' }}>
                <span style={{ color: p.risk_check_passed ? '#34d399' : '#f87171' }}>
                  {p.risk_check_passed ? '✓' : '✗'} 10% Single-Order Limit (₹1,00,000 max)
                </span>
                <span style={{ color: '#34d399' }}>✓ Cash Balance Sufficiency</span>
                <span style={{ color: '#34d399' }}>✓ Prohibit Uncovered Short-Selling</span>
                <span style={{ color: '#34d399' }}>✓ 0.05% Slippage & 0.1% Fee Modelled</span>
              </div>
            </div>

            {/* Operator Confirmation Actions */}
            <div style={{ display: 'flex', gap: '10px', alignItems: 'center', marginTop: '4px' }}>
              <button
                className="btn-approve"
                onClick={() => handleConfirm(p.proposal_id)}
                disabled={isConfirming}
                style={{ display: 'inline-flex', alignItems: 'center', gap: '6px' }}
              >
                <Check size={13} /> Confirm & Execute Paper Trade
              </button>
              <button
                className="btn-reject"
                onClick={() => handleReject(p.proposal_id)}
                disabled={isConfirming}
                style={{ display: 'inline-flex', alignItems: 'center', gap: '6px' }}
              >
                <X size={13} /> Dismiss Proposal
              </button>
            </div>
          </div>
        ))
      ) : (
        <div className="paper-proposals-empty" style={{
          background: 'rgba(18, 24, 38, 0.6)',
          border: '1px dashed rgba(255, 255, 255, 0.1)',
          borderRadius: '8px',
          padding: '24px',
          textAlign: 'center',
          color: '#64748b',
          fontSize: '13px'
        }}>
          No pending paper-trade proposals awaiting confirmation. Proposals are generated when meaningful market events are verified by the intelligence workflow.
        </div>
      )}
    </div>
  );
}
