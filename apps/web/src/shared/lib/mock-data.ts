export type { PCBStatus, Plan, Project, Message, Credits } from '@cirqix/types';
import type { Project, Message, Credits } from '@cirqix/types';

export const MOCK_PROJECTS: Project[] = [
  { id: '1', name: 'ESP32 Weather Station', description: 'BLE + WiFi, BME280, SSD1306 OLED, LiPo', status: 'DRC_CLEAN', iteration_count: 7, created_at: '2026-03-25', updated_at: '2026-03-27' },
  { id: '2', name: 'Motor Driver Shield', description: 'Dual H-bridge for NEMA17 stepper motors', status: 'ROUTING_DONE', iteration_count: 4, created_at: '2026-03-20', updated_at: '2026-03-26' },
  { id: '3', name: 'USB-C Power Delivery', description: 'PD 100W negotiation with protection', status: 'PLACEMENT_DONE', iteration_count: 2, created_at: '2026-03-18', updated_at: '2026-03-22' },
  { id: '4', name: 'Audio DAC Board', description: 'PCM5102A, I2S input, RCA & 3.5mm output', status: 'SCHEMA_DONE', iteration_count: 1, created_at: '2026-03-15', updated_at: '2026-03-15' },
  { id: '5', name: 'LoRa Gateway', description: 'SX1276 + RPi CM4, outdoor IP67 enclosure', status: 'INITIAL', iteration_count: 0, created_at: '2026-03-28', updated_at: '2026-03-28' },
];

export const MOCK_MESSAGES: Message[] = [
  { id: '1', role: 'user', content: 'Create an ESP32-S3 weather station PCB with BME280, SSD1306 OLED, LiPo charging, and USB-C.', timestamp: '10:32' },
  { id: '2', role: 'assistant', content: "I'll design your ESP32-S3 weather station. Let me start by creating the schematic...\n\n**Components identified:**\n- ESP32-S3-WROOM-1 (main MCU)\n- BME280 (temp/humidity/pressure, I2C)\n- SSD1306 128×64 OLED (I2C)\n- TP4056 (LiPo charging)\n- USB-C port (5V input)\n\nGenerating netlist...", timestamp: '10:32' },
  { id: '3', role: 'assistant', content: '✅ **Schema complete** — 14 components, 3 power nets (3.3V, 5V, VBAT)\n\nStarting component placement on 60×40mm board...', timestamp: '10:33' },
  { id: '4', role: 'assistant', content: '✅ **Placement done** — All 14 components placed. Starting Freerouting autoroute...', timestamp: '10:34' },
  { id: '5', role: 'assistant', content: '✅ **Routing complete** — 47 tracks, 2 layers, 0 unrouted. Running DRC check...', timestamp: '10:35' },
  { id: '6', role: 'assistant', content: '✅ **DRC clean!** Your PCB is ready.\n\n**Summary:**\n- Board: 60×40mm, 2 layers\n- Components: 14\n- Tracks: 47 · Vias: 8\n- DRC violations: 0\n\nReady to export Gerbers or order from JLCPCB?', timestamp: '10:36' },
];

export const MOCK_CREDITS: Credits = { balance: 67.5, plan: 'pro', daily_limit: null };
