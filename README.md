# Cirqix.ai — AI PCB Design Agent

> **From idea to manufacturable PCB, autonomously**

Cirqix is a 100% cloud SaaS for PCB design powered by natural language. Describe your circuit, the AI agent generates a DRC-clean PCB, exports Gerbers, and orders from JLCPCB — fully autonomously.

[![CI](https://github.com/bmechergui/cirqix/actions/workflows/ci.yml/badge.svg)](https://github.com/bmechergui/cirqix/actions/workflows/ci.yml)
![Next.js](https://img.shields.io/badge/Next.js-15-black?logo=next.js)
![TypeScript](https://img.shields.io/badge/TypeScript-strict-blue?logo=typescript)
![Turborepo](https://img.shields.io/badge/Turborepo-monorepo-EF4444?logo=turborepo)

---

## What it does

```
User prompt → 8 AI Agents → Schematic → ERC → Footprints → PCB → Placement → Routing → DRC → Gerbers → JLCPCB
```

1. **Describe** — type your circuit in natural language
2. **Design** — 8 specialized AI agents create schematic, resolve footprints, place components, route traces, fix all DRC violations
3. **Review** — visualize schematic + PCB in KiCanvas, inspect in 3D, run SPICE simulation
4. **Order** — download Gerbers/BOM, or order directly from JLCPCB (confirmation required)

---

## Tech Stack

| Layer | Technology |
|-------|-----------|
| Frontend | Next.js 15 · Tailwind CSS · shadcn/ui · Zustand |
| Backend | Next.js API Routes |
| AI Agents | Claude SDK — Sonnet 4.6 (orchestrator) + 8× Haiku 4.5 (specialists) |
| PCB Engine | Circuit-Synth (Python pip) → native `.kicad_sch` + `.kicad_pcb` |
| KiCad Service | FastAPI · pcbnew · Freerouting · kicad-cli · ngspice · Docker |
| Database | Supabase · PostgreSQL · pgvector (footprint embeddings) |
| Queue | Redis · BullMQ (10 concurrent PCBs) |
| Viewer Schematic + PCB | KiCanvas (native `.kicad_sch` / `.kicad_pcb` from Supabase Storage) |
| Viewer 3D | Three.js + STEP via occt-import-js (Pro plan+) |
| SPICE Simulation | ngspice batch → parsed waveforms → Recharts (Pro plan+) |
| Auth | Supabase Auth (email + Google OAuth) |
| Payments | Lemon Squeezy |
| Infra | Vercel (frontend) · Railway (api) · DigitalOcean (KiCad service) |

---

## Monorepo Structure

```
cirqix/
├── apps/
│   └── web/                          # Next.js 15 app — port 3333
│       ├── src/app/
│       │   ├── (marketing)/          # cirqix.ai — landing, pricing, waitlist
│       │   ├── (workspace)/          # cirqix.ai/dashboard — auth required
│       │   └── api/                  # API Routes: /agent (SSE), /jlcpcb/order, /webhooks
│       ├── src/features/             # FSD: auth, chat-agent, credits, dashboard, marketing
│       ├── src/widgets/viewer/       # KiCanvas viewer (schematic + PCB) + Three.js 3D
│       ├── src/entities/             # project, pcb, credits
│       ├── src/shared/               # ui (shadcn), store (Zustand), lib, types
│       └── src/middleware.ts         # Supabase Auth JWT — protects /dashboard/*
├── packages/
│   ├── agents/                       # Claude SDK — orchestrator + 8 specialists + engines
│   │   └── src/engines/              # schematic-engine · placement-service · routing-service
│   │                                 # drc-service · export-service · footprint-service
│   ├── types/                        # @cirqix/types — single source of truth
│   ├── db/                           # Supabase client + migrations
│   ├── logger/                       # Pino logger
│   ├── utils/                        # cn() helpers
│   ├── ui/                           # Shared shadcn/ui components
│   ├── config-typescript/            # Shared strict tsconfig
│   └── config-eslint/                # Shared ESLint config
├── services/
│   └── kicad/                        # FastAPI + Circuit-Synth + pcbnew + Freerouting (Docker)
│       └── routers/                  # kicad_gen · placement · routing · drc · export · erc · simulation
├── docs/                             # Architecture, design system, agent prompts
├── PLAN.md                           # Full implementation plan (6 phases)
└── CLAUDE.md                         # AI assistant context & rules
```

---

## Getting Started

### Prerequisites

- Node.js ≥ 20
- pnpm ≥ 9 — **required** (`npm install` breaks the workspace)
- Docker (for KiCad service)

```bash
npm install -g pnpm   # install pnpm if needed
```

### Install

```bash
git clone https://github.com/bmechergui/cirqix.git
cd cirqix
pnpm install          # always use pnpm — never npm install
```

### Environment Variables

Copy `.env.example` and fill in the values:

```bash
cp .env.example apps/web/.env.local
```

Required variables:

```env
ANTHROPIC_API_KEY=
NEXT_PUBLIC_SUPABASE_URL=
NEXT_PUBLIC_SUPABASE_ANON_KEY=
SUPABASE_SERVICE_KEY=
REDIS_URL=
LEMON_SQUEEZY_API_KEY=
KICAD_SERVICE_URL=http://localhost:8766

# Agent mode: 'simulator' (no API calls) or 'orchestrator' (real Claude + Circuit-Synth)
CIRQIX_AGENT_MODE=orchestrator
```

### Dev

```bash
# Start all apps (Turborepo)
pnpm dev

# apps/web → http://localhost:3333
```

### KiCad Service (Docker — WSL recommended on Windows)

```bash
cd services/kicad
docker compose up -d
# → http://localhost:8766/health
```

---

## Agent Pipeline

**8 specialized agents** orchestrated by Claude Sonnet 4.6 (max 15 iterations per PCB):

```
User → Sonnet 4.6 (orchestrator)
  ① Schema Agent    (Haiku 4.5) — Circuit-Synth Python → .kicad_sch
  ② ERC Agent       (Haiku 4.5) — kicad-cli ERC, auto-fix loop
  ③ Footprint Agent (Haiku 4.5) — 4-step cascade per component ref
  ④ KiCad Agent     (Haiku 4.5) — .kicad_pcb from schema + footprints
  ⑤ Placement Agent (Haiku 4.5) — pcbnew SetPosition/SetOrientationDegrees
  ⑥ Routing Agent   (Haiku 4.5) — Freerouting .dsn → .ses → .kicad_pcb
  ⑦ DRC Agent       (Haiku 4.5) — kicad-cli DRC, auto-fix loop (max 3×)
  ⑧ Export Agent    (Haiku 4.5) — Gerbers + drill + CPL zip → Supabase Storage
```

**Footprint cascade** (stops at first success):
1. KiCad official libraries (instant, free)
2. pgvector community cache (instant, free)
3. LCSC / EasyEDA API (by LCSC part number)
4. AI generation by Haiku (3 credits)

**Token optimization:** KiCad blob content (`kicad_sch_content`, `kicad_pcb_content`, Gerbers) is stripped from Sonnet tool_result messages → **~70% token savings** (~0.25€ vs 0.86€ per run).

Target cost: **~0.12€ per complete PCB**.

---

## Credit System

| Action | Credits |
|--------|---------|
| Chat message | 0.5 |
| Schematic | 2 |
| Placement | 2 |
| Routing | 3 |
| DRC check | 1 |
| Export Gerbers | 1 |
| Footprint AI | 3 |
| 3D view | 1 |
| SPICE simulation | 3 |

| Plan       | Price      | Credits        | Max layers |
|------------|------------|----------------|------------|
| Free       | 0€         | 5 / day        | 2          |
| Pro        | 25€/mo     | 100 / month    | 4          |
| Pro Max    | 50€/mo     | 300 / month    | 8          |
| Enterprise | Custom     | Unlimited      | Unlimited  |

---

## Implementation Roadmap

- [x] **Phase 0** — Monorepo setup, DB schema, KiCad Docker, CI/CD
- [x] **Phase 1** — Landing page + waitlist (design system, mock data)
- [x] **Phase 2** — Auth + dashboard + Claude agent + SSE streaming + Circuit-Synth + KiCanvas viewer + credits
- [x] **Phase 3** — pcbnew placement + Freerouting routing + kicad-cli DRC + Gerbers/BOM export + footprint cascade (KiCad/pgvector/LCSC/SnapMagic/AI)
- [x] **Phase 4.1** — 3D viewer (Three.js + STEP/occt-import-js, Pro+)
- [x] **Phase 4.2** — SPICE simulation (ngspice batch + Recharts waveforms, Pro+)
- [x] **Phase 4.3** — JLCPCB integration (Gerbers + BOM download, order with confirmation gate)
- [ ] **Phase 4.4** — Lemon Squeezy payments (webhooks + billing page + top-ups)
- [ ] **Phase 5** — Rate limiting + E2E tests + monitoring + launch

See [PLAN.md](./PLAN.md) for the full detailed plan.

---

## License

Private — All rights reserved © 2026 Cirqix Technologies
