# HIVE release security assessment

Assessed 18 November 2026. The inspected configuration supports a narrow security exception for a public source release intended for trusted local builds and static frontend deployment. The project owner accepted that exception on 18 November 2026. The development dependency still has the reported availability risk, and the full audit still fails.

## Advisory and dependency paths

[GHSA-fc5q-39xc-vjpf](https://github.com/advisories/GHSA-fc5q-39xc-vjpf) (`CVE-2026-112366`) originally reported a high-severity denial-of-service condition in Picomatch `<=4.0.7`. Crafted glob input and a crafted candidate string can trigger excessive processing in the Node process doing the matching. GitHub withdrew the advisory on 18 November 2026. The CVE record still describes the behavior, and the Picomatch maintainer closed the linked proposed fix and advised against accepting untrusted glob definitions. The root npm lockfile installs one deduplicated copy of `picomatch@4.0.7` through these paths. [CVE record](https://nvd.nist.gov/vuln/detail/CVE-2026-112366) · [Maintainer discussion](https://github.com/micromatch/picomatch/pull/235)

```text
hive-research → vite@6.4.6 → picomatch@4.0.7
hive-research → vite@6.4.6 → fdir@6.5.0 → picomatch@4.0.7 (optional peer)
hive-research → vite@6.4.6 → tinyglobby@0.2.17 → picomatch@4.0.7
hive-research → vite@6.4.6 → tinyglobby@0.2.17 → fdir@6.5.0 → picomatch@4.0.7 (optional peer)
```

The full `npm audit` was refreshed after observing the withdrawal and still exited 1 with four high-severity entries for the advisory and three dependent packages. `npm audit --omit=dev` exited 0 with zero reported vulnerabilities in the root production dependency tree. The installed code and its availability risk are unchanged by the advisory withdrawal. The optional market data sidecar's tooling is outside this root-lockfile assessment.

At assessment time the registry's latest Picomatch release was `4.0.7`, the advisory listed no patched version, and the latest Vite release (`8.3.8`) still declared `picomatch ^4.0.7`. No compatible maintained replacement was verified. The earlier disposable trial of Vite `6.2.7` restored high-severity Vite findings. The existing dependency graph and audit reporting were preserved. [Upstream Picomatch releases](https://github.com/micromatch/picomatch/releases)

## Exposure and residual risk

| Surface | Evidence and limits |
| --- | --- |
| Production runtime | Vite is declared in `devDependencies`. The two emitted JavaScript chunks contained 798 unique Rollup module IDs. None resolved to Picomatch, fdir, or tinyglobby. HIVE's frontend and Python API have no observed path from application inputs to those glob parsers. The conclusion applies to serving the compiled `dist` assets with the backend. |
| Local development and builds | Vite uses Picomatch in Node for source glob transforms, file and package matching, plugin filters, and configured filesystem rules. HIVE has no `import.meta.glob` call sites and no observed input path that supplies an untrusted glob pattern. Request paths can be tested against configured patterns. The checked-in dev server binds to `127.0.0.1`. The assessment assumes trusted source, Vite configuration, and plugins. |
| CI | No repository-owned workflow was found that runs the parser on untrusted input. The target remote returned no advertised refs. External CI and organization-level configuration were outside the observed scope. A future workflow that builds untrusted refs or accepts external glob patterns could expose the parser. |

Publishing source would leave the affected dependency in downstream development installs. A developer or runner can still incur availability and resource impact if untrusted patterns reach Vite, including through a changed checkout, configuration, or plugin. The accepted exception covers trusted local development and builds and deployment of compiled static frontend assets. Keep Vite development and preview servers local. Reassess before introducing public Vite serving, builds of untrusted refs, or untrusted pattern inputs. Any later CI design should isolate untrusted builds from trusted credentials and shared build infrastructure.

## Verification

| Check | Result |
| --- | --- |
| Backend regression | 237 passed, 0 failed, in 89.66 seconds. The suite used isolated SQLite and explicit model and market fixtures. It covers evidence integrity, benchmark promotion, approval and rollback, paper-order accounting and rejection, restart persistence, and backtest isolation. |
| Lint, types, and production build | Ruff, frontend ESLint, TypeScript, and the Vite production build passed. Vite reported the existing main bundle size warning. |
| Local model integration | Edge historical replay `RUN_61c447947b474b88bf9361f8520191a2` completed with the actual `qwen3.5:4b` executor and `hf.co/unsloth/gemma-3-4b-it-GGUF:Q4_K_M` reviewer. The reviewer returned `FLAG`. The SHA-256 recomputed from the stored evidence payload matched the persisted digest. The unavailable-market path separately persisted a failed run with a market-data error. |
| Backtesting and paper trading | Browser backtest `BT_3123dd57d9` persisted 246 observations and 10 simulated trades. Regression tests verified isolated accounting, rejected orders leaving balances intact, and provider-backed settlement with fixtures. The provider previously returned a real quote outside the exchange session. Exchange-hour provider-backed fills remain unverified. |
| Benchmark artifacts | Both recorded benchmark files were retained without rerunning or changing their scores. The linked candidate tied the baseline at 8/8, regressed on one case, and failed promotion. See [engineering verification](IMPLEMENTATION_STATUS.md) for the scope of the trials. |
| Git preflight | GitHub confirmed that `PraneshS19/Hive` was public and empty, with `main` as the default branch and push permission for the authenticated release account. The public source snapshot uses separate initial history. |

## Decision and remediation

The project owner authorized the public source release with the scoped availability-risk exception on 18 November 2026. The exception excludes untrusted pattern input, public Vite development or preview serving, and suppression of audit findings. Project license selection remains with the owner.

The public source snapshot excludes the local market archives, raw benchmark reports, screenshots, databases, local configuration, and the optional RAMM sidecar. The data source use labels and the available vendor policies do not establish permission to redistribute the ten historical CSV files. The RAMM upstream README identifies MIT, while the exact vendored revision and applicable copyright notice remain unverified. These materials remain local. [NSE data policy](https://betanseapi.nseindia.com/static/market-data/nse-data-policy) · [Yahoo terms](https://legal.yahoo.com/us/en/yahoo/terms/otos/index.html?ncid=mbr_idnedulnk00000001) · [RAMM upstream](https://github.com/0xramm/Indian-Stock-Market-API)

The public release uses a separate root commit with the release account’s GitHub noreply identity. Development history and private artifacts remain local.

Monitor the upstream releases and npm advisory feed. When a supported patch is available, use the smallest compatible dependency update, regenerate the lockfile, and confirm every path resolves outside the affected range. Rerun the full and production-only audits, lint, TypeScript, the build and module inspection, and the browser release smoke. Close the exception once the fix and checks are verified.

## Public source release verification

The isolated source snapshot passed 223 backend tests in 9.03 seconds, with 14 tests deselected because the original market archives or local verification database were excluded. The full suite passed all 237 tests in 40.77 seconds in the development checkout with those prerequisites. The release snapshot passed Ruff, Python dependency consistency checking, the locked npm install, ESLint, TypeScript, and the production build. The build reported the existing bundle-size warning. The refreshed full npm audit reported four high-severity entries tied to the withdrawn advisory. The production-only npm audit reported zero vulnerabilities.
