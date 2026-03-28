# Layrix.ai — AI PCB Design Agent

> **Every layer, perfectly designed by AI**

Layrix is a 100% cloud SaaS for PCB design powered by natural language. Describe your circuit, the AI agent generates a DRC-clean PCB, exports Gerbers, and orders from JLCPCB — fully autonomously.

[![CI](https://github.com/bmechergui/layrix/actions/workflows/ci.yml/badge.svg)](https://github.com/bmechergui/layrix/actions/workflows/ci.yml)
![Next.js](https://img.shields.io/badge/Next.js-15-black?logo=next.js)
![TypeScript](https://img.shields.io/badge/TypeScript-strict-blue?logo=typescript)
![Turborepo](https://img.shields.io/badge/Turborepo-monorepo-EF4444?logo=turborepo)

---

## What it does

```
User prompt → Layrix Agent → Schematic → Placement → Routing → DRC fix → Gerbers → JLCPCB
```

1. **Describe** — type your circuit in plain English
2. **Design** — the agent creates schematic, places components, routes traces, fixes all DRC violations
3. **Order** — review in 2D/3D, download Gerbers, or order directly from JLCPCB

---

## Tech Stack

| Layer | Technology |
|-------|-----------|
| Frontend | Next.js 15 · Tailwind CSS · shadcn/ui · Zustand |
| Backend | Next.js API Routes (MVP) |
| AI Agents | Claude SDK — Sonnet 4.6 (orchestrator) + Haiku 4.5 (specialists) |
| Database | Supabase · PostgreSQL · pgvector |
| Queue | Redis · BullMQ (10 concurrent PCBs) |
| KiCad Service | Python · FastAPI · pcbnew · Freerouting · Docker |
| Viewer 2D | PixiJS (WebGL, 60 FPS) |
| Viewer 3D | Three.js + STEP via occt-import-js |
| Auth | Supabase Auth (email + Google OAuth) |
| Payments | Lemon Squeezy (MVP) |
| Infra | Vercel (frontend) · DigitalOcean (KiCad service) |

---

## Monorepo Structure

```
layrix/
├── apps/
│   ├── web/                  # Single Next.js app (landing + dashboard)
│   │   ├── src/app/
│   │   │   ├── (marketing)/  # layrix.ai — landing page
│   │   │   └── (dashboard)/  # app.layrix.ai/dashboard
│   │   ├── src/components/
│   │   │   ├── marketing/    # Navbar, Hero, Features, Pricing…
│   │   │   └── dashboard/    # Sidebar, ChatPanel, ViewerPanel…
│   │   └── src/store/        # Zustand global store
│   └── api/                  # Next.js API routes
├── packages/
│   ├── agents/               # Claude SDK agents (orchestrator + specialists)
│   ├── db/                   # Supabase client + types + migrations
│   ├── ui/                   # Shared UI components
│   ├── config-typescript/    # Shared tsconfig
│   └── config-eslint/        # Shared ESLint config
├── services/
│   └── kicad/                # FastAPI + pcbnew + Freerouting (Docker)
├── docs/                     # Architecture, design system, agent prompts
├── PLAN.md                   # Full implementation plan (6 phases)
└── CLAUDE.md                 # AI assistant context & rules
```

---

## Getting Started

### Prerequisites

- Node.js ≥ 20
- pnpm ≥ 9
- Docker (for KiCad service)

### Install

```bash
git clone https://github.com/bmechergui/layrix.git
cd layrix
pnpm install
```

### Environment Variables

Copy `.env.example` and fill in the values:

```bash
cp .env.example apps/web/.env.local
cp .env.example apps/api/.env.local
```

Required variables:

```env
ANTHROPIC_API_KEY=
SUPABASE_URL=
SUPABASE_ANON_KEY=
SUPABASE_SERVICE_KEY=
REDIS_URL=
LEMON_SQUEEZY_API_KEY=
KICAD_SERVICE_URL=http://localhost:8000
```

### Dev

```bash
# Start all apps (Turborepo)
pnpm dev

# apps/web → http://localhost:3000
# apps/api  → http://localhost:3002
```

### KiCad Service (Docker)

```bash
cd services/kicad
docker compose up
# → http://localhost:8000/health
```

---

## PCB Engine Strategy

| Condition | Engine |
|-----------|--------|
| < 20 components, 2 layers | TSCircuit (fast, Claude generates TSX natively) |
| ≥ 20 components or > 2 layers | KiCad + Freerouting + pcbnew |

Both produce standard Gerber files — the engine selection is invisible to the user.

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

| Plan | Price | Credits |
|------|-------|---------|
| Free | 0€ | 5 / day |
| Maker | 25€/mo | 100 / month |
| Pro | 50€/mo | 300 / month |
| Enterprise | Custom | Unlimited |

---

## Implementation Roadmap

- [x] **Phase 0** — Monorepo setup, DB schema, KiCad Docker, CI/CD
- [x] **Phase 1** — Landing page + waitlist (design system, mock data)
- [ ] **Phase 2** — Auth + dashboard + Claude agent MVP + streaming SSE
- [ ] **Phase 3** — KiCad + Freerouting + footprint cascade + pgvector
- [ ] **Phase 4** — 3D viewer + SPICE simulation + JLCPCB integration + payments
- [ ] **Phase 5** — Rate limiting + E2E tests + monitoring + launch

See [PLAN.md](./PLAN.md) for the full detailed plan.

---

## AI Agents

| Agent | Model | Role |
|-------|-------|------|
| Orchestrator | Claude Sonnet 4.6 | Plans the PCB flow, max 15 iterations |
| Schema Agent | Claude Haiku 4.5 | Generates netlist from prompt |
| Placement Agent | Claude Haiku 4.5 | Places components on board |
| Routing Agent | Claude Haiku 4.5 | Routes traces via Freerouting |
| DRC Agent | Claude Haiku 4.5 | Fixes DRC violations (max 3 iterations) |
| Footprint Agent | Claude Haiku 4.5 | 8-step cascade: DB → KiCad → SnapMagic → AI |

Target cost: **~0.12€ per complete PCB**.

---

## License

Private — All rights reserved © 2025 Layrix Technologies
