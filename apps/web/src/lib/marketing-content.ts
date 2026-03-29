import { Zap, Eye, Cpu, Package, Coins, Activity, type LucideIcon } from 'lucide-react';

// ─── Features ────────────────────────────────────────────────────────────────

export interface Feature {
  icon: LucideIcon;
  label: string;
  title: string;
  desc: string;
  accent: 'primary' | 'copper';
}

export const FEATURES: Feature[] = [
  {
    icon: Zap,
    label: 'AGENT_CORE',
    title: 'Autonomous Agent',
    desc: 'Describe your circuit. Layrix plans, routes, fixes DRC violations and delivers Gerbers — no human intervention.',
    accent: 'primary',
  },
  {
    icon: Eye,
    label: 'VIEWER_2D3D',
    title: '2D / 3D Viewer',
    desc: 'Inspect every layer in real-time at 60 FPS. Switch to 3D with realistic FR4 and copper materials.',
    accent: 'primary',
  },
  {
    icon: Cpu,
    label: 'FOOTPRINT_AI',
    title: 'Auto Footprint',
    desc: 'Missing footprint? Layrix searches SnapMagic, reads the datasheet with Vision AI and generates it automatically.',
    accent: 'copper',
  },
  {
    icon: Package,
    label: 'JLCPCB_INT',
    title: 'JLCPCB Ready',
    desc: 'BOM, CPL, Gerbers — perfectly formatted. One click to request a quote and order fabrication.',
    accent: 'copper',
  },
  {
    icon: Coins,
    label: 'CREDIT_SYS',
    title: 'Pay as you go',
    desc: 'Free tier included. Maker and Pro plans for professionals. Credits never expire.',
    accent: 'primary',
  },
  {
    icon: Activity,
    label: 'SPICE_SIM',
    title: 'SPICE Simulation',
    desc: 'Run transient, AC and DC analysis before ordering. Powered by ngspice. Pro plan feature.',
    accent: 'copper',
  },
];

// ─── How It Works ─────────────────────────────────────────────────────────────

export interface Step {
  num: string;
  title: string;
  desc: string;
  label: string;
}

export const HOW_IT_WORKS_STEPS: Step[] = [
  {
    num: '01',
    title: 'Describe',
    desc: 'Type your circuit requirements in plain English. Components, constraints, form factor — anything goes.',
    label: 'PROMPT_INPUT',
  },
  {
    num: '02',
    title: 'Design',
    desc: 'The Layrix agent autonomously creates the schematic, places components, routes traces and fixes all DRC violations.',
    label: 'AGENT_RUN',
  },
  {
    num: '03',
    title: 'Order',
    desc: 'Review your PCB in 2D or 3D, download Gerbers or order directly from JLCPCB with one click.',
    label: 'EXPORT_GERBERS',
  },
];

// ─── Pricing ──────────────────────────────────────────────────────────────────

export type PricingCtaVariant = 'default' | 'secondary' | 'outline';

export interface PricingPlan {
  name: string;
  price: string;
  period: string;
  popular: boolean;
  credits: string;
  layers: string;
  features: string[];
  cta: string;
  ctaVariant: PricingCtaVariant;
}

export const PRICING_PLANS: PricingPlan[] = [
  {
    name: 'Free',
    price: '0€',
    period: '',
    popular: false,
    credits: '5 credits / day',
    layers: '2 layers max',
    features: ['2D viewer', 'Basic footprint search', 'TSCircuit engine', 'Community footprints'],
    cta: 'Get started',
    ctaVariant: 'secondary',
  },
  {
    name: 'Maker',
    price: '25€',
    period: '/mo',
    popular: true,
    credits: '100 credits / month',
    layers: '4 layers',
    features: ['Everything in Free', '3D viewer', 'Footprint AI generation', 'KiCad + Freerouting', 'Priority queue'],
    cta: 'Start free trial',
    ctaVariant: 'default',
  },
  {
    name: 'Pro',
    price: '50€',
    period: '/mo',
    popular: false,
    credits: '300 credits / month',
    layers: '8 layers',
    features: ['Everything in Maker', 'SPICE simulation', 'Export .kicad_mod', 'API access', 'Dedicated support'],
    cta: 'Start free trial',
    ctaVariant: 'outline',
  },
  {
    name: 'Enterprise',
    price: 'Custom',
    period: '',
    popular: false,
    credits: 'Unlimited credits',
    layers: 'Unlimited layers',
    features: ['Everything in Pro', 'SSO / SAML', 'Custom integrations', 'SLA guarantee', 'Dedicated CSM'],
    cta: 'Contact us',
    ctaVariant: 'secondary',
  },
];

export const CREDIT_COSTS: [string, string][] = [
  ['Chat message', '0.5'],
  ['Schema', '2'],
  ['Placement', '2'],
  ['Routing', '3'],
  ['DRC check', '1'],
  ['Export Gerbers', '1'],
  ['Footprint AI', '3'],
  ['3D view', '1'],
  ['SPICE sim', '3'],
];

// ─── Comparison ───────────────────────────────────────────────────────────────

export const COMPARISON_FEATURES: string[] = [
  'Autonomous agent',
  'Natural language input',
  'Auto DRC fix',
  'JLCPCB integration',
  '3D viewer',
  'SPICE simulation',
  'Footprint generation',
];

export interface ComparisonTool {
  name: string;
  values: boolean[];
  price: string;
}

export const COMPARISON_TOOLS: ComparisonTool[] = [
  { name: 'Layrix',  values: [true, true, true, true, true, true, true],    price: 'from 0€' },
  { name: 'Flux.ai', values: [false, true, false, false, true, false, false], price: '$99/mo' },
  { name: 'Quilter', values: [true, false, true, false, false, false, false], price: '$49/mo' },
  { name: 'KiCad',   values: [false, false, false, false, true, true, false], price: 'Free' },
];

// ─── Footer ───────────────────────────────────────────────────────────────────

export const FOOTER_LINKS: Record<string, string[]> = {
  Product: ['Features', 'Pricing', 'Changelog', 'Roadmap'],
  Resources: ['Docs', 'API Reference', 'Blog', 'Status'],
  Company: ['About', 'Careers', 'Privacy', 'Terms'],
};
