# Third-party references and notices

This document records the design patterns, libraries, and architectural references evaluated for HIVE. The architecture references below describe design patterns. The vendored component and its license appear in the notice section.

---

## 1. Reference Repositories Evaluated

### A. FinRobot (AI4Finance-Foundation)
- **Repository**: https://github.com/AI4Finance-Foundation/FinRobot
- **License**: Apache 2.0
- **Adapted Patterns**:
  - **Separation of Concerns**: Strict architectural boundary between quantitative/deterministic calculations (OHLCV indicators, portfolio metrics, risk limits) and cognitive agent reasoning.
  - **Structured Financial Reporting**: Typed output schemas for market analysis, risk evaluation, and investment proposals.
  - **Auditability**: Traceable inputs and outputs for every agent execution step.

### B. TradingAgents (TauricResearch)
- **Repository**: https://github.com/TauricResearch/TradingAgents
- **License**: Apache 2.0
- **Adapted Patterns**:
  - **Specialist Agent Roles**: Clear division into Market Analyst (technical and price action), Sentiment Analyst (news and headline signals), and Portfolio Manager (synthesis and allocation proposal).
  - **Independent Risk Gate**: The Portfolio Manager does *not* execute orders; an independent deterministic Risk Gate validates and sizes or rejects all proposals before simulated execution.

### C. FastAPI (tiangolo)
- **Repository**: https://github.com/fastapi/fastapi
- **License**: MIT
- **Role in HIVE**:
  - Foundation of the HIVE Python backend.
  - Asynchronous route handlers, Pydantic v2 data validation, OpenAPI specification, dependency injection for database sessions and services.

### D. backtesting.py (kernc)
- **Repository**: https://github.com/kernc/backtesting.py
- **License**: AGPL-3.0
- **Evaluation & Decision**:
  - Studied for event-driven bar simulation, trade lifecycle tracking, and equity curve computation without look-ahead bias.
  - Due to AGPL-3.0 copyleft restrictions and the requirement for lightweight, zero-overhead simulation, a clean, self-contained vectorized and event-driven backtesting engine was implemented natively using NumPy and pandas, avoiding AGPL licensing complications.

### E. VectorBT (polakowo)
- **Repository**: https://github.com/polakowo/vectorbt
- **License**: Apache 2.0 with Commons Clause
- **Evaluation & Decision**:
  - Studied for vector calculation of technical indicators (SMA, EMA, RSI, MACD, Bollinger Bands, Drawdown) and performance metrics (Sharpe ratio, max drawdown, win rate).
  - Natively implemented clean pandas/NumPy vector operations in `market/indicators.py` to minimize heavy external binary dependencies on laptop hardware.

### F. Lightweight Paper-Trading Bot (Om7398)
- **Repository**: https://github.com/Om7398/trading-bot
- **License**: MIT
- **Adapted Patterns**:
  - SQLite persistent ledger architecture with SQLAlchemy 2.0.
  - Order state machine: `PROPOSAL` -> `APPROVED` / `RESIZED` / `REJECTED` -> `FILLED`.
  - Atomic transaction handling for cash balances and position holdings.

---

## 2. Hardware and Local AI Constraints

- **Hardware Target**: NVIDIA RTX 4050 Laptop GPU (6 GB VRAM), Intel Core i5 (13th Gen), 16 GB RAM, Windows 11.
- **AI Policy**:
  - Zero cloud/paid API dependencies (no Gemini, OpenAI, or third-party paid keys).
  - Optional local LLM via Ollama (`http://localhost:11434`), defaulting to compact 3Bâ€“4B quantized models (e.g. `llama3.2:3b`, `qwen2.5:3b`).
  - The review workflow reports local inference failures explicitly and retains applicable deterministic results.

## 3. Motion-Primitives Text Roll

HIVE adapts [Text Roll from Motion-Primitives](https://github.com/ibelick/motion-primitives/blob/main/components/core/text-roll.tsx) in `src/components/ui/text-roll.tsx`. Keep the following notice with distributions that include this component.

MIT License

Copyright (c) 2024 ibelick

Permission is hereby granted, free of charge, to any person obtaining a copy
of this software and associated documentation files (the "Software"), to deal
in the Software without restriction, including without limitation the rights
to use, copy, modify, merge, publish, distribute, sublicense, and/or sell
copies of the Software, and to permit persons to whom the Software is
furnished to do so, subject to the following conditions:

The above copyright notice and this permission notice shall be included in all
copies or substantial portions of the Software.

THE SOFTWARE IS PROVIDED "AS IS", WITHOUT WARRANTY OF ANY KIND, EXPRESS OR
IMPLIED, INCLUDING BUT NOT LIMITED TO THE WARRANTIES OF MERCHANTABILITY,
FITNESS FOR A PARTICULAR PURPOSE AND NONINFRINGEMENT. IN NO EVENT SHALL THE
AUTHORS OR COPYRIGHT HOLDERS BE LIABLE FOR ANY CLAIM, DAMAGES OR OTHER
LIABILITY, WHETHER IN AN ACTION OF CONTRACT, TORT OR OTHERWISE, ARISING FROM,
OUT OF OR IN CONNECTION WITH THE SOFTWARE OR THE USE OR OTHER DEALINGS IN THE
SOFTWARE.
app/page.tsx
