-- Phase 3.2 — insert ERC_CLEAN status between SCHEMA_DONE and PLACEMENT_DONE.
-- ERC = Electrical Rules Check on the .kicad_sch produced by Circuit-Synth.
-- Idempotent : DROP IF EXISTS so reapplying is safe.

ALTER TABLE projects DROP CONSTRAINT IF EXISTS projects_status_check;

ALTER TABLE projects ADD CONSTRAINT projects_status_check CHECK (status IN (
  'INITIAL',
  'SCHEMA_DONE',
  'ERC_CLEAN',
  'PLACEMENT_DONE',
  'ROUTING_DONE',
  'DRC_CLEAN',
  'PCB_LIVRÉ'
));
