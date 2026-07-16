import { z } from 'zod';

const envSchema = z.object({
  NEXT_PUBLIC_SUPABASE_URL: z.string().url('SUPABASE_URL invalide'),
  NEXT_PUBLIC_SUPABASE_ANON_KEY: z.string().min(1, 'SUPABASE_ANON_KEY manquante'),
  SUPABASE_SERVICE_KEY: z.string().min(1, 'SUPABASE_SERVICE_KEY manquante').optional(),
});

const agentEnvSchema = z.object({
  ANTHROPIC_API_KEY: z.string().min(1, 'ANTHROPIC_API_KEY manquante'),
  REDIS_URL: z.string().url('REDIS_URL invalide'),
  KICAD_SERVICE_URL: z.string().url('KICAD_SERVICE_URL invalide'),
  KICAD_SERVICE_TOKEN: z.string().min(32, 'KICAD_SERVICE_TOKEN trop court'),
});

export function validateEnv() {
  const result = envSchema.safeParse(process.env);
  if (!result.success) {
    const errors = result.error.flatten().fieldErrors;
    throw new Error(`Variables d'environnement manquantes :\n${JSON.stringify(errors, null, 2)}`);
  }
  return result.data;
}

export function validateAgentEnv() {
  const result = agentEnvSchema.safeParse(process.env);
  if (!result.success) {
    const errors = result.error.flatten().fieldErrors;
    throw new Error(`Variables agents manquantes :\n${JSON.stringify(errors, null, 2)}`);
  }
  return result.data;
}
