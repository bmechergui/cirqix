import { spawn } from 'node:child_process';
import { tmpdir } from 'node:os';
import type { SchemaJson } from '../../engines/engine-router';
import { log } from '../shared';
import { SCHEMA_SYSTEM_PROMPT, parseSchemaText, messageUtilisateur } from './schema-prompt';

/**
 * Claude Code écrit le schéma — `claude -p`, sortie JSON, MÊME contrat que
 * Haiku (`SCHEMA_SYSTEM_PROMPT`, `parseSchemaText`). Décision D-2026-09-13-a.
 *
 * ⚠️ Le prompt part par STDIN, jamais en argument : sous Windows le binaire est
 * un `.cmd` qui exige un shell, et une description qui contient des guillemets
 * ou des retours à la ligne casserait la ligne de commande — ou pire, y
 * injecterait une commande.
 *
 * ⚠️ Le répertoire de travail est un dossier TEMPORAIRE : lancé depuis le
 * dépôt, `claude -p` charge `CLAUDE.md` et ses règles — mesuré à 130 000
 * jetons de contexte pour répondre `{"ok":true}`, 2,6 $ l'appel contre 0,96 $
 * depuis un dossier neutre. Le schéma n'a rien à faire de ces règles.
 *
 * Rend `null` sur toute panne (binaire absent, délai, JSON illisible) : le
 * handler refuse alors le run, il ne fabrique jamais un schéma de repli.
 */
export interface ClaudeCodeOptions {
  /** Binaire à lancer ; `CIRQIX_CLAUDE_CODE_BIN` ou `claude`. */
  bin?: string;
  /** Modèle passé à `--model` ; défaut du CLI si absent. */
  model?: string;
  /** Délai maximal, ms. Un schéma tient en une réponse : 5 min est large. */
  timeoutMs?: number;
  /** Point d'injection pour les tests : exécute le CLI et rend sa sortie. */
  executer?: Executer;
}

export type Executer = (
  bin: string,
  args: string[],
  stdin: string,
  timeoutMs: number,
) => Promise<{ stdout: string; code: number | null }>;

const DELAI_PAR_DEFAUT_MS = 5 * 60_000;

/**
 * L environnement du CLI, SANS les variables d authentification API.
 *
 * ⚠️ Mesure du 2026-09-13, run 0525dc97 : le worker porte `ANTHROPIC_API_KEY`
 * (pour Haiku) ; `claude -p` l a heritee et l a preferee a la session
 * claude.ai — « claude.ai connectors are disabled because ANTHROPIC_API_KEY
 * ... takes precedence over your claude.ai login » — puis a echoue sur le
 * solde a zero de cette cle. Tout l interet du fournisseur est l abonnement :
 * on retire la cle, le jeton et l URL de base avant de lancer le CLI.
 */
export const VARIABLES_AUTH_API = ['ANTHROPIC_API_KEY', 'ANTHROPIC_AUTH_TOKEN', 'ANTHROPIC_BASE_URL'] as const;

export function envPourClaudeCode(env: NodeJS.ProcessEnv): NodeJS.ProcessEnv {
  const propre: NodeJS.ProcessEnv = { ...env };
  for (const nom of VARIABLES_AUTH_API) delete propre[nom];
  return propre;
}

/** Exécution réelle : stdin → `claude -p`, stdout collecté, délai respecté. */
export const executerClaudeCode: Executer = (bin, args, stdin, timeoutMs) =>
  new Promise((resolve, reject) => {
    const enfant = spawn(bin, args, {
      cwd: tmpdir(),
      env: envPourClaudeCode(process.env),
      shell: process.platform === 'win32',
      stdio: ['pipe', 'pipe', 'pipe'],
      windowsHide: true,
    });
    let stdout = '';
    let stderr = '';
    const minuteur = setTimeout(() => {
      enfant.kill();
      reject(new Error(`claude -p : délai de ${timeoutMs} ms dépassé`));
    }, timeoutMs);
    enfant.stdout.on('data', (d: Buffer) => { stdout += d.toString('utf8'); });
    enfant.stderr.on('data', (d: Buffer) => { stderr += d.toString('utf8'); });
    enfant.on('error', (err) => { clearTimeout(minuteur); reject(err); });
    enfant.on('close', (code) => {
      clearTimeout(minuteur);
      if (code !== 0) log.warn({ code, stderr: stderr.slice(0, 500) }, 'claude -p : sortie non nulle');
      resolve({ stdout, code });
    });
    enfant.stdin.end(stdin);
  });

/** Le texte de la réponse dans l'enveloppe `--output-format json`. */
export function texteDeLEnveloppe(stdout: string): string | null {
  try {
    const env = JSON.parse(stdout) as Record<string, unknown>;
    if (env['is_error'] === true) return null;
    if (typeof env['result'] === 'string') return env['result'];
    // Une enveloppe sans texte ne rend rien ; un JSON qui n en est pas une
    // (le schema nu, ancien CLI ou --output-format text) est rendu tel quel.
    return 'result' in env || 'is_error' in env || 'type' in env ? null : stdout;
  } catch {
    // Pas une enveloppe : peut-être le JSON nu (ancien CLI, ou --output-format text).
    return stdout.trim() ? stdout : null;
  }
}

export async function generateSchemaWithClaudeCode(
  description: string,
  options: ClaudeCodeOptions = {},
  retour?: string,
): Promise<SchemaJson | null> {
  const bin = options.bin ?? process.env['CIRQIX_CLAUDE_CODE_BIN'] ?? 'claude';
  const model = options.model ?? process.env['CIRQIX_CLAUDE_CODE_MODEL'];
  const timeoutMs = options.timeoutMs ?? DELAI_PAR_DEFAUT_MS;
  const executer = options.executer ?? executerClaudeCode;
  const args = ['-p', '--output-format', 'json', ...(model ? ['--model', model] : [])];
  const stdin = `${SCHEMA_SYSTEM_PROMPT}\n\n${messageUtilisateur(description, retour)}`;
  try {
    const debut = Date.now();
    const { stdout } = await executer(bin, args, stdin, timeoutMs);
    const texte = texteDeLEnveloppe(stdout);
    if (!texte) {
      log.warn({ bin }, 'schema agent: Claude Code a rendu une réponse vide ou en erreur');
      return null;
    }
    const schema = parseSchemaText(texte);
    if (!schema) {
      log.warn({ bin, len: texte.length }, 'schema agent: Claude Code a rendu un schéma illisible');
      return null;
    }
    log.info({ bin, composants: schema.components.length, ms: Date.now() - debut }, 'schema agent: schéma écrit par Claude Code');
    return schema;
  } catch (err) {
    log.warn({ err, bin }, 'schema agent: Claude Code injoignable ou en panne — aucun schéma fabriqué');
    return null;
  }
}
