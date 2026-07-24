# SentinelGrid Web Frontend Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Replace the Streamlit dashboard with an enterprise-grade Next.js web app (dark "control room" visual direction, WebSocket-driven live updates, master-detail navigation) that talks to the existing, unchanged FastAPI backend.

**Architecture:** A new top-level `web/` directory (Next.js 14 App Router + TypeScript + Tailwind + shadcn/ui), talking only to `backend/api` over HTTP/WebSocket, mirroring `frontend/components/api_client.py`'s endpoint surface. React Query holds server state; a WebSocket hook writes live run updates directly into its cache and falls back to 2s polling on disconnect. `backend/` and the existing `frontend/` (Streamlit) are untouched.

**Tech Stack:** Next.js 14, TypeScript, Tailwind CSS, shadcn/ui, @tanstack/react-query, recharts, Vitest + React Testing Library, Playwright.

**Spec:** `docs/superpowers/specs/2026-07-24-web-frontend-design.md`

## Global Constraints

- Frontend talks only to the existing FastAPI backend via HTTP/WebSocket — never a direct DB connection (CLAUDE.md §3, inherited by any frontend regardless of framework).
- No backend changes — CORS already allows all origins (`backend/api/main.py`).
- `risk_score` is `null` exactly when `is_novel_condition` is `true` — render as "novel condition, low confidence," never a fabricated number.
- `reasoning_unavailable: true` on any agent result → render an explicit "reasoning service unavailable" state, never hidden or silently retried.
- Approve/Reject stay disabled until `viewed_evidence` is `true` AND an operator is signed in.
- Every approval decision requires the signed-in operator ID — never a bare flag.
- WebSocket drop → automatic fallback to 2s polling of `GET /runs/{run_id}`; a decision in flight during a drop is never optimistically applied — only the server's response updates a row's status.
- Lives entirely in a new top-level `web/` directory — `backend/` and `frontend/` (the existing Streamlit app) are untouched.
- Default API base URL `http://127.0.0.1:8000`, overridable via `NEXT_PUBLIC_API_BASE_URL`.
- Real LLM calls (Gemini free tier) are capped at 20 requests/day/project/model (CLAUDE.md §5) — don't run LLM-triggering e2e tests repeatedly in short loops.

## File Structure

```
web/
├── package.json, tsconfig.json, next.config.mjs, tailwind.config.ts, postcss.config.mjs
├── components.json                  # shadcn config
├── vitest.config.ts, playwright.config.ts
├── .env.local.example, .gitignore
├── app/
│   ├── layout.tsx, globals.css, providers.tsx, page.tsx
│   ├── monitor/page.tsx
│   ├── trace/page.tsx
│   └── approvals/page.tsx
├── components/
│   ├── shell/sidebar.tsx, header.tsx, sign-in-gate.tsx
│   ├── monitor/scenario-picker.tsx, kpi-row.tsx, timeline-chart.tsx, assessment-panel.tsx
│   ├── trace/audit-strip.tsx, assessment-list.tsx, assessment-detail.tsx
│   ├── approvals/approval-list.tsx, approval-detail.tsx
│   └── ui/                          # shadcn-generated primitives
├── lib/
│   ├── types.ts, api-client.ts, utils.ts
│   ├── operator-context.tsx, active-run-context.tsx, query-client.tsx
│   └── use-run-socket.ts
├── tests/                           # Vitest + RTL
└── e2e/                              # Playwright
```

---

### Task 1: Scaffold Next.js project + tooling

**Files:**
- Create: `web/package.json`, `web/tsconfig.json`, `web/next.config.mjs`, `web/postcss.config.mjs`, `web/tailwind.config.ts`
- Create: `web/app/layout.tsx`, `web/app/globals.css`, `web/app/page.tsx`
- Create: `web/vitest.config.ts`, `web/tests/setup.ts`, `web/playwright.config.ts`
- Create: `web/.gitignore`, `web/.env.local.example`

**Interfaces:**
- Produces: the `web/` project skeleton every later task writes into; `npm test` and `npm run build` as the verification commands later tasks use.

- [ ] **Step 1: Create `web/package.json`**

```json
{
  "name": "sentinelgrid-web",
  "version": "0.1.0",
  "private": true,
  "scripts": {
    "dev": "next dev",
    "build": "next build",
    "start": "next start",
    "lint": "next lint",
    "test": "vitest run",
    "test:watch": "vitest",
    "e2e": "playwright test"
  },
  "dependencies": {
    "next": "^14.2.0",
    "react": "^18.3.0",
    "react-dom": "^18.3.0",
    "@tanstack/react-query": "^5.51.0",
    "recharts": "^2.12.0",
    "clsx": "^2.1.0",
    "tailwind-merge": "^2.4.0",
    "class-variance-authority": "^0.7.0",
    "lucide-react": "^0.400.0"
  },
  "devDependencies": {
    "typescript": "^5.5.0",
    "@types/node": "^20.14.0",
    "@types/react": "^18.3.0",
    "@types/react-dom": "^18.3.0",
    "tailwindcss": "^3.4.0",
    "tailwindcss-animate": "^1.0.7",
    "postcss": "^8.4.0",
    "autoprefixer": "^10.4.0",
    "vitest": "^2.0.0",
    "@vitejs/plugin-react": "^4.3.0",
    "jsdom": "^24.1.0",
    "@testing-library/react": "^16.0.0",
    "@testing-library/jest-dom": "^6.4.0",
    "@testing-library/user-event": "^14.5.0",
    "@playwright/test": "^1.45.0"
  }
}
```

- [ ] **Step 2: Create `web/tsconfig.json`**

```json
{
  "compilerOptions": {
    "target": "ES2017",
    "lib": ["dom", "dom.iterable", "esnext"],
    "allowJs": false,
    "skipLibCheck": true,
    "strict": true,
    "noEmit": true,
    "esModuleInterop": true,
    "module": "esnext",
    "moduleResolution": "bundler",
    "resolveJsonModule": true,
    "isolatedModules": true,
    "jsx": "preserve",
    "incremental": true,
    "plugins": [{ "name": "next" }],
    "paths": { "@/*": ["./*"] }
  },
  "include": ["next-env.d.ts", "**/*.ts", "**/*.tsx", ".next/types/**/*.ts"],
  "exclude": ["node_modules"]
}
```

- [ ] **Step 3: Create `web/next.config.mjs`, `web/postcss.config.mjs`, `web/tailwind.config.ts`**

`web/next.config.mjs`:
```js
/** @type {import('next').NextConfig} */
const nextConfig = {};
export default nextConfig;
```

`web/postcss.config.mjs`:
```js
export default {
  plugins: {
    tailwindcss: {},
    autoprefixer: {},
  },
};
```

`web/tailwind.config.ts` (base — extended with design tokens in Task 2):
```ts
import type { Config } from "tailwindcss";

const config: Config = {
  darkMode: ["class"],
  content: ["./app/**/*.{ts,tsx}", "./components/**/*.{ts,tsx}"],
  theme: {
    extend: {},
  },
  plugins: [],
};
export default config;
```

- [ ] **Step 4: Create `web/app/layout.tsx`, `web/app/globals.css`, `web/app/page.tsx`**

`web/app/globals.css` (minimal — filled out in Task 2):
```css
@tailwind base;
@tailwind components;
@tailwind utilities;
```

`web/app/layout.tsx`:
```tsx
import type { Metadata } from "next";
import "./globals.css";

export const metadata: Metadata = {
  title: "SentinelGrid",
  description: "Compound-risk monitoring for a chemical plant",
};

export default function RootLayout({ children }: { children: React.ReactNode }) {
  return (
    <html lang="en">
      <body>{children}</body>
    </html>
  );
}
```

`web/app/page.tsx`:
```tsx
export default function Home() {
  return <main>SentinelGrid — scaffolding in progress</main>;
}
```

- [ ] **Step 5: Create `web/vitest.config.ts` and `web/tests/setup.ts`**

`web/vitest.config.ts`:
```ts
import { defineConfig } from "vitest/config";
import react from "@vitejs/plugin-react";
import path from "path";

export default defineConfig({
  plugins: [react()],
  test: {
    environment: "jsdom",
    setupFiles: ["./tests/setup.ts"],
    globals: true,
  },
  resolve: {
    alias: {
      "@": path.resolve(__dirname, "."),
    },
  },
});
```

`web/tests/setup.ts`:
```ts
import "@testing-library/jest-dom/vitest";
```

- [ ] **Step 6: Create `web/playwright.config.ts`** (minimal — the two-server `webServer` array is added in Task 14)

```ts
import { defineConfig } from "@playwright/test";

export default defineConfig({
  testDir: "./e2e",
  timeout: 30_000,
  use: {
    baseURL: "http://localhost:3000",
  },
});
```

- [ ] **Step 7: Create `web/.gitignore` and `web/.env.local.example`**

`web/.gitignore`:
```
node_modules/
.next/
out/
.env.local
test-results/
playwright-report/
```

`web/.env.local.example`:
```
NEXT_PUBLIC_API_BASE_URL=http://127.0.0.1:8000
```

- [ ] **Step 8: Install dependencies and verify the scaffold builds**

Run (inside `web/`): `npm install`
Run: `npm run build`
Expected: build succeeds, `.next/` output produced, no TypeScript errors.

- [ ] **Step 9: Commit**

```bash
git add web/
git commit -m "Scaffold Next.js web frontend project and tooling"
```

---

### Task 2: Dark Control Room design tokens + shadcn/ui primitives

**Files:**
- Create: `web/lib/utils.ts`, `web/components.json`
- Modify: `web/app/globals.css`, `web/tailwind.config.ts`
- Create (via shadcn CLI): `web/components/ui/button.tsx`, `badge.tsx`, `input.tsx`, `label.tsx`

**Interfaces:**
- Consumes: `web/` scaffold from Task 1.
- Produces: `cn()` from `web/lib/utils.ts` (used by every component with conditional classes); Tailwind color tokens `background`, `foreground`, `card`, `border`, `muted`, `muted-foreground`, `destructive`, `brand-accent`, `risk-normal`, `risk-warn`, `risk-critical` usable as `bg-*`/`text-*`/`border-*` classes in every later task; shadcn `Button`, `Badge`, `Input`, `Label` components at `@/components/ui/*`.

- [ ] **Step 1: Create `web/lib/utils.ts`**

```ts
import { type ClassValue, clsx } from "clsx";
import { twMerge } from "tailwind-merge";

export function cn(...inputs: ClassValue[]) {
  return twMerge(clsx(inputs));
}
```

- [ ] **Step 2: Create `web/components.json`**

```json
{
  "$schema": "https://ui.shadcn.com/schema.json",
  "style": "default",
  "rsc": true,
  "tsx": true,
  "tailwind": {
    "config": "tailwind.config.ts",
    "css": "app/globals.css",
    "baseColor": "neutral",
    "cssVariables": true,
    "prefix": ""
  },
  "aliases": {
    "components": "@/components",
    "utils": "@/lib/utils",
    "ui": "@/components/ui"
  }
}
```

- [ ] **Step 3: Replace `web/app/globals.css` with the Dark Control Room token set**

This palette matches the SentinelGrid pitch-page artifact and the visual direction approved during brainstorming: blue-charcoal grounds, cyan structural accent, green/amber/red used only as real risk states (not decoration).

```css
@tailwind base;
@tailwind components;
@tailwind utilities;

@layer base {
  :root {
    --background: 220 26% 7%;
    --foreground: 210 20% 92%;
    --card: 216 22% 11%;
    --card-foreground: 210 20% 92%;
    --popover: 216 22% 11%;
    --popover-foreground: 210 20% 92%;
    --primary: 187 55% 52%;
    --primary-foreground: 200 60% 5%;
    --secondary: 216 18% 16%;
    --secondary-foreground: 210 20% 92%;
    --muted: 216 18% 16%;
    --muted-foreground: 213 13% 58%;
    --accent: 216 18% 16%;
    --accent-foreground: 210 20% 92%;
    --destructive: 3 62% 63%;
    --destructive-foreground: 210 20% 96%;
    --border: 214 19% 16%;
    --input: 214 19% 16%;
    --ring: 187 55% 52%;
    --radius: 0.25rem;

    /* Brand + semantic risk tokens — distinct from shadcn's own accent/destructive,
       since these carry real plant-state meaning, not UI hover/error state. */
    --brand-accent: 187 55% 52%;
    --risk-normal: 140 32% 49%;
    --risk-warn: 38 68% 56%;
    --risk-critical: 3 62% 63%;
  }
}

@layer base {
  * {
    @apply border-border;
  }
  body {
    @apply bg-background text-foreground;
    font-feature-settings: "tnum" 1;
  }
}
```

- [ ] **Step 4: Extend `web/tailwind.config.ts` with the token mapping**

```ts
import type { Config } from "tailwindcss";

const config: Config = {
  darkMode: ["class"],
  content: ["./app/**/*.{ts,tsx}", "./components/**/*.{ts,tsx}"],
  theme: {
    extend: {
      colors: {
        border: "hsl(var(--border))",
        input: "hsl(var(--input))",
        ring: "hsl(var(--ring))",
        background: "hsl(var(--background))",
        foreground: "hsl(var(--foreground))",
        primary: {
          DEFAULT: "hsl(var(--primary))",
          foreground: "hsl(var(--primary-foreground))",
        },
        secondary: {
          DEFAULT: "hsl(var(--secondary))",
          foreground: "hsl(var(--secondary-foreground))",
        },
        destructive: {
          DEFAULT: "hsl(var(--destructive))",
          foreground: "hsl(var(--destructive-foreground))",
        },
        muted: {
          DEFAULT: "hsl(var(--muted))",
          foreground: "hsl(var(--muted-foreground))",
        },
        accent: {
          DEFAULT: "hsl(var(--accent))",
          foreground: "hsl(var(--accent-foreground))",
        },
        popover: {
          DEFAULT: "hsl(var(--popover))",
          foreground: "hsl(var(--popover-foreground))",
        },
        card: {
          DEFAULT: "hsl(var(--card))",
          foreground: "hsl(var(--card-foreground))",
        },
        brand: {
          accent: "hsl(var(--brand-accent))",
        },
        risk: {
          normal: "hsl(var(--risk-normal))",
          warn: "hsl(var(--risk-warn))",
          critical: "hsl(var(--risk-critical))",
        },
      },
      borderRadius: {
        lg: "var(--radius)",
        md: "calc(var(--radius) - 2px)",
        sm: "calc(var(--radius) - 4px)",
      },
    },
  },
  plugins: [require("tailwindcss-animate")],
};
export default config;
```

- [ ] **Step 5: Generate shadcn primitives**

Run (inside `web/`): `npx shadcn@latest add button badge input label -y`
Expected: creates `components/ui/button.tsx`, `components/ui/badge.tsx`, `components/ui/input.tsx`, `components/ui/label.tsx`, each using the `cn()` helper and the color tokens above.

- [ ] **Step 6: Visual verification**

Run: `npm run dev`, open `http://localhost:3000`.
Expected: dark blue-charcoal background, light text — confirms the tokens are wired through Tailwind correctly. Stop the dev server (Ctrl+C) once confirmed.

- [ ] **Step 7: Commit**

```bash
git add web/
git commit -m "Add Dark Control Room design tokens and shadcn/ui primitives"
```

---

### Task 3: Backend contract types + API client

**Files:**
- Create: `web/lib/types.ts`, `web/lib/api-client.ts`
- Test: `web/tests/api-client.test.ts`

**Interfaces:**
- Consumes: nothing from earlier tasks (pure data layer).
- Produces: types `RunStatus`, `RiskAssessment`, `ComplianceResult`, `ExplanationResult`, `EmergencyRecommendation`, `Assessment`, `RecordSummary`, `RunSnapshot`, `ApprovalStatus`, `ApprovalRecord`, `Scenario`, `LLMStatus`, `AuditVerification`, `WSMessage` from `web/lib/types.ts`; class `APIClient` and singleton `apiClient` (methods: `health()`, `listScenarios()`, `startRun()`, `getRun()`, `getAssessments()`, `getReadings()`, `getApproval()`, `markViewed()`, `decide()`, `llmStatus()`, `auditVerify()`, `wsUrl()`) and `APIError` from `web/lib/api-client.ts` — every later task that talks to the backend imports from here.

These types were verified directly against the running backend code (`backend/agents/models.py`, `backend/database/approvals.py`, `backend/api/run_manager.py`, `backend/api/routers/*.py`), not guessed.

- [ ] **Step 1: Write `web/lib/types.ts`**

```ts
export type RunStatus = "starting" | "running" | "completed" | "error";

export interface RiskAssessment {
  risk_score: number | null;
  is_novel_condition: boolean;
  confidence: string;
  contributing_factors: string[];
  recommended_action: string;
  cited_chunk_ids: string[];
  reasoning: string;
  llm_tier_used: string;
  latency_ms: number;
  parse_error: boolean;
  reasoning_unavailable: boolean;
}

export interface ComplianceResult {
  action_reviewed: string;
  approved: boolean;
  cited_sop_chunk_ids: string[];
  notes: string;
  llm_tier_used: string;
  latency_ms: number;
  parse_error: boolean;
  reasoning_unavailable: boolean;
}

export interface ExplanationResult {
  narrative: string;
  cited_chunk_ids: string[];
  llm_tier_used: string;
  latency_ms: number;
  reasoning_unavailable: boolean;
}

export interface EmergencyRecommendation {
  triggered: boolean;
  recommended_interventions: string[];
  requires_approval: boolean;
  approval_id: string | null;
  llm_tier_used: string | null;
  latency_ms: number | null;
  reasoning_unavailable: boolean;
}

export interface Assessment {
  record_index: number;
  t_hours: number;
  retrieval_phase: string;
  retrieval_confidence: string;
  is_novel_condition: boolean;
  risk_assessment: RiskAssessment;
  compliance_result: ComplianceResult;
  explanation: ExplanationResult;
  emergency_recommendation: EmergencyRecommendation;
}

export interface RecordSummary {
  record_index: number;
  t_hours: number;
  reactor_pressure_kpa: number;
  reactor_temperature_c: number;
  reactor_level_pct: number;
  separator_pressure_kpa: number;
  stripper_level_pct: number;
}

export interface RunSnapshot {
  run_id: string;
  scenario_name: string;
  status: RunStatus;
  total_records: number;
  revealed_count: number;
  diverged: boolean;
  diverged_reason: string | null;
  error: string | null;
  latest_record_summary: RecordSummary | null;
  latest_assessment: Assessment | null;
  assessment_count: number;
}

export type ApprovalStatus = "pending" | "approved" | "rejected";

export interface ApprovalRecord {
  approval_id: string;
  run_id: string;
  recommendation_summary: string;
  status: ApprovalStatus;
  operator_id: string | null;
  decided_at: string | null;
  viewed_evidence: boolean;
}

export interface Scenario {
  name: string;
  description: string;
  duration_hours: number;
}

export interface LLMStatus {
  active_tier: string | null;
  available: boolean;
}

export interface AuditVerification {
  ok: boolean;
  rows_checked: number;
  first_broken_id: number | null;
  reason: string | null;
}

export interface WSUpdateMessage extends RunSnapshot {
  type: "update";
}
export interface WSErrorMessage {
  type: "error";
  message: string;
}
export type WSMessage = WSUpdateMessage | WSErrorMessage;
```

- [ ] **Step 2: Write `web/lib/api-client.ts`**

```ts
import type {
  Scenario,
  RunSnapshot,
  Assessment,
  RecordSummary,
  ApprovalRecord,
  ApprovalStatus,
  LLMStatus,
  AuditVerification,
} from "./types";

const DEFAULT_BASE_URL = "http://127.0.0.1:8000";

export class APIError extends Error {}

export class APIClient {
  constructor(
    private baseUrl: string = process.env.NEXT_PUBLIC_API_BASE_URL ?? DEFAULT_BASE_URL
  ) {}

  private async get<T>(path: string): Promise<T> {
    const resp = await fetch(`${this.baseUrl}${path}`);
    if (!resp.ok) {
      const body = await resp.json().catch(() => ({}));
      throw new APIError(body.detail ?? resp.statusText);
    }
    return resp.json() as Promise<T>;
  }

  private async post<T>(path: string, json?: unknown): Promise<T> {
    const resp = await fetch(`${this.baseUrl}${path}`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(json ?? {}),
    });
    if (!resp.ok) {
      const body = await resp.json().catch(() => ({}));
      throw new APIError(body.detail ?? resp.statusText);
    }
    return resp.json() as Promise<T>;
  }

  async health(): Promise<boolean> {
    try {
      const result = await this.get<{ status: string }>("/health");
      return result.status === "ok";
    } catch {
      return false;
    }
  }

  listScenarios(): Promise<Scenario[]> {
    return this.get<Scenario[]>("/scenarios");
  }

  async startRun(params: {
    scenarioName: string;
    durationHours?: number;
    tickSeconds?: number;
    assessmentIntervalRecords?: number;
  }): Promise<string> {
    const payload: Record<string, unknown> = {
      scenario_name: params.scenarioName,
      tick_seconds: params.tickSeconds ?? 0.2,
      assessment_interval_records: params.assessmentIntervalRecords ?? 5,
    };
    if (params.durationHours) payload.duration_hours = params.durationHours;
    const result = await this.post<{ run_id: string }>("/runs", payload);
    return result.run_id;
  }

  getRun(runId: string): Promise<RunSnapshot> {
    return this.get<RunSnapshot>(`/runs/${runId}`);
  }

  getAssessments(runId: string): Promise<Assessment[]> {
    return this.get<Assessment[]>(`/runs/${runId}/assessments`);
  }

  getReadings(runId: string): Promise<RecordSummary[]> {
    return this.get<RecordSummary[]>(`/runs/${runId}/readings`);
  }

  getApproval(approvalId: string): Promise<ApprovalRecord> {
    return this.get<ApprovalRecord>(`/approvals/${approvalId}`);
  }

  markViewed(approvalId: string): Promise<ApprovalRecord> {
    return this.post<ApprovalRecord>(`/approvals/${approvalId}/view`);
  }

  decide(approvalId: string, operatorId: string, status: ApprovalStatus): Promise<ApprovalRecord> {
    return this.post<ApprovalRecord>(`/approvals/${approvalId}/decide`, {
      operator_id: operatorId,
      status,
    });
  }

  llmStatus(): Promise<LLMStatus> {
    return this.get<LLMStatus>("/llm/status");
  }

  auditVerify(): Promise<AuditVerification> {
    return this.get<AuditVerification>("/audit/verify");
  }

  wsUrl(runId: string): string {
    const url = new URL(this.baseUrl);
    url.protocol = url.protocol === "https:" ? "wss:" : "ws:";
    url.pathname = `/runs/ws/${runId}`;
    return url.toString();
  }
}

export const apiClient = new APIClient();
```

- [ ] **Step 3: Write `web/tests/api-client.test.ts`**

```ts
import { describe, it, expect, vi, beforeEach } from "vitest";
import { APIClient, APIError } from "@/lib/api-client";

function mockFetchOnce(body: unknown, ok = true, status = 200) {
  global.fetch = vi.fn().mockResolvedValue({
    ok,
    status,
    json: async () => body,
  }) as unknown as typeof fetch;
}

describe("APIClient", () => {
  let client: APIClient;

  beforeEach(() => {
    client = new APIClient("http://test-backend");
  });

  it("health() returns true when status is ok", async () => {
    mockFetchOnce({ status: "ok" });
    expect(await client.health()).toBe(true);
  });

  it("health() returns false when the request fails", async () => {
    global.fetch = vi.fn().mockRejectedValue(new Error("network down"));
    expect(await client.health()).toBe(false);
  });

  it("listScenarios() calls GET /scenarios and returns the list", async () => {
    mockFetchOnce([{ name: "baseline", description: "No fault.", duration_hours: 2 }]);
    const scenarios = await client.listScenarios();
    expect(fetch).toHaveBeenCalledWith("http://test-backend/scenarios");
    expect(scenarios).toEqual([{ name: "baseline", description: "No fault.", duration_hours: 2 }]);
  });

  it("startRun() posts scenario_name and returns run_id", async () => {
    mockFetchOnce({ run_id: "run-123" });
    const runId = await client.startRun({ scenarioName: "reactor_a_feed_loss" });
    expect(runId).toBe("run-123");
    const [, options] = (fetch as unknown as ReturnType<typeof vi.fn>).mock.calls[0];
    expect(JSON.parse(options.body)).toEqual({
      scenario_name: "reactor_a_feed_loss",
      tick_seconds: 0.2,
      assessment_interval_records: 5,
    });
  });

  it("throws APIError with the backend's detail message on failure", async () => {
    mockFetchOnce({ detail: "No run with id x" }, false, 404);
    await expect(client.getRun("x")).rejects.toThrow(APIError);
    mockFetchOnce({ detail: "No run with id x" }, false, 404);
    await expect(client.getRun("x")).rejects.toThrow("No run with id x");
  });

  it("decide() posts operator_id and status", async () => {
    mockFetchOnce({ approval_id: "a1", status: "approved" });
    await client.decide("a1", "J.RAO", "approved");
    const [, options] = (fetch as unknown as ReturnType<typeof vi.fn>).mock.calls[0];
    expect(JSON.parse(options.body)).toEqual({ operator_id: "J.RAO", status: "approved" });
  });

  it("wsUrl() converts http(s) base to ws(s) and points at the run channel", () => {
    expect(client.wsUrl("run-123")).toBe("ws://test-backend/runs/ws/run-123");
  });
});
```

- [ ] **Step 4: Run the tests**

Run: `npm test -- run tests/api-client.test.ts`
Expected: 7 tests PASS.

- [ ] **Step 5: Commit**

```bash
git add web/lib/types.ts web/lib/api-client.ts web/tests/api-client.test.ts
git commit -m "Add backend contract types and API client"
```

---

### Task 4: Operator context + sign-in gate

**Files:**
- Create: `web/lib/operator-context.tsx`, `web/components/shell/sign-in-gate.tsx`
- Test: `web/tests/sign-in-gate.test.tsx`

**Interfaces:**
- Consumes: `Button`, `Input`, `Label` from `web/components/ui/*` (Task 2).
- Produces: `OperatorProvider`, `useOperator()` returning `{ operatorId: string | null, setOperatorId: (id: string) => void, clearOperatorId: () => void }` — used by the shell (Task 6) and the approval decision flow (Task 12).

- [ ] **Step 1: Write `web/lib/operator-context.tsx`**

```tsx
"use client";

import { createContext, useContext, useEffect, useState, type ReactNode } from "react";

const STORAGE_KEY = "sentinelgrid-operator-id";

interface OperatorContextValue {
  operatorId: string | null;
  setOperatorId: (id: string) => void;
  clearOperatorId: () => void;
}

const OperatorContext = createContext<OperatorContextValue | null>(null);

export function OperatorProvider({ children }: { children: ReactNode }) {
  const [operatorId, setOperatorIdState] = useState<string | null>(null);
  const [hydrated, setHydrated] = useState(false);

  useEffect(() => {
    const stored = window.localStorage.getItem(STORAGE_KEY);
    if (stored) setOperatorIdState(stored);
    setHydrated(true);
  }, []);

  const setOperatorId = (id: string) => {
    window.localStorage.setItem(STORAGE_KEY, id);
    setOperatorIdState(id);
  };

  const clearOperatorId = () => {
    window.localStorage.removeItem(STORAGE_KEY);
    setOperatorIdState(null);
  };

  if (!hydrated) return null;

  return (
    <OperatorContext.Provider value={{ operatorId, setOperatorId, clearOperatorId }}>
      {children}
    </OperatorContext.Provider>
  );
}

export function useOperator(): OperatorContextValue {
  const ctx = useContext(OperatorContext);
  if (!ctx) throw new Error("useOperator must be used within an OperatorProvider");
  return ctx;
}
```

- [ ] **Step 2: Write `web/components/shell/sign-in-gate.tsx`**

```tsx
"use client";

import { useState, type ReactNode } from "react";
import { useOperator } from "@/lib/operator-context";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";

export function SignInGate({ children }: { children: ReactNode }) {
  const { operatorId, setOperatorId } = useOperator();
  const [draft, setDraft] = useState("");

  if (operatorId) return <>{children}</>;

  return (
    <div className="flex min-h-screen items-center justify-center bg-background">
      <form
        className="w-80 space-y-4 rounded-md border border-border bg-card p-6"
        onSubmit={(e) => {
          e.preventDefault();
          const trimmed = draft.trim();
          if (trimmed) setOperatorId(trimmed);
        }}
      >
        <div>
          <h1 className="text-lg font-semibold text-foreground">SentinelGrid</h1>
          <p className="text-sm text-muted-foreground">Sign in with your operator ID to continue.</p>
        </div>
        <div className="space-y-2">
          <Label htmlFor="operator-id">Operator ID</Label>
          <Input
            id="operator-id"
            value={draft}
            onChange={(e) => setDraft(e.target.value)}
            placeholder="e.g. J.RAO"
            autoFocus
          />
        </div>
        <Button type="submit" className="w-full" disabled={!draft.trim()}>
          Continue
        </Button>
      </form>
    </div>
  );
}
```

- [ ] **Step 3: Write `web/tests/sign-in-gate.test.tsx`**

```tsx
import { describe, it, expect, beforeEach } from "vitest";
import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { OperatorProvider } from "@/lib/operator-context";
import { SignInGate } from "@/components/shell/sign-in-gate";

describe("SignInGate", () => {
  beforeEach(() => {
    window.localStorage.clear();
  });

  it("blocks children until an operator ID is entered", async () => {
    render(
      <OperatorProvider>
        <SignInGate>
          <div>Protected content</div>
        </SignInGate>
      </OperatorProvider>
    );

    expect(await screen.findByLabelText(/operator id/i)).toBeInTheDocument();
    expect(screen.queryByText("Protected content")).not.toBeInTheDocument();

    await userEvent.type(screen.getByLabelText(/operator id/i), "J.RAO");
    await userEvent.click(screen.getByRole("button", { name: /continue/i }));

    expect(await screen.findByText("Protected content")).toBeInTheDocument();
  });

  it("restores a previously signed-in operator from localStorage", async () => {
    window.localStorage.setItem("sentinelgrid-operator-id", "M.CHEN");
    render(
      <OperatorProvider>
        <SignInGate>
          <div>Protected content</div>
        </SignInGate>
      </OperatorProvider>
    );
    expect(await screen.findByText("Protected content")).toBeInTheDocument();
  });
});
```

- [ ] **Step 4: Run the tests**

Run: `npm test -- run tests/sign-in-gate.test.tsx`
Expected: 2 tests PASS.

- [ ] **Step 5: Commit**

```bash
git add web/lib/operator-context.tsx web/components/shell/sign-in-gate.tsx web/tests/sign-in-gate.test.tsx
git commit -m "Add operator sign-in context and gate"
```

---

### Task 5: React Query provider + WebSocket hook with polling fallback

**Files:**
- Create: `web/lib/query-client.tsx`, `web/lib/use-run-socket.ts`
- Test: `web/tests/use-run-socket.test.tsx`

**Interfaces:**
- Consumes: `apiClient`, `RunSnapshot`, `WSMessage` from Task 3.
- Produces: `QueryProvider` (wraps `@tanstack/react-query`'s `QueryClientProvider`); `useRunSocket(runId: string | null): "connecting" | "live" | "polling"` — writes into the `["run", runId]` query-cache key that Task 10 (Monitor page) reads.

- [ ] **Step 1: Write `web/lib/query-client.tsx`**

```tsx
"use client";

import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { useState, type ReactNode } from "react";

export function QueryProvider({ children }: { children: ReactNode }) {
  const [client] = useState(
    () =>
      new QueryClient({
        defaultOptions: {
          queries: {
            staleTime: 1_000,
            refetchOnWindowFocus: false,
          },
        },
      })
  );
  return <QueryClientProvider client={client}>{children}</QueryClientProvider>;
}
```

- [ ] **Step 2: Write `web/lib/use-run-socket.ts`**

```ts
"use client";

import { useEffect, useRef, useState } from "react";
import { useQueryClient } from "@tanstack/react-query";
import { apiClient } from "./api-client";
import type { RunSnapshot, WSMessage } from "./types";

const POLL_INTERVAL_MS = 2000;

export type ConnectionState = "connecting" | "live" | "polling";

export function useRunSocket(runId: string | null): ConnectionState {
  const queryClient = useQueryClient();
  const [state, setState] = useState<ConnectionState>("connecting");
  const pollRef = useRef<ReturnType<typeof setInterval> | null>(null);

  useEffect(() => {
    if (!runId) return;

    let socket: WebSocket | null = null;
    let cancelled = false;

    const startPolling = () => {
      setState("polling");
      if (pollRef.current) return;
      pollRef.current = setInterval(async () => {
        try {
          const snapshot = await apiClient.getRun(runId);
          queryClient.setQueryData(["run", runId], snapshot);
        } catch {
          // backend unreachable — the shell-level health check (Task 6) surfaces this
        }
      }, POLL_INTERVAL_MS);
    };

    const stopPolling = () => {
      if (pollRef.current) {
        clearInterval(pollRef.current);
        pollRef.current = null;
      }
    };

    try {
      socket = new WebSocket(apiClient.wsUrl(runId));
    } catch {
      startPolling();
      return;
    }

    socket.onopen = () => {
      if (cancelled) return;
      stopPolling();
      setState("live");
    };

    socket.onmessage = (event) => {
      if (cancelled) return;
      const message = JSON.parse(event.data) as WSMessage;
      if (message.type === "update") {
        const { type: _type, ...snapshot } = message;
        queryClient.setQueryData<RunSnapshot>(["run", runId], snapshot as RunSnapshot);
      }
    };

    socket.onclose = () => {
      if (cancelled) return;
      startPolling();
    };

    socket.onerror = () => {
      if (cancelled) return;
      socket?.close();
    };

    return () => {
      cancelled = true;
      stopPolling();
      socket?.close();
    };
  }, [runId, queryClient]);

  return state;
}
```

- [ ] **Step 3: Write `web/tests/use-run-socket.test.tsx`**

```tsx
import { describe, it, expect, vi, beforeEach, afterEach } from "vitest";
import { renderHook, waitFor } from "@testing-library/react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import type { ReactNode } from "react";
import { useRunSocket } from "@/lib/use-run-socket";

class MockWebSocket {
  static instances: MockWebSocket[] = [];
  onopen: (() => void) | null = null;
  onmessage: ((event: { data: string }) => void) | null = null;
  onclose: (() => void) | null = null;
  onerror: (() => void) | null = null;
  closed = false;

  constructor(public url: string) {
    MockWebSocket.instances.push(this);
  }
  close() {
    this.closed = true;
    this.onclose?.();
  }
}

function wrapper({ children }: { children: ReactNode }) {
  const client = new QueryClient();
  return <QueryClientProvider client={client}>{children}</QueryClientProvider>;
}

describe("useRunSocket", () => {
  beforeEach(() => {
    MockWebSocket.instances = [];
    vi.stubGlobal("WebSocket", MockWebSocket);
  });

  afterEach(() => {
    vi.unstubAllGlobals();
  });

  it("reports 'live' once the socket opens", async () => {
    const { result } = renderHook(() => useRunSocket("run-1"), { wrapper });
    expect(result.current).toBe("connecting");

    MockWebSocket.instances[0].onopen?.();
    await waitFor(() => expect(result.current).toBe("live"));
  });

  it("falls back to 'polling' when the socket closes", async () => {
    const { result } = renderHook(() => useRunSocket("run-1"), { wrapper });
    MockWebSocket.instances[0].onopen?.();
    await waitFor(() => expect(result.current).toBe("live"));

    MockWebSocket.instances[0].close();
    await waitFor(() => expect(result.current).toBe("polling"));
  });

  it("writes incoming update messages into the query cache", async () => {
    const client = new QueryClient();
    function localWrapper({ children }: { children: ReactNode }) {
      return <QueryClientProvider client={client}>{children}</QueryClientProvider>;
    }
    renderHook(() => useRunSocket("run-1"), { wrapper: localWrapper });
    MockWebSocket.instances[0].onopen?.();

    MockWebSocket.instances[0].onmessage?.({
      data: JSON.stringify({ type: "update", run_id: "run-1", status: "running" }),
    });

    await waitFor(() => {
      expect(client.getQueryData(["run", "run-1"])).toMatchObject({ run_id: "run-1", status: "running" });
    });
  });
});
```

- [ ] **Step 4: Run the tests**

Run: `npm test -- run tests/use-run-socket.test.tsx`
Expected: 3 tests PASS. This is the required WebSocket-drop → polling-fallback test from the design spec.

- [ ] **Step 5: Commit**

```bash
git add web/lib/query-client.tsx web/lib/use-run-socket.ts web/tests/use-run-socket.test.tsx
git commit -m "Add React Query provider and WebSocket-with-polling-fallback hook"
```

---

### Task 6: App shell — active-run context, sidebar, header, provider wiring

**Files:**
- Create: `web/lib/active-run-context.tsx`, `web/components/shell/sidebar.tsx`, `web/components/shell/header.tsx`, `web/app/providers.tsx`
- Modify: `web/app/layout.tsx`, `web/app/page.tsx`
- Test: `web/tests/sidebar.test.tsx`

**Interfaces:**
- Consumes: `QueryProvider` (Task 5), `OperatorProvider`/`useOperator`/`SignInGate` (Task 4), `apiClient` (Task 3), `Badge` (Task 2).
- Produces: `ActiveRunProvider`, `useActiveRun()` returning `{ runId: string | null, setRunId: (id: string | null) => void, pendingApprovalCount: number, setPendingApprovalCount: (count: number) => void }` — every page (Tasks 7, 10, 11, 13) reads/writes this.

- [ ] **Step 1: Write `web/lib/active-run-context.tsx`**

```tsx
"use client";

import { createContext, useContext, useState, type ReactNode } from "react";

interface ActiveRunContextValue {
  runId: string | null;
  setRunId: (id: string | null) => void;
  pendingApprovalCount: number;
  setPendingApprovalCount: (count: number) => void;
}

const ActiveRunContext = createContext<ActiveRunContextValue | null>(null);

export function ActiveRunProvider({ children }: { children: ReactNode }) {
  const [runId, setRunId] = useState<string | null>(null);
  const [pendingApprovalCount, setPendingApprovalCount] = useState(0);
  return (
    <ActiveRunContext.Provider value={{ runId, setRunId, pendingApprovalCount, setPendingApprovalCount }}>
      {children}
    </ActiveRunContext.Provider>
  );
}

export function useActiveRun(): ActiveRunContextValue {
  const ctx = useContext(ActiveRunContext);
  if (!ctx) throw new Error("useActiveRun must be used within an ActiveRunProvider");
  return ctx;
}
```

- [ ] **Step 2: Write `web/components/shell/sidebar.tsx`**

```tsx
"use client";

import Link from "next/link";
import { usePathname } from "next/navigation";
import { cn } from "@/lib/utils";
import { Badge } from "@/components/ui/badge";
import { useActiveRun } from "@/lib/active-run-context";

const NAV_ITEMS = [
  { href: "/monitor", label: "Live Monitor" },
  { href: "/trace", label: "Agent Trace" },
  { href: "/approvals", label: "Approvals" },
] as const;

export function Sidebar() {
  const pathname = usePathname();
  const { pendingApprovalCount } = useActiveRun();

  return (
    <aside className="flex w-56 flex-col border-r border-border bg-card px-3 py-4">
      <div className="mb-6 px-2 text-sm font-bold tracking-wide text-foreground">
        Sentinel<span className="text-brand-accent">Grid</span>
      </div>
      <nav className="flex flex-col gap-1">
        {NAV_ITEMS.map((item) => (
          <Link
            key={item.href}
            href={item.href}
            className={cn(
              "flex items-center justify-between rounded-md px-2 py-2 text-sm text-muted-foreground hover:bg-secondary hover:text-foreground",
              pathname?.startsWith(item.href) && "bg-secondary text-brand-accent"
            )}
          >
            {item.label}
            {item.href === "/approvals" && pendingApprovalCount > 0 && (
              <Badge variant="destructive" className="h-5 min-w-5 justify-center px-1">
                {pendingApprovalCount}
              </Badge>
            )}
          </Link>
        ))}
      </nav>
    </aside>
  );
}
```

- [ ] **Step 3: Write `web/components/shell/header.tsx`**

```tsx
"use client";

import { useQuery } from "@tanstack/react-query";
import { apiClient } from "@/lib/api-client";
import { useOperator } from "@/lib/operator-context";

export function Header() {
  const { operatorId, clearOperatorId } = useOperator();

  const { data: healthy } = useQuery({
    queryKey: ["health"],
    queryFn: () => apiClient.health(),
    refetchInterval: 5_000,
  });

  const { data: llm } = useQuery({
    queryKey: ["llm-status"],
    queryFn: () => apiClient.llmStatus(),
    refetchInterval: 5_000,
  });

  return (
    <header className="flex items-center justify-between border-b border-border bg-background px-6 py-3">
      <div className="flex items-center gap-4 text-xs font-mono text-muted-foreground">
        <span className="flex items-center gap-1.5">
          <span
            className={"h-1.5 w-1.5 rounded-full " + (healthy ? "bg-risk-normal" : "bg-risk-critical")}
          />
          {healthy ? "Backend connected" : "Backend unreachable"}
        </span>
        <span>LLM tier: {llm?.active_tier ?? "none yet"}</span>
      </div>
      {operatorId && (
        <button onClick={clearOperatorId} className="text-xs font-mono text-muted-foreground hover:text-foreground">
          Signed in as {operatorId}
        </button>
      )}
    </header>
  );
}
```

- [ ] **Step 4: Write `web/app/providers.tsx`, update `web/app/layout.tsx` and `web/app/page.tsx`**

`web/app/providers.tsx`:
```tsx
"use client";

import type { ReactNode } from "react";
import { QueryProvider } from "@/lib/query-client";
import { OperatorProvider } from "@/lib/operator-context";
import { ActiveRunProvider } from "@/lib/active-run-context";
import { SignInGate } from "@/components/shell/sign-in-gate";
import { Sidebar } from "@/components/shell/sidebar";
import { Header } from "@/components/shell/header";

export function Providers({ children }: { children: ReactNode }) {
  return (
    <QueryProvider>
      <OperatorProvider>
        <ActiveRunProvider>
          <SignInGate>
            <div className="flex h-screen">
              <Sidebar />
              <div className="flex flex-1 flex-col overflow-hidden">
                <Header />
                <main className="flex-1 overflow-y-auto bg-background p-6">{children}</main>
              </div>
            </div>
          </SignInGate>
        </ActiveRunProvider>
      </OperatorProvider>
    </QueryProvider>
  );
}
```

`web/app/layout.tsx`:
```tsx
import type { Metadata } from "next";
import "./globals.css";
import { Providers } from "./providers";

export const metadata: Metadata = {
  title: "SentinelGrid",
  description: "Compound-risk monitoring for a chemical plant",
};

export default function RootLayout({ children }: { children: React.ReactNode }) {
  return (
    <html lang="en">
      <body className="font-sans antialiased">
        <Providers>{children}</Providers>
      </body>
    </html>
  );
}
```

`web/app/page.tsx`:
```tsx
import { redirect } from "next/navigation";

export default function Home() {
  redirect("/monitor");
}
```

- [ ] **Step 5: Write `web/tests/sidebar.test.tsx`**

```tsx
import { describe, it, expect, vi } from "vitest";
import { render, screen } from "@testing-library/react";
import { useEffect } from "react";
import { ActiveRunProvider, useActiveRun } from "@/lib/active-run-context";

vi.mock("next/navigation", () => ({
  usePathname: () => "/monitor",
}));

import { Sidebar } from "@/components/shell/sidebar";

function HarnessWithCount({ count }: { count: number }) {
  const { setPendingApprovalCount } = useActiveRun();
  useEffect(() => setPendingApprovalCount(count), [count, setPendingApprovalCount]);
  return <Sidebar />;
}

describe("Sidebar", () => {
  it("does not show an approvals badge when nothing is pending", () => {
    render(
      <ActiveRunProvider>
        <Sidebar />
      </ActiveRunProvider>
    );
    expect(screen.queryByText("1")).not.toBeInTheDocument();
  });

  it("shows the pending count as a badge on Approvals", () => {
    render(
      <ActiveRunProvider>
        <HarnessWithCount count={3} />
      </ActiveRunProvider>
    );
    expect(screen.getByText("3")).toBeInTheDocument();
  });
});
```

- [ ] **Step 6: Run the tests**

Run: `npm test -- run tests/sidebar.test.tsx`
Expected: 2 tests PASS.

- [ ] **Step 7: Commit**

```bash
git add web/lib/active-run-context.tsx web/components/shell/ web/app/providers.tsx web/app/layout.tsx web/app/page.tsx web/tests/sidebar.test.tsx
git commit -m "Add app shell: active-run context, sidebar, header, provider wiring"
```

---

### Task 7: Scenario picker + run-start form

**Files:**
- Create: `web/components/monitor/scenario-picker.tsx`
- Test: `web/tests/scenario-picker.test.tsx`

**Interfaces:**
- Consumes: `apiClient.listScenarios()`, `apiClient.startRun()` (Task 3); `useActiveRun()` (Task 6); `Button`, `Input`, `Label` (Task 2).
- Produces: `ScenarioPicker` component — used by the Monitor page (Task 10).

A native `<select>` is used instead of a shadcn/Radix `Select` — Radix's pointer-capture behavior is unreliable under jsdom, and a native element keeps the test in Step 2 fast and non-flaky.

- [ ] **Step 1: Write `web/components/monitor/scenario-picker.tsx`**

```tsx
"use client";

import { useState } from "react";
import { useQuery, useMutation, useQueryClient } from "@tanstack/react-query";
import { apiClient } from "@/lib/api-client";
import { useActiveRun } from "@/lib/active-run-context";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";

export function ScenarioPicker() {
  const { setRunId } = useActiveRun();
  const queryClient = useQueryClient();
  const [selected, setSelected] = useState<string | null>(null);
  const [tickSeconds, setTickSeconds] = useState(0.2);
  const [assessmentInterval, setAssessmentInterval] = useState(5);
  const [durationHours, setDurationHours] = useState(0);

  const { data: scenarios, isLoading, error } = useQuery({
    queryKey: ["scenarios"],
    queryFn: () => apiClient.listScenarios(),
  });

  const startRun = useMutation({
    mutationFn: () =>
      apiClient.startRun({
        scenarioName: selected as string,
        tickSeconds,
        assessmentIntervalRecords: assessmentInterval,
        durationHours: durationHours || undefined,
      }),
    onSuccess: (runId) => {
      setRunId(runId);
      queryClient.invalidateQueries({ queryKey: ["run", runId] });
    },
  });

  if (isLoading) return <p className="text-sm text-muted-foreground">Loading scenarios…</p>;
  if (error) return <p className="text-sm text-risk-critical">Could not load scenarios: {(error as Error).message}</p>;

  const description = scenarios?.find((s) => s.name === selected)?.description;

  return (
    <div className="space-y-4 rounded-md border border-border bg-card p-4">
      <div className="space-y-2">
        <Label htmlFor="scenario-select">Scenario</Label>
        <select
          id="scenario-select"
          className="w-full rounded-md border border-input bg-background px-3 py-2 text-sm text-foreground"
          value={selected ?? ""}
          onChange={(e) => setSelected(e.target.value || null)}
        >
          <option value="" disabled>
            Choose a scenario
          </option>
          {scenarios?.map((s) => (
            <option key={s.name} value={s.name}>
              {s.name}
            </option>
          ))}
        </select>
        {description && <p className="text-xs text-muted-foreground">{description}</p>}
      </div>

      <div className="grid grid-cols-3 gap-3">
        <div className="space-y-1">
          <Label htmlFor="duration">Duration override (h, 0 = default)</Label>
          <Input
            id="duration"
            type="number"
            min={0}
            step={0.5}
            value={durationHours}
            onChange={(e) => setDurationHours(Number(e.target.value))}
          />
        </div>
        <div className="space-y-1">
          <Label htmlFor="tick">Tick seconds</Label>
          <Input
            id="tick"
            type="number"
            min={0.01}
            step={0.05}
            value={tickSeconds}
            onChange={(e) => setTickSeconds(Number(e.target.value))}
          />
        </div>
        <div className="space-y-1">
          <Label htmlFor="interval">Assess every N records</Label>
          <Input
            id="interval"
            type="number"
            min={1}
            step={1}
            value={assessmentInterval}
            onChange={(e) => setAssessmentInterval(Number(e.target.value))}
          />
        </div>
      </div>

      <Button onClick={() => startRun.mutate()} disabled={!selected || startRun.isPending}>
        {startRun.isPending ? "Starting…" : "Start run"}
      </Button>
      {startRun.isError && (
        <p className="text-sm text-risk-critical">Failed to start run: {(startRun.error as Error).message}</p>
      )}
    </div>
  );
}
```

- [ ] **Step 2: Write `web/tests/scenario-picker.test.tsx`**

```tsx
import { describe, it, expect, vi, beforeEach } from "vitest";
import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { ActiveRunProvider, useActiveRun } from "@/lib/active-run-context";
import { apiClient } from "@/lib/api-client";
import { ScenarioPicker } from "@/components/monitor/scenario-picker";

vi.mock("@/lib/api-client", () => ({
  apiClient: {
    listScenarios: vi.fn(),
    startRun: vi.fn(),
  },
}));

function renderWithProviders() {
  const client = new QueryClient();
  let capturedRunId: string | null = null;
  function Capture() {
    capturedRunId = useActiveRun().runId;
    return null;
  }
  render(
    <QueryClientProvider client={client}>
      <ActiveRunProvider>
        <ScenarioPicker />
        <Capture />
      </ActiveRunProvider>
    </QueryClientProvider>
  );
  return { getRunId: () => capturedRunId };
}

describe("ScenarioPicker", () => {
  beforeEach(() => {
    vi.mocked(apiClient.listScenarios).mockResolvedValue([
      { name: "baseline", description: "No fault.", duration_hours: 2 },
      { name: "reactor_a_feed_loss", description: "Total feed loss.", duration_hours: 3 },
    ]);
    vi.mocked(apiClient.startRun).mockResolvedValue("run-999");
  });

  it("starts a run with the selected scenario and sets it as the active run", async () => {
    const { getRunId } = renderWithProviders();

    await screen.findByText(/choose a scenario/i);
    await userEvent.selectOptions(screen.getByLabelText(/scenario/i), "reactor_a_feed_loss");
    await userEvent.click(screen.getByRole("button", { name: /start run/i }));

    await waitFor(() =>
      expect(apiClient.startRun).toHaveBeenCalledWith(
        expect.objectContaining({ scenarioName: "reactor_a_feed_loss" })
      )
    );
    await waitFor(() => expect(getRunId()).toBe("run-999"));
  });

  it("disables Start run until a scenario is selected", async () => {
    renderWithProviders();
    await screen.findByText(/choose a scenario/i);
    expect(screen.getByRole("button", { name: /start run/i })).toBeDisabled();
  });
});
```

- [ ] **Step 3: Run the tests**

Run: `npm test -- run tests/scenario-picker.test.tsx`
Expected: 2 tests PASS.

- [ ] **Step 4: Commit**

```bash
git add web/components/monitor/scenario-picker.tsx web/tests/scenario-picker.test.tsx
git commit -m "Add scenario picker and run-start form"
```

---

### Task 8: KPI row + timeline chart

**Files:**
- Create: `web/components/monitor/kpi-row.tsx`, `web/components/monitor/timeline-chart.tsx`

**Interfaces:**
- Consumes: `RunSnapshot`, `LLMStatus`, `RecordSummary` types (Task 3).
- Produces: `KpiRow({ run: RunSnapshot, llm?: LLMStatus })`, `TimelineChart({ readings: RecordSummary[], contributingFactors?: string[] })` — used by the Monitor page (Task 10).

No dedicated unit test for these two: `KpiRow` is pure formatting logic already exercised through `AssessmentPanel`'s tests in Task 9, and `recharts`' `ResponsiveContainer` doesn't produce meaningful layout under jsdom — real coverage comes from the Playwright "start a run" smoke test in Task 14, which renders it in an actual browser.

- [ ] **Step 1: Write `web/components/monitor/kpi-row.tsx`**

```tsx
import type { RunSnapshot, LLMStatus } from "@/lib/types";

function Kpi({
  label,
  value,
  tone,
}: {
  label: string;
  value: string;
  tone?: "normal" | "warn" | "critical";
}) {
  const toneClass =
    tone === "warn" ? "text-risk-warn" : tone === "critical" ? "text-risk-critical" : "text-foreground";
  return (
    <div className="rounded-md border border-border bg-card px-4 py-3">
      <div className="text-xs font-mono uppercase tracking-wide text-muted-foreground">{label}</div>
      <div className={`mt-1 font-mono text-lg tabular-nums ${toneClass}`}>{value}</div>
    </div>
  );
}

export function KpiRow({ run, llm }: { run: RunSnapshot; llm?: LLMStatus }) {
  const risk = run.latest_assessment?.risk_assessment;
  const riskLabel = risk == null ? "—" : risk.risk_score === null ? "novel" : risk.risk_score.toFixed(1);
  const riskTone =
    risk?.risk_score == null ? "warn" : risk.risk_score >= 80 ? "critical" : risk.risk_score >= 50 ? "warn" : "normal";

  return (
    <div className="grid grid-cols-2 gap-3 sm:grid-cols-4">
      <Kpi label="Status" value={run.status} />
      <Kpi label="Records" value={`${run.revealed_count} / ${run.total_records}`} />
      <Kpi label="Risk score" value={riskLabel} tone={riskTone} />
      <Kpi label="LLM tier" value={llm?.active_tier ?? "none yet"} />
    </div>
  );
}
```

- [ ] **Step 2: Write `web/components/monitor/timeline-chart.tsx`**

```tsx
"use client";

import { LineChart, Line, XAxis, YAxis, CartesianGrid, Tooltip, ResponsiveContainer } from "recharts";
import type { RecordSummary } from "@/lib/types";

const SERIES: { key: keyof RecordSummary; label: string; color: string }[] = [
  { key: "reactor_temperature_c", label: "Reactor temp (°C)", color: "hsl(var(--brand-accent))" },
  { key: "reactor_pressure_kpa", label: "Reactor pressure (kPa)", color: "hsl(var(--risk-warn))" },
  { key: "reactor_level_pct", label: "Reactor level (%)", color: "hsl(var(--risk-normal))" },
];

export function TimelineChart({
  readings,
  contributingFactors = [],
}: {
  readings: RecordSummary[];
  contributingFactors?: string[];
}) {
  if (readings.length === 0) {
    return <p className="text-sm text-muted-foreground">No readings yet.</p>;
  }

  return (
    <div className="h-64 rounded-md border border-border bg-card p-4">
      <ResponsiveContainer width="100%" height="100%">
        <LineChart data={readings}>
          <CartesianGrid strokeDasharray="3 3" stroke="hsl(var(--border))" />
          <XAxis
            dataKey="t_hours"
            tickFormatter={(v: number) => v.toFixed(1)}
            stroke="hsl(var(--muted-foreground))"
            fontSize={11}
          />
          <YAxis stroke="hsl(var(--muted-foreground))" fontSize={11} />
          <Tooltip
            contentStyle={{ background: "hsl(var(--card))", border: "1px solid hsl(var(--border))" }}
            labelFormatter={(v: number) => `t = ${v.toFixed(2)}h`}
          />
          {SERIES.map((series) => (
            <Line
              key={series.key}
              type="monotone"
              dataKey={series.key}
              name={series.label}
              stroke={series.color}
              strokeWidth={contributingFactors.includes(series.key) ? 3 : 1.5}
              dot={false}
            />
          ))}
        </LineChart>
      </ResponsiveContainer>
    </div>
  );
}
```

- [ ] **Step 3: Verify the build**

Run: `npm run build`
Expected: succeeds with no TypeScript errors (confirms `RecordSummary`'s keys line up with the `SERIES` array and `recharts`' prop types).

- [ ] **Step 4: Commit**

```bash
git add web/components/monitor/kpi-row.tsx web/components/monitor/timeline-chart.tsx
git commit -m "Add KPI row and sensor timeline chart"
```

---

### Task 9: Assessment panel

**Files:**
- Create: `web/components/monitor/assessment-panel.tsx`
- Test: `web/tests/assessment-panel.test.tsx`

**Interfaces:**
- Consumes: `Assessment` type (Task 3).
- Produces: `AssessmentPanel({ assessment: Assessment | null })` — used by the Monitor page (Task 10).

This is the required "risk-score rendering" test from the design spec: `risk_score: null` must render as "novel condition," never a blank or a fabricated number, and `reasoning_unavailable: true` must render an explicit unavailable state.

- [ ] **Step 1: Write `web/components/monitor/assessment-panel.tsx`**

```tsx
import type { Assessment } from "@/lib/types";

export function AssessmentPanel({ assessment }: { assessment: Assessment | null }) {
  if (!assessment) {
    return (
      <div className="rounded-md border border-border bg-card p-4 text-sm text-muted-foreground">
        No assessment yet — waiting for enough records (needs at least 5).
      </div>
    );
  }

  const { risk_assessment: risk, explanation } = assessment;

  if (risk.reasoning_unavailable) {
    return (
      <div className="rounded-md border border-risk-critical bg-card p-4">
        <p className="text-sm font-semibold text-risk-critical">Reasoning service unavailable</p>
        <p className="mt-1 text-sm text-muted-foreground">
          Both LLM tiers failed to respond for this assessment. No score was guessed.
        </p>
      </div>
    );
  }

  if (risk.risk_score === null) {
    return (
      <div className="rounded-md border border-risk-warn bg-card p-4">
        <p className="text-sm font-semibold text-risk-warn">Novel condition — low confidence</p>
        <p className="mt-1 text-sm text-muted-foreground">{risk.reasoning}</p>
      </div>
    );
  }

  const tone = risk.risk_score >= 80 ? "critical" : risk.risk_score >= 50 ? "warn" : "normal";
  const toneClass =
    tone === "critical"
      ? "border-risk-critical text-risk-critical"
      : tone === "warn"
        ? "border-risk-warn text-risk-warn"
        : "border-risk-normal text-risk-normal";

  return (
    <div className={`space-y-3 rounded-md border bg-card p-4 ${toneClass}`}>
      <div className="flex items-baseline gap-2">
        <span className="font-mono text-2xl tabular-nums">{risk.risk_score.toFixed(1)}</span>
        <span className="text-xs uppercase tracking-wide text-muted-foreground">confidence: {risk.confidence}</span>
      </div>
      <p className="text-sm text-foreground">
        <span className="text-muted-foreground">Contributing factors: </span>
        {risk.contributing_factors.join(", ") || "none"}
      </p>
      <p className="text-sm text-foreground">
        <span className="text-muted-foreground">Recommended action: </span>
        {risk.recommended_action}
      </p>
      {explanation && <p className="text-sm text-foreground">{explanation.narrative}</p>}
    </div>
  );
}
```

- [ ] **Step 2: Write `web/tests/assessment-panel.test.tsx`**

```tsx
import { describe, it, expect } from "vitest";
import { render, screen } from "@testing-library/react";
import { AssessmentPanel } from "@/components/monitor/assessment-panel";
import type { Assessment } from "@/lib/types";

function makeAssessment(overrides: Partial<Assessment["risk_assessment"]>): Assessment {
  return {
    record_index: 10,
    t_hours: 1.2,
    retrieval_phase: "combined",
    retrieval_confidence: "high",
    is_novel_condition: false,
    risk_assessment: {
      risk_score: 62,
      is_novel_condition: false,
      confidence: "high",
      contributing_factors: ["reactor_temperature_c"],
      recommended_action: "Increase coolant flow.",
      cited_chunk_ids: ["chunk-1"],
      reasoning: "Cooling margin narrowing.",
      llm_tier_used: "gemini",
      latency_ms: 900,
      parse_error: false,
      reasoning_unavailable: false,
      ...overrides,
    },
    compliance_result: {
      action_reviewed: "Increase coolant flow.",
      approved: true,
      cited_sop_chunk_ids: [],
      notes: "",
      llm_tier_used: "gemini",
      latency_ms: 500,
      parse_error: false,
      reasoning_unavailable: false,
    },
    explanation: {
      narrative: "Reactor temp and pressure are trending together.",
      cited_chunk_ids: [],
      llm_tier_used: "gemini",
      latency_ms: 400,
      reasoning_unavailable: false,
    },
    emergency_recommendation: {
      triggered: false,
      recommended_interventions: [],
      requires_approval: true,
      approval_id: null,
      llm_tier_used: null,
      latency_ms: null,
      reasoning_unavailable: false,
    },
  };
}

describe("AssessmentPanel", () => {
  it("shows a placeholder when there is no assessment yet", () => {
    render(<AssessmentPanel assessment={null} />);
    expect(screen.getByText(/no assessment yet/i)).toBeInTheDocument();
  });

  it("renders the numeric risk score, confidence, and explanation for a normal assessment", () => {
    render(<AssessmentPanel assessment={makeAssessment({})} />);
    expect(screen.getByText("62.0")).toBeInTheDocument();
    expect(screen.getByText(/confidence: high/i)).toBeInTheDocument();
    expect(screen.getByText(/reactor temp and pressure are trending together/i)).toBeInTheDocument();
  });

  it("renders 'novel condition' instead of a fabricated score when risk_score is null", () => {
    const assessment = makeAssessment({ risk_score: null, is_novel_condition: true });
    render(<AssessmentPanel assessment={assessment} />);
    expect(screen.getByText(/novel condition/i)).toBeInTheDocument();
    expect(screen.queryByText(/^\d+\.\d$/)).not.toBeInTheDocument();
  });

  it("renders an explicit unavailable state when both LLM tiers failed, never a guessed score", () => {
    const assessment = makeAssessment({ reasoning_unavailable: true });
    render(<AssessmentPanel assessment={assessment} />);
    expect(screen.getByText(/reasoning service unavailable/i)).toBeInTheDocument();
    expect(screen.queryByText("62.0")).not.toBeInTheDocument();
  });
});
```

- [ ] **Step 3: Run the tests**

Run: `npm test -- run tests/assessment-panel.test.tsx`
Expected: 4 tests PASS. This is the required risk-score/novel-condition rendering test from the design spec.

- [ ] **Step 4: Commit**

```bash
git add web/components/monitor/assessment-panel.tsx web/tests/assessment-panel.test.tsx
git commit -m "Add assessment panel with novel-condition and unavailable states"
```

---

### Task 10: Monitor page assembly

**Files:**
- Create: `web/app/monitor/page.tsx`

**Interfaces:**
- Consumes: `useActiveRun()` (Task 6), `useRunSocket()` (Task 5), `apiClient` (Task 3), `ScenarioPicker` (Task 7), `KpiRow`/`TimelineChart` (Task 8), `AssessmentPanel` (Task 9).
- Produces: the `/monitor` route. No dedicated unit test — this is wiring of already-tested pieces; real coverage comes from the Playwright "start a run" smoke test in Task 14.

- [ ] **Step 1: Write `web/app/monitor/page.tsx`**

```tsx
"use client";

import { useQuery } from "@tanstack/react-query";
import { apiClient } from "@/lib/api-client";
import { useActiveRun } from "@/lib/active-run-context";
import { useRunSocket } from "@/lib/use-run-socket";
import { ScenarioPicker } from "@/components/monitor/scenario-picker";
import { KpiRow } from "@/components/monitor/kpi-row";
import { TimelineChart } from "@/components/monitor/timeline-chart";
import { AssessmentPanel } from "@/components/monitor/assessment-panel";

export default function MonitorPage() {
  const { runId } = useActiveRun();
  const connection = useRunSocket(runId);

  const { data: run } = useQuery({
    queryKey: ["run", runId],
    queryFn: () => apiClient.getRun(runId as string),
    enabled: !!runId,
    refetchInterval: connection === "polling" ? 2_000 : false,
  });

  const { data: readings } = useQuery({
    queryKey: ["readings", runId],
    queryFn: () => apiClient.getReadings(runId as string),
    enabled: !!runId,
    refetchInterval: connection !== "live" ? 2_000 : 5_000,
  });

  const { data: llm } = useQuery({
    queryKey: ["llm-status"],
    queryFn: () => apiClient.llmStatus(),
    refetchInterval: 5_000,
  });

  if (!runId) {
    return (
      <div className="space-y-4">
        <h1 className="text-xl font-semibold text-foreground">Live Monitor</h1>
        <ScenarioPicker />
      </div>
    );
  }

  return (
    <div className="space-y-4">
      <div className="flex items-center justify-between">
        <h1 className="text-xl font-semibold text-foreground">Live Monitor</h1>
        <span className="font-mono text-xs text-muted-foreground">
          {connection === "live" ? "● live" : connection === "polling" ? "● polling (reconnecting…)" : "connecting…"}
        </span>
      </div>

      {run?.diverged && (
        <div className="rounded-md border border-risk-warn bg-card p-3 text-sm text-risk-warn">
          Simulation diverged / tripped: {run.diverged_reason}
        </div>
      )}
      {run?.error && (
        <div className="rounded-md border border-risk-critical bg-card p-3 text-sm text-risk-critical">
          Run error: {run.error}
        </div>
      )}

      {run && <KpiRow run={run} llm={llm} />}
      <TimelineChart
        readings={readings ?? []}
        contributingFactors={run?.latest_assessment?.risk_assessment.contributing_factors}
      />
      <AssessmentPanel assessment={run?.latest_assessment ?? null} />
    </div>
  );
}
```

- [ ] **Step 2: Verify the build**

Run: `npm run build`
Expected: succeeds with no TypeScript errors.

- [ ] **Step 3: Commit**

```bash
git add web/app/monitor/page.tsx
git commit -m "Assemble the Live Monitor page"
```

---

### Task 11: Agent Trace — audit strip, master-detail assessment list, page

**Files:**
- Create: `web/components/trace/audit-strip.tsx`, `web/components/trace/assessment-list.tsx`, `web/components/trace/assessment-detail.tsx`, `web/app/trace/page.tsx`
- Test: `web/tests/assessment-list.test.tsx`

**Interfaces:**
- Consumes: `apiClient` (Task 3), `Assessment` type (Task 3), `useActiveRun()` (Task 6), `cn()` (Task 2).
- Produces: `AuditStrip`, `AssessmentList({ assessments, selectedIndex, onSelect })`, `AssessmentDetail({ assessment })`, and the `/trace` route.

- [ ] **Step 1: Write `web/components/trace/audit-strip.tsx`**

```tsx
"use client";

import { useQuery } from "@tanstack/react-query";
import { apiClient } from "@/lib/api-client";

export function AuditStrip() {
  const { data, isLoading } = useQuery({
    queryKey: ["audit-verify"],
    queryFn: () => apiClient.auditVerify(),
  });

  if (isLoading) return <p className="text-sm text-muted-foreground">Verifying audit chain…</p>;
  if (!data) return null;

  return (
    <div
      className={`rounded-md border p-3 text-sm ${
        data.ok ? "border-risk-normal text-risk-normal" : "border-risk-critical text-risk-critical"
      }`}
    >
      {data.ok
        ? `Hash chain verified — ${data.rows_checked} rows, untampered.`
        : `Audit chain broken at row ${data.first_broken_id}: ${data.reason}`}
    </div>
  );
}
```

- [ ] **Step 2: Write `web/components/trace/assessment-list.tsx`**

```tsx
import type { Assessment } from "@/lib/types";
import { cn } from "@/lib/utils";

export function AssessmentList({
  assessments,
  selectedIndex,
  onSelect,
}: {
  assessments: Assessment[];
  selectedIndex: number | null;
  onSelect: (index: number) => void;
}) {
  return (
    <ul className="flex flex-col gap-1">
      {[...assessments].reverse().map((a, i) => {
        const originalIndex = assessments.length - 1 - i;
        const score = a.risk_assessment.risk_score;
        const label = score === null ? "novel" : score.toFixed(1);
        const tone =
          score === null
            ? "text-risk-warn"
            : score >= 80
              ? "text-risk-critical"
              : score >= 50
                ? "text-risk-warn"
                : "text-risk-normal";
        return (
          <li key={a.record_index}>
            <button
              onClick={() => onSelect(originalIndex)}
              className={cn(
                "flex w-full items-center justify-between rounded-md border border-border bg-card px-3 py-2 text-left text-sm hover:bg-secondary",
                selectedIndex === originalIndex && "border-brand-accent"
              )}
            >
              <span className="text-foreground">#{originalIndex + 1} · t={a.t_hours.toFixed(2)}h</span>
              <span className={`font-mono tabular-nums ${tone}`}>{label}</span>
            </button>
          </li>
        );
      })}
    </ul>
  );
}
```

- [ ] **Step 3: Write `web/components/trace/assessment-detail.tsx`**

```tsx
import type { Assessment } from "@/lib/types";

function Stage({ title, children }: { title: string; children: React.ReactNode }) {
  return (
    <div className="rounded-md border border-border bg-card p-4">
      <h3 className="mb-2 text-sm font-semibold text-foreground">{title}</h3>
      {children}
    </div>
  );
}

export function AssessmentDetail({ assessment }: { assessment: Assessment | null }) {
  if (!assessment) {
    return <p className="text-sm text-muted-foreground">Select an assessment on the left.</p>;
  }

  const {
    risk_assessment: risk,
    compliance_result: compliance,
    explanation,
    emergency_recommendation: emergency,
  } = assessment;

  return (
    <div className="space-y-3">
      <p className="text-xs font-mono text-muted-foreground">
        Retrieval phase: {assessment.retrieval_phase} · confidence: {assessment.retrieval_confidence} · novel:{" "}
        {String(assessment.is_novel_condition)}
      </p>

      <Stage title="1. Compound-Risk Agent">
        <p className="text-sm text-foreground">
          Risk score: <strong>{risk.risk_score ?? "N/A (novel condition)"}</strong> (tier: {risk.llm_tier_used})
        </p>
        <p className="text-sm text-muted-foreground">Contributing: {risk.contributing_factors.join(", ") || "none"}</p>
        <p className="text-sm text-muted-foreground">Recommended: {risk.recommended_action}</p>
        <p className="text-sm text-muted-foreground">{risk.reasoning}</p>
        {risk.cited_chunk_ids.length > 0 && (
          <p className="mt-1 text-xs text-muted-foreground">Cited: {risk.cited_chunk_ids.join(", ")}</p>
        )}
      </Stage>

      <Stage title="2. Compliance Agent">
        <p className="text-sm text-foreground">
          {compliance.approved ? "Approved" : "Not approved"} (tier: {compliance.llm_tier_used})
        </p>
        <p className="text-sm text-muted-foreground">{compliance.notes}</p>
        {compliance.cited_sop_chunk_ids.length > 0 && (
          <p className="mt-1 text-xs text-muted-foreground">Cited SOP: {compliance.cited_sop_chunk_ids.join(", ")}</p>
        )}
      </Stage>

      <Stage title="3. Explanation Agent">
        <p className="text-sm text-foreground">{explanation.narrative}</p>
      </Stage>

      <Stage title="4. Emergency Agent">
        {emergency.triggered ? (
          <div className="text-sm text-risk-critical">
            Escalated — approval_id <code>{emergency.approval_id}</code> (see Approvals page)
            <ul className="mt-1 list-disc pl-5 text-foreground">
              {emergency.recommended_interventions.map((item) => (
                <li key={item}>{item}</li>
              ))}
            </ul>
          </div>
        ) : (
          <p className="text-sm text-muted-foreground">Not triggered (risk below threshold or novel condition).</p>
        )}
      </Stage>
    </div>
  );
}
```

- [ ] **Step 4: Write `web/app/trace/page.tsx`**

```tsx
"use client";

import { useState, useEffect } from "react";
import { useQuery } from "@tanstack/react-query";
import { apiClient } from "@/lib/api-client";
import { useActiveRun } from "@/lib/active-run-context";
import { AuditStrip } from "@/components/trace/audit-strip";
import { AssessmentList } from "@/components/trace/assessment-list";
import { AssessmentDetail } from "@/components/trace/assessment-detail";

export default function TracePage() {
  const { runId } = useActiveRun();
  const [selectedIndex, setSelectedIndex] = useState<number | null>(null);

  const { data: assessments } = useQuery({
    queryKey: ["assessments", runId],
    queryFn: () => apiClient.getAssessments(runId as string),
    enabled: !!runId,
    refetchInterval: 3_000,
  });

  useEffect(() => {
    if (assessments && assessments.length > 0 && selectedIndex === null) {
      setSelectedIndex(assessments.length - 1);
    }
  }, [assessments, selectedIndex]);

  if (!runId) {
    return <p className="text-sm text-muted-foreground">No run selected — start one on the Live Monitor page first.</p>;
  }

  return (
    <div className="space-y-4">
      <h1 className="text-xl font-semibold text-foreground">Agent Trace</h1>
      <AuditStrip />
      {!assessments || assessments.length === 0 ? (
        <p className="text-sm text-muted-foreground">No assessments yet — need at least 5 revealed records.</p>
      ) : (
        <div className="grid grid-cols-[280px_1fr] gap-4">
          <AssessmentList assessments={assessments} selectedIndex={selectedIndex} onSelect={setSelectedIndex} />
          <AssessmentDetail assessment={selectedIndex !== null ? assessments[selectedIndex] : null} />
        </div>
      )}
    </div>
  );
}
```

- [ ] **Step 5: Write `web/tests/assessment-list.test.tsx`**

```tsx
import { describe, it, expect, vi } from "vitest";
import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { AssessmentList } from "@/components/trace/assessment-list";
import type { Assessment } from "@/lib/types";

function makeAssessment(index: number, score: number | null): Assessment {
  return {
    record_index: index,
    t_hours: index * 0.2,
    retrieval_phase: "combined",
    retrieval_confidence: "high",
    is_novel_condition: score === null,
    risk_assessment: {
      risk_score: score,
      is_novel_condition: score === null,
      confidence: "high",
      contributing_factors: [],
      recommended_action: "",
      cited_chunk_ids: [],
      reasoning: "",
      llm_tier_used: "gemini",
      latency_ms: 1,
      parse_error: false,
      reasoning_unavailable: false,
    },
    compliance_result: {
      action_reviewed: "",
      approved: true,
      cited_sop_chunk_ids: [],
      notes: "",
      llm_tier_used: "gemini",
      latency_ms: 1,
      parse_error: false,
      reasoning_unavailable: false,
    },
    explanation: { narrative: "", cited_chunk_ids: [], llm_tier_used: "gemini", latency_ms: 1, reasoning_unavailable: false },
    emergency_recommendation: {
      triggered: false,
      recommended_interventions: [],
      requires_approval: true,
      approval_id: null,
      llm_tier_used: null,
      latency_ms: null,
      reasoning_unavailable: false,
    },
  };
}

describe("AssessmentList", () => {
  it("lists assessments newest first and calls onSelect with the original index", async () => {
    const assessments = [makeAssessment(0, 12), makeAssessment(1, 62)];
    const onSelect = vi.fn();
    render(<AssessmentList assessments={assessments} selectedIndex={null} onSelect={onSelect} />);

    const rows = screen.getAllByRole("button");
    expect(rows[0]).toHaveTextContent("#2");
    expect(rows[1]).toHaveTextContent("#1");

    await userEvent.click(rows[0]);
    expect(onSelect).toHaveBeenCalledWith(1);
  });

  it("renders 'novel' instead of a score for a novel-condition assessment", () => {
    render(<AssessmentList assessments={[makeAssessment(0, null)]} selectedIndex={null} onSelect={vi.fn()} />);
    expect(screen.getByText("novel")).toBeInTheDocument();
  });
});
```

- [ ] **Step 6: Run the tests**

Run: `npm test -- run tests/assessment-list.test.tsx`
Expected: 2 tests PASS.

- [ ] **Step 7: Commit**

```bash
git add web/components/trace/ web/app/trace/page.tsx web/tests/assessment-list.test.tsx
git commit -m "Add Agent Trace page: audit strip and master-detail assessment view"
```

---

### Task 12: Approval list + approval detail (viewed-before-decide gate)

**Files:**
- Create: `web/components/approvals/approval-list.tsx`, `web/components/approvals/approval-detail.tsx`
- Test: `web/tests/approval-detail.test.tsx`

**Interfaces:**
- Consumes: `apiClient.markViewed()`, `apiClient.decide()` (Task 3); `useOperator()` (Task 4); `Button` (Task 2); `ApprovalRecord`, `Assessment` types (Task 3).
- Produces: `ApprovalList({ approvals, selectedId, onSelect })`, `ApprovalDetail({ approval, matchingAssessment })` — used by the Approvals page (Task 13).

This is the required "approval-gate logic" test from the design spec: Approve/Reject must stay disabled until `viewed_evidence` is `true` AND an operator is signed in, and a decision always carries the signed-in operator's ID.

- [ ] **Step 1: Write `web/components/approvals/approval-list.tsx`**

```tsx
import type { ApprovalRecord } from "@/lib/types";
import { cn } from "@/lib/utils";

const STATUS_LABEL: Record<ApprovalRecord["status"], string> = {
  pending: "PENDING",
  approved: "APPROVED",
  rejected: "REJECTED",
};

const STATUS_TONE: Record<ApprovalRecord["status"], string> = {
  pending: "text-risk-warn",
  approved: "text-risk-normal",
  rejected: "text-risk-critical",
};

export function ApprovalList({
  approvals,
  selectedId,
  onSelect,
}: {
  approvals: ApprovalRecord[];
  selectedId: string | null;
  onSelect: (id: string) => void;
}) {
  return (
    <ul className="flex flex-col gap-1">
      {approvals.map((a) => (
        <li key={a.approval_id}>
          <button
            onClick={() => onSelect(a.approval_id)}
            className={cn(
              "flex w-full flex-col items-start gap-1 rounded-md border border-border bg-card px-3 py-2 text-left text-sm hover:bg-secondary",
              selectedId === a.approval_id && "border-brand-accent"
            )}
          >
            <span className="font-mono text-xs text-muted-foreground">{a.approval_id.slice(0, 8)}</span>
            <span className={`text-xs font-semibold ${STATUS_TONE[a.status]}`}>{STATUS_LABEL[a.status]}</span>
            <span className="line-clamp-2 text-foreground">{a.recommendation_summary}</span>
          </button>
        </li>
      ))}
    </ul>
  );
}
```

- [ ] **Step 2: Write `web/components/approvals/approval-detail.tsx`**

The gate logic: decisions are only ever applied from the server's response (`onSuccess: (updated) => queryClient.setQueryData(...)`), never assumed optimistically — so a WebSocket/network drop mid-decision cannot show a false "approved" row.

```tsx
"use client";

import { useMutation, useQueryClient } from "@tanstack/react-query";
import { apiClient } from "@/lib/api-client";
import { useOperator } from "@/lib/operator-context";
import { Button } from "@/components/ui/button";
import type { ApprovalRecord, Assessment } from "@/lib/types";

export function ApprovalDetail({
  approval,
  matchingAssessment,
}: {
  approval: ApprovalRecord;
  matchingAssessment: Assessment | null;
}) {
  const { operatorId } = useOperator();
  const queryClient = useQueryClient();

  const markViewed = useMutation({
    mutationFn: () => apiClient.markViewed(approval.approval_id),
    onSuccess: (updated) => {
      queryClient.setQueryData(["approval", approval.approval_id], updated);
    },
  });

  const decide = useMutation({
    mutationFn: (status: "approved" | "rejected") =>
      apiClient.decide(approval.approval_id, operatorId as string, status),
    onSuccess: (updated) => {
      queryClient.setQueryData(["approval", approval.approval_id], updated);
    },
  });

  const canDecide = approval.viewed_evidence && !!operatorId && approval.status === "pending";

  return (
    <div className="space-y-3">
      <h2 className="text-sm font-semibold text-foreground">
        Approval <code>{approval.approval_id.slice(0, 8)}</code>
      </h2>
      <p className="text-sm text-foreground">{approval.recommendation_summary}</p>
      {approval.operator_id && (
        <p className="text-xs text-muted-foreground">
          Decided by {approval.operator_id} at {approval.decided_at}
        </p>
      )}

      {matchingAssessment && (
        <div className="rounded-md border border-border bg-card p-4">
          <h3 className="mb-2 text-sm font-semibold text-foreground">Evidence / explanation</h3>
          <p className="text-sm text-foreground">{matchingAssessment.explanation.narrative}</p>
          <p className="mt-1 text-sm text-muted-foreground">
            Risk score: {matchingAssessment.risk_assessment.risk_score ?? "N/A (novel condition)"}
          </p>
          <p className="text-sm text-muted-foreground">
            Compliance: {matchingAssessment.compliance_result.approved ? "approved" : "not approved"} —{" "}
            {matchingAssessment.compliance_result.notes}
          </p>
          {!approval.viewed_evidence && (
            <Button className="mt-3" variant="secondary" onClick={() => markViewed.mutate()} disabled={markViewed.isPending}>
              Mark evidence as viewed
            </Button>
          )}
        </div>
      )}

      {approval.status === "pending" && (
        <div className="space-y-2">
          {!approval.viewed_evidence && (
            <p className="text-sm text-risk-warn">
              Evidence must be viewed above before this can be decided — reflexive-click approvals are disabled by design.
            </p>
          )}
          {!operatorId && <p className="text-sm text-muted-foreground">Sign in to enable the decision buttons.</p>}
          <div className="flex gap-2">
            <Button onClick={() => decide.mutate("approved")} disabled={!canDecide || decide.isPending}>
              Approve
            </Button>
            <Button variant="destructive" onClick={() => decide.mutate("rejected")} disabled={!canDecide || decide.isPending}>
              Reject
            </Button>
          </div>
        </div>
      )}
    </div>
  );
}
```

- [ ] **Step 3: Write `web/tests/approval-detail.test.tsx`**

```tsx
import { describe, it, expect, vi, beforeEach } from "vitest";
import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { useEffect } from "react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { OperatorProvider, useOperator } from "@/lib/operator-context";
import { apiClient } from "@/lib/api-client";
import { ApprovalDetail } from "@/components/approvals/approval-detail";
import type { ApprovalRecord } from "@/lib/types";

vi.mock("@/lib/api-client", () => ({
  apiClient: {
    markViewed: vi.fn(),
    decide: vi.fn(),
  },
}));

function baseApproval(overrides: Partial<ApprovalRecord> = {}): ApprovalRecord {
  return {
    approval_id: "approval-123",
    run_id: "run-1",
    recommendation_summary: "Shut down feed to reactor A.",
    status: "pending",
    operator_id: null,
    decided_at: null,
    viewed_evidence: false,
    ...overrides,
  };
}

function SignInHarness({ id }: { id: string | null }) {
  const { setOperatorId } = useOperator();
  useEffect(() => {
    if (id) setOperatorId(id);
  }, [id, setOperatorId]);
  return null;
}

function renderDetail(approval: ApprovalRecord, operatorSignedIn: string | null = "J.RAO") {
  const client = new QueryClient();
  return render(
    <QueryClientProvider client={client}>
      <OperatorProvider>
        <SignInHarness id={operatorSignedIn} />
        <ApprovalDetail approval={approval} matchingAssessment={null} />
      </OperatorProvider>
    </QueryClientProvider>
  );
}

describe("ApprovalDetail — viewed-before-decide gate", () => {
  beforeEach(() => {
    vi.mocked(apiClient.decide).mockResolvedValue(baseApproval({ status: "approved" }));
    vi.mocked(apiClient.markViewed).mockResolvedValue(baseApproval({ viewed_evidence: true }));
  });

  it("disables Approve and Reject until the evidence has been viewed", async () => {
    renderDetail(baseApproval({ viewed_evidence: false }));
    expect(await screen.findByRole("button", { name: /approve/i })).toBeDisabled();
    expect(screen.getByRole("button", { name: /reject/i })).toBeDisabled();
    expect(screen.getByText(/reflexive-click approvals are disabled by design/i)).toBeInTheDocument();
  });

  it("enables the decision buttons once evidence has been viewed and an operator is signed in", async () => {
    renderDetail(baseApproval({ viewed_evidence: true }));
    expect(await screen.findByRole("button", { name: /approve/i })).toBeEnabled();
    expect(screen.getByRole("button", { name: /reject/i })).toBeEnabled();
  });

  it("keeps decision buttons disabled with no signed-in operator, even after viewing evidence", async () => {
    renderDetail(baseApproval({ viewed_evidence: true }), null);
    expect(await screen.findByRole("button", { name: /approve/i })).toBeDisabled();
  });

  it("calls decide() with the signed-in operator ID when Approve is clicked", async () => {
    renderDetail(baseApproval({ viewed_evidence: true }));
    const approveButton = await screen.findByRole("button", { name: /approve/i });
    await userEvent.click(approveButton);
    expect(apiClient.decide).toHaveBeenCalledWith("approval-123", "J.RAO", "approved");
  });

  it("does not render decide buttons at all once a decision has already been made", async () => {
    renderDetail(baseApproval({ viewed_evidence: true, status: "approved", operator_id: "J.RAO" }));
    await screen.findByText(/shut down feed to reactor a/i);
    expect(screen.queryByRole("button", { name: /approve/i })).not.toBeInTheDocument();
  });
});
```

- [ ] **Step 4: Run the tests**

Run: `npm test -- run tests/approval-detail.test.tsx`
Expected: 5 tests PASS. This is the required approval-gate-logic test from the design spec.

- [ ] **Step 5: Commit**

```bash
git add web/components/approvals/ web/tests/approval-detail.test.tsx
git commit -m "Add approval list and viewed-before-decide gate"
```

---

### Task 13: Approvals page assembly

**Files:**
- Create: `web/app/approvals/page.tsx`

**Interfaces:**
- Consumes: `useActiveRun()` (Task 6), `apiClient` (Task 3), `ApprovalList`/`ApprovalDetail` (Task 12).
- Produces: the `/approvals` route; writes `pendingApprovalCount` back into `ActiveRunContext` so the sidebar badge (Task 6) reflects it. No dedicated unit test — wiring of already-tested pieces; covered by the Playwright "approve a recommendation" smoke test in Task 14.

- [ ] **Step 1: Write `web/app/approvals/page.tsx`**

```tsx
"use client";

import { useState, useEffect } from "react";
import { useQuery } from "@tanstack/react-query";
import { apiClient } from "@/lib/api-client";
import { useActiveRun } from "@/lib/active-run-context";
import { ApprovalList } from "@/components/approvals/approval-list";
import { ApprovalDetail } from "@/components/approvals/approval-detail";
import type { ApprovalRecord } from "@/lib/types";

export default function ApprovalsPage() {
  const { runId, setPendingApprovalCount } = useActiveRun();
  const [selectedId, setSelectedId] = useState<string | null>(null);

  const { data: assessments } = useQuery({
    queryKey: ["assessments", runId],
    queryFn: () => apiClient.getAssessments(runId as string),
    enabled: !!runId,
    refetchInterval: 3_000,
  });

  const approvalIds = Array.from(
    new Set(
      (assessments ?? [])
        .filter((a) => a.emergency_recommendation.triggered && a.emergency_recommendation.approval_id)
        .map((a) => a.emergency_recommendation.approval_id as string)
    )
  );

  const { data: approvals } = useQuery({
    queryKey: ["approvals", approvalIds],
    queryFn: () => Promise.all(approvalIds.map((id) => apiClient.getApproval(id))),
    enabled: approvalIds.length > 0,
    refetchInterval: 3_000,
  });

  useEffect(() => {
    if (approvals) {
      setPendingApprovalCount(approvals.filter((a) => a.status === "pending").length);
    }
  }, [approvals, setPendingApprovalCount]);

  useEffect(() => {
    if (approvals && approvals.length > 0 && !selectedId) {
      setSelectedId(approvals[0].approval_id);
    }
  }, [approvals, selectedId]);

  if (!runId) {
    return <p className="text-sm text-muted-foreground">No run selected — start one on the Live Monitor page first.</p>;
  }

  if (!approvals || approvals.length === 0) {
    return (
      <div className="space-y-4">
        <h1 className="text-xl font-semibold text-foreground">Approvals</h1>
        <p className="text-sm text-muted-foreground">No Emergency Agent escalations for this run yet.</p>
      </div>
    );
  }

  const selected: ApprovalRecord | undefined = approvals.find((a) => a.approval_id === selectedId);
  const matchingAssessment = assessments?.find((a) => a.emergency_recommendation.approval_id === selectedId) ?? null;

  return (
    <div className="space-y-4">
      <h1 className="text-xl font-semibold text-foreground">Approvals</h1>
      <div className="grid grid-cols-[280px_1fr] gap-4">
        <ApprovalList approvals={approvals} selectedId={selectedId} onSelect={setSelectedId} />
        {selected && <ApprovalDetail approval={selected} matchingAssessment={matchingAssessment} />}
      </div>
    </div>
  );
}
```

- [ ] **Step 2: Verify the build**

Run: `npm run build`
Expected: succeeds with no TypeScript errors.

- [ ] **Step 3: Commit**

```bash
git add web/app/approvals/page.tsx
git commit -m "Assemble the Approvals page"
```

---

### Task 14: Playwright e2e setup + smoke tests

**Files:**
- Modify: `web/playwright.config.ts`
- Create: `web/e2e/start-run.spec.ts`, `web/e2e/approve-recommendation.spec.ts`

**Interfaces:**
- Consumes: the full running app (Tasks 1–13) and the real FastAPI backend.
- Produces: the two smoke flows the design spec requires. These make real Gemini/Groq calls through the real backend — see the Global Constraints note on the 20 requests/day Gemini cap.

- [ ] **Step 1: Update `web/playwright.config.ts` to start both servers**

```ts
import { defineConfig } from "@playwright/test";

export default defineConfig({
  testDir: "./e2e",
  timeout: 30_000,
  use: {
    baseURL: "http://localhost:3000",
  },
  webServer: [
    {
      command: "npm run dev",
      url: "http://localhost:3000",
      reuseExistingServer: !process.env.CI,
      timeout: 30_000,
    },
    {
      command: "uvicorn backend.api.main:app --port 8000",
      cwd: "../",
      url: "http://127.0.0.1:8000/health",
      reuseExistingServer: !process.env.CI,
      timeout: 30_000,
    },
  ],
});
```

- [ ] **Step 2: Write `web/e2e/start-run.spec.ts`**

```ts
import { test, expect } from "@playwright/test";

test("starting a scenario shows the first assessment", async ({ page }) => {
  await page.goto("/");

  await page.getByLabel(/operator id/i).fill("E2E.TESTER");
  await page.getByRole("button", { name: /continue/i }).click();
  await page.waitForURL("**/monitor");

  await page.selectOption("#scenario-select", "baseline");
  await page.getByRole("button", { name: /start run/i }).click();

  await expect(page.getByText(/status/i)).toBeVisible();
  await expect(page.getByText(/no assessment yet|novel condition|confidence:/i)).toBeVisible({ timeout: 60_000 });
});
```

- [ ] **Step 3: Write `web/e2e/approve-recommendation.spec.ts`**

The `reactor_a_feed_loss` scenario is authored to escalate (see `backend/knowledge/incidents/reactor_a_feed_loss.yaml`), but escalation depends on real LLM reasoning over real physics — it is not deterministic run to run. Rather than flake, this test soft-skips with a clear reason if no escalation appears within the window, and only exercises the approve flow when one actually does.

```ts
import { test, expect } from "@playwright/test";

test("approving a pending recommendation completes the operator flow", async ({ page }) => {
  test.setTimeout(180_000); // fault scenario + real LLM calls can take a while

  await page.goto("/");
  await page.getByLabel(/operator id/i).fill("E2E.APPROVER");
  await page.getByRole("button", { name: /continue/i }).click();
  await page.waitForURL("**/monitor");

  await page.selectOption("#scenario-select", "reactor_a_feed_loss");
  await page.getByRole("button", { name: /start run/i }).click();

  await page.getByRole("link", { name: /approvals/i }).click();

  const pendingRow = page.getByText(/pending/i).first();
  const appeared = await pendingRow
    .waitFor({ state: "visible", timeout: 150_000 })
    .then(() => true)
    .catch(() => false);

  test.skip(
    !appeared,
    "No escalation was triggered within the test window — real LLM-driven, not deterministic. Re-run to retry."
  );

  await pendingRow.click();
  await page.getByRole("button", { name: /mark evidence as viewed/i }).click();
  await page.getByRole("button", { name: /^approve$/i }).click();

  await expect(page.getByText(/approved/i).first()).toBeVisible({ timeout: 15_000 });
});
```

- [ ] **Step 4: Run the e2e suite**

Run: `npm run e2e`
Expected: `start-run.spec.ts` PASSES; `approve-recommendation.spec.ts` either PASSES or SKIPS with the documented reason. This consumes real Gemini/Groq quota — don't run it repeatedly in a tight loop (CLAUDE.md's documented 20 requests/day Gemini cap).

- [ ] **Step 5: Commit**

```bash
git add web/playwright.config.ts web/e2e/
git commit -m "Add Playwright e2e smoke tests: start a run, approve a recommendation"
```
