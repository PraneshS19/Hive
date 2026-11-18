/**
 * HIVE API Client
 * Connects frontend to the FastAPI backend (/api/v1) with typed schemas and graceful error handling.
 */

const API_BASE = '/api/v1';

export type ScenarioType =
  | 'VOLATILITY_SURGE'
  | 'RISK_OFF_PULLBACK'
  | 'UNVERIFIED_RUMOR'
  | 'LIQUIDITY_SQUEEZE'
  | 'CRASH'
  | 'RALLY'
  | 'MISLEADING_NEWS'
  | 'LIQUIDITY_SHOCK';
export type Status = 'APPROVED' | 'RESIZED' | 'REJECTED' | 'PROPOSAL';

export type QuoteHistoryPoint = {
  time: string;
  price: number;
  equity: number;
};

export type Quote = {
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
  history?: QuoteHistoryPoint[];
};

export type MarketStatus = {
  is_market_session: boolean;
  market_status: string;
  trading_day_status: string;
  session_start_ist: string;
  session_end_ist: string;
  timezone: string;
  feed_health: string;
  feed_status: string;
  last_completed_session_date: string | null;
  active_data_source: string;
  session_note: string;
  description?: string;
};

export type Position = {
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

export type Event = {
  id: number;
  type: ScenarioType;
  severity: number;
  headline: string;
  time: string;
  outcome: Status;
};

export type Order = {
  id: number;
  symbol: string;
  side: 'BUY' | 'SELL';
  requested: number;
  executed: number;
  price: number;
  fee: number;
  status: Status;
  reason: string;
  time: string;
};

export type AgentCard = {
  name: string;
  status: string;
  value: string;
  text: string;
  execution_mode: string;
};

export type RiskConfig = {
  fee: number;
  maxOrder: number;
  maxAllocation: number;
  drawdown: number;
  auto_execute: boolean;
};

export type PromptVersion = {
  id: number;
  version_tag: string;
  role: string;
  prompt_hash: string;
  is_active: number;
  parent_version?: string | null;
  benchmark_score?: number | null;
  created_at: string;
};

export type ActivePromptVersionInfo = {
  active_prompt_version: string;
  active_prompt_hash: string;
  active_prompt_source: string;
  is_active: number;
};

export type AgentRunSummary = {
  run_id: string;
  task_type: string;
  symbol: string;
  status: string;
  executor_model: string;
  reviewer_model: string;
  review_verdict: string;
  overall_score: number;
  revision_count: number;
  total_latency_ms: number;
  executor_latency_ms?: number;
  reviewer_latency_ms?: number;
  objective_pass_pct?: number;
  objective_checks?: Record<string, any>;
  findings_count?: number;
  created_at: string;
  completed_at?: string | null;
};

export type DatasetRecord = {
  id: string;
  name: string;
  symbol: string;
  asset_name?: string;
  exchange: string;
  source: string;
  provenance: string;
  timeframe: string;
  start_date: string;
  end_date: string;
  candle_count: number;
  is_adjusted: boolean;
  adjustment_status: string;
  quality_status: string;
  license_info: string;
  created_at: string;
  updated_at: string;
  validation_report?: {
    status: string;
    total_rows: number;
    accepted_rows: number;
    rejected_rows: number;
    duplicate_count: number;
    warnings: string[];
    gaps_detected: { from_date: string; to_date: string; gap_calendar_days: number; missing_trading_days: number }[];
  };
};

export type BacktestResult = {
  run_id: string;
  strategy: string;
  symbol: string;
  timeframe: string;
  starting_capital: number;
  final_equity: number;
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
  dataset_id?: string;
  dataset_checksum?: string;
  equity_curve: { time: string; equity: number; benchmark: number }[];
  trades: {
    id: number;
    symbol: string;
    entry_time: string;
    exit_time: string;
    side: string;
    quantity: number;
    entry_price: number;
    exit_price: number;
    pnl: number;
    pnl_pct: number;
    status: string;
  }[];
};

async function fetchJson<T>(url: string, options?: RequestInit): Promise<T> {
  const res = await fetch(url, {
    ...options,
    headers: {
      'Content-Type': 'application/json',
      ...options?.headers,
    },
  });

  if (!res.ok) {
    let errorMsg = `HTTP ${res.status}: ${res.statusText}`;
    try {
      const errJson = await res.json();
      if (errJson.message) errorMsg = errJson.message;
      else if (errJson.detail) errorMsg = errJson.detail;
    } catch {
      // ignore JSON parse error
    }
    throw new Error(errorMsg);
  }

  return res.json();
}

export const api = {
  async getHealth() {
    return fetchJson<{ status: string; database_status: string; ollama_status: string }>(`${API_BASE}/health`);
  },

  async getDashboardSummary() {
    return fetchJson<{
      metrics: {
        equity: number;
        cash: number;
        invested: number;
        unrealized_pnl: number;
        realized_pnl: number;
        total_pnl: number;
        total_pnl_pct: number;
        current_drawdown_pct: number;
        risk_status: string;
      };
      equity_curve: QuoteHistoryPoint[];
      watchlist: Quote[];
      agents: AgentCard[];
      recent_activity: Event[];
      running: boolean;
    }>(`${API_BASE}/dashboard/summary`);
  },

  async getQuotes(): Promise<Quote[]> {
    return fetchJson<Quote[]>(`${API_BASE}/market/quotes`);
  },

  async getMarketStatus(): Promise<MarketStatus> {
    return fetchJson<MarketStatus>(`${API_BASE}/market/status`);
  },

  async getPortfolio() {
    return fetchJson<{
      equity: number;
      cash: number;
      invested: number;
      positions: Position[];
      history: QuoteHistoryPoint[];
      metrics: any;
    }>(`${API_BASE}/portfolio`);
  },

  async getOrders(): Promise<Order[]> {
    return fetchJson<Order[]>(`${API_BASE}/orders`);
  },

  async getRiskConfig(): Promise<RiskConfig> {
    return fetchJson<RiskConfig>(`${API_BASE}/risk/config`);
  },

  async updateRiskConfig(config: Partial<RiskConfig>, token: string): Promise<RiskConfig> {
    return fetchJson<RiskConfig>(`${API_BASE}/risk/config`, {
      method: 'PUT',
      headers: { 'X-Hive-Operator-Token': token },
      body: JSON.stringify({
        fee_pct: config.fee,
        max_order_pct: config.maxOrder,
        max_allocation_pct: config.maxAllocation,
        drawdown_halt_pct: config.drawdown,
        auto_execute: config.auto_execute,
      }),
    });
  },

  async injectScenario(scenario: ScenarioType, symbol: string, severity: number) {
    return fetchJson<{
      scenario_id: number;
      scenario_type: ScenarioType;
      symbol: string;
      severity: number;
      outcome: Status;
      reason: string;
      headline: string;
      time: string;
      order_id?: number;
    }>(`${API_BASE}/scenarios/inject`, {
      method: 'POST',
      body: JSON.stringify({ scenario, symbol, severity }),
    });
  },

  async runDecisionPipeline(symbol: string, scenario_type?: ScenarioType, severity: number = 60) {
    return fetchJson<{
      run_id: string;
      symbol: string;
      status: string;
      current_stage: string;
      stages: { name: string; state: string; summary: string }[];
      proposal: any;
      risk_decision: any;
      execution_result: any;
      execution_mode: string;
    }>(`${API_BASE}/decisions/run`, {
      method: 'POST',
      body: JSON.stringify({ symbol, scenario_type, severity }),
    });
  },

  async getDatasets(): Promise<DatasetRecord[]> {
    return fetchJson<DatasetRecord[]>(`${API_BASE}/datasets`);
  },

  async getDatasetDetail(id: string): Promise<DatasetRecord> {
    return fetchJson<DatasetRecord>(`${API_BASE}/datasets/${id}`);
  },

  async previewCsv(csv_text: string, symbol: string = 'ASSET', timeframe: string = '1d'): Promise<any> {
    return fetchJson<any>(`${API_BASE}/datasets/preview-csv`, {
      method: 'POST',
      body: JSON.stringify({ csv_text, symbol, timeframe }),
    });
  },

  async importCsv(params: {
    csv_text: string;
    symbol: string;
    dataset_name?: string;
    asset_name?: string;
    exchange?: string;
    source?: string;
    provenance?: string;
    timeframe?: string;
  }): Promise<any> {
    return fetchJson<any>(`${API_BASE}/datasets/import-csv`, {
      method: 'POST',
      body: JSON.stringify(params),
    });
  },

  async previewDownload(symbol: string, period: string = '1y', interval: string = '1d'): Promise<any> {
    return fetchJson<any>(`${API_BASE}/datasets/download/preview`, {
      method: 'POST',
      body: JSON.stringify({ symbol, period, interval }),
    });
  },

  async executeDownload(symbol: string, period: string = '1y', interval: string = '1d'): Promise<any> {
    return fetchJson<any>(`${API_BASE}/datasets/download`, {
      method: 'POST',
      body: JSON.stringify({ symbol, period, interval }),
    });
  },

  async runBacktest(
    strategyOrParams: string | {
      strategy: string;
      symbol: string;
      timeframe?: string;
      starting_capital?: number;
      rsi_oversold?: number;
      rsi_overbought?: number;
      data_source?: 'synthetic' | 'historical';
      dataset_id?: string;
      start_date?: string;
      end_date?: string;
    },
    symbol?: string,
    timeframe?: string,
    starting_capital?: number,
    rsi_oversold?: number,
    rsi_overbought?: number
  ): Promise<BacktestResult> {
    let payload: any;
    if (typeof strategyOrParams === 'object') {
      payload = {
        strategy: strategyOrParams.strategy,
        symbol: strategyOrParams.symbol || 'RELIANCE',
        timeframe: strategyOrParams.timeframe || '1d',
        starting_capital: strategyOrParams.starting_capital || 1000000,
        rsi_oversold: strategyOrParams.rsi_oversold ?? 35.0,
        rsi_overbought: strategyOrParams.rsi_overbought ?? 65.0,
        data_source: 'historical',
        dataset_id: strategyOrParams.dataset_id,
        start_date: strategyOrParams.start_date,
        end_date: strategyOrParams.end_date,
      };
    } else {
      payload = {
        strategy: strategyOrParams,
        symbol: symbol || 'RELIANCE',
        timeframe: timeframe || '1d',
        starting_capital: starting_capital || 1000000,
        rsi_oversold: rsi_oversold ?? 35.0,
        rsi_overbought: rsi_overbought ?? 65.0,
        data_source: 'historical',
      };
    }
    return fetchJson<BacktestResult>(`${API_BASE}/backtests`, {
      method: 'POST',
      body: JSON.stringify(payload),
    });
  },

  async resetSimulation(token: string) {
    return fetchJson<{ success: boolean; message: string }>(`${API_BASE}/portfolio/reset`, {
      method: 'POST',
      headers: { 'X-Hive-Operator-Token': token },
    });
  },

  async getCandles(symbol: string = 'RELIANCE', bars: number = 60): Promise<any[]> {
    return fetchJson<any[]>(`${API_BASE}/market/candles?symbol=${encodeURIComponent(symbol)}&bars=${bars}`);
  },

  async getDecisionsHistory(): Promise<any[]> {
    return fetchJson<any[]>(`${API_BASE}/decisions/history`);
  },

  async getAgentsMonitor(): Promise<any> {
    return fetchJson<any>(`${API_BASE}/agents/monitor`);
  },

  async confirmOrder(orderId: number): Promise<any> {
    return fetchJson<any>(`${API_BASE}/orders/${orderId}/confirm`, {
      method: 'POST',
    });
  },

  /* ------------------------------------------------------------------------
   * AI Review & Continuous Improvement Endpoints
   * ------------------------------------------------------------------------ */
  async getModelStatus() {
    return fetchJson<{
      ollama_reachable: boolean;
      executor_model: string;
      executor_model_installed: boolean;
      reviewer_model: string;
      reviewer_model_installed: boolean;
      system_gpu?: string;
      vram_management: string;
      ready: boolean;
    }>(`${API_BASE}/model-status`);
  },

  async triggerAgentRun(params: { symbol: string; task_prompt?: string; task_type?: string; replay_cutoff?: string; replay_dataset_id?: string }) {
    return fetchJson<AgentRunSummary & { error_message?: string | null }>(`${API_BASE}/agent-runs`, {
      method: 'POST',
      body: JSON.stringify(params),
    });
  },

  async getAgentRuns(limit: number = 30) {
    return fetchJson<AgentRunSummary[]>(`${API_BASE}/agent-runs?limit=${limit}`);
  },

  async getRunDetail(runId: string) {
    return fetchJson<any>(`${API_BASE}/agent-runs/${encodeURIComponent(runId)}`);
  },

  async getRunEvents(runId: string) {
    return fetchJson<any[]>(`${API_BASE}/agent-runs/${encodeURIComponent(runId)}/events`);
  },

  async getEvaluationSummary() {
    return fetchJson<{
      total_runs: number;
      completed_runs: number;
      failed_runs: number;
      pass_count: number;
      flag_count: number;
      revise_count: number;
      error_count: number;
      pass_rate_pct: number;
      schema_validity_pct: number;
      evidence_grounding_pct: number;
      average_score: number;
      average_latency_ms: number;
      p95_latency_ms: number;
      revision_frequency_pct: number;
      failure_categories: Record<string, number>;
      active_prompt_version: string;
      active_prompt_hash?: string;
      active_prompt_source?: string;
      sample_sufficient_for_improvement: boolean;
      sample_size: number;
      min_threshold: number;
      total_findings_count?: number;
    }>(`${API_BASE}/agent-evaluations/summary`);
  },

  async getImprovementProposals() {
    return fetchJson<any[]>(`${API_BASE}/improvement-proposals`);
  },

  async runProposalBenchmark(proposalId: string, mode: 'auto' | 'real_llm' | 'simulation' = 'auto') {
    return fetchJson<any>(`${API_BASE}/improvement-proposals/${encodeURIComponent(proposalId)}/benchmark?mode=${mode}`, {
      method: 'POST',
    });
  },

  async generateImprovementProposal() {
    return fetchJson<any>(`${API_BASE}/improvement-proposals/generate`, {
      method: 'POST',
    });
  },

  async decideProposal(
    proposalId: string,
    action: 'approve' | 'activate' | 'reject' | 'rollback',
    token: string,
    reason: string,
  ) {
    return fetchJson<{ status: string }>(
      `${API_BASE}/improvement-proposals/${encodeURIComponent(proposalId)}/${action}`,
      { method: 'POST', headers: { 'X-Hive-Operator-Token': token }, body: JSON.stringify({ reason }) },
    );
  },

  async getPromptVersions(role: string = 'EXECUTOR') {
    return fetchJson<PromptVersion[]>(`${API_BASE}/prompt-versions?role=${encodeURIComponent(role)}`);
  },

  async getActivePromptVersion() {
    return fetchJson<ActivePromptVersionInfo>(`${API_BASE}/prompt-versions/active`);
  },

  /* ------------------------------------------------------------------------
   * DhanHQ Live Feed & Market State Endpoints
   * ------------------------------------------------------------------------ */
  async getDhanStatus() {
    return fetchJson<{
      provider: string;
      status: string;
      description: string;
      is_market_session: boolean;
      market_session_note: string;
      feed_enabled: boolean;
      credentials_configured: boolean;
      active_subscriptions: number;
      valid_ticks_count: number;
      invalid_ticks_count: number;
      dropped_ticks_count: number;
      last_connected_at: string | null;
      last_source_timestamp: string | null;
      last_ingestion_timestamp: string | null;
      staleness_threshold_seconds: number;
      error_message: string | null;
    }>(`${API_BASE}/dhan/status`);
  },

  async getDhanWatchlist() {
    return fetchJson<any[]>(`${API_BASE}/dhan/watchlist`);
  },

  async getDhanQuote(symbol: string) {
    return fetchJson<any>(`${API_BASE}/dhan/quote/${encodeURIComponent(symbol)}`);
  },

  async getDhanEvents(limit: number = 30) {
    return fetchJson<any[]>(`${API_BASE}/dhan/events?limit=${limit}`);
  },

  async triggerDhanEvent(symbol: string, reason?: string) {
    return fetchJson<any>(`${API_BASE}/dhan/trigger-event`, {
      method: 'POST',
      body: JSON.stringify({ symbol, reason }),
    });
  },

  async updateDhanConfig(config: {
    client_id?: string;
    access_token?: string;
    feed_enabled?: boolean;
    staleness_threshold_seconds?: number;
  }, token: string) {
    return fetchJson<any>(`${API_BASE}/dhan/config`, {
      method: 'POST',
      headers: { 'X-Hive-Operator-Token': token },
      body: JSON.stringify(config),
    });
  },

  /* ------------------------------------------------------------------------
   * Risk-Gated Paper-Trade Proposals Endpoints
   * ------------------------------------------------------------------------ */
  async getPaperProposals(status?: string, limit: number = 30) {
    const url = status
      ? `${API_BASE}/proposals?status=${encodeURIComponent(status)}&limit=${limit}`
      : `${API_BASE}/proposals?limit=${limit}`;
    return fetchJson<any[]>(url);
  },

  async confirmPaperProposal(proposalId: string) {
    return fetchJson<any>(`${API_BASE}/proposals/${encodeURIComponent(proposalId)}/confirm`, {
      method: 'POST',
    });
  },

  async rejectPaperProposal(proposalId: string, reason?: string) {
    return fetchJson<any>(`${API_BASE}/proposals/${encodeURIComponent(proposalId)}/reject`, {
      method: 'POST',
      body: JSON.stringify({ reason }),
    });
  },

  async getEvidenceSnapshot(snapshotId: string) {
    return fetchJson<any>(`${API_BASE}/snapshots/${encodeURIComponent(snapshotId)}`);
  },

  /* ------------------------------------------------------------------------
   * Evidence Verification & Point-in-Time Historical Replay
   * ------------------------------------------------------------------------ */
  async verifyRunEvidence(runId: string) {
    return fetchJson<any>(`${API_BASE}/review/runs/${encodeURIComponent(runId)}/evidence-verification`);
  },

  async pointInTimeReplay(symbol: string, cutoffDatetime: string, datasetId?: string) {
    return fetchJson<any>(`${API_BASE}/review/point-in-time-replay`, {
      method: 'POST',
      body: JSON.stringify({
        symbol,
        cutoff_datetime: cutoffDatetime,
        dataset_id: datasetId,
      }),
    });
  },
};
