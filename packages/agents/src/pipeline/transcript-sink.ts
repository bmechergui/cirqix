/**
 * Historique de discussion d'un projet (migration 026 `project_messages`).
 *
 * Le chat vivait uniquement dans le store Zustand du navigateur : un
 * rechargement, ou la réouverture du projet, effaçait la conversation.
 *
 * La réponse de l'agent est consignée par le PORTEUR du pipeline (route SSE ou
 * worker), jamais par l'onglet : un run asynchrone dure jusqu'à 20 minutes et
 * l'utilisateur ferme son onglet — c'est précisément le cas où une écriture
 * côté navigateur perdrait la réponse.
 *
 * Deux pièces, séparées pour se tester sans base :
 *   - `TranscriptSink` — décorateur de `RunSink` qui accumule le texte visible ;
 *   - `createChatMessageWriter` — l'écriture d'une ligne, qui ne lève JAMAIS :
 *     perdre une ligne d'historique est un désagrément, perdre un routage de
 *     17 minutes pour cette raison serait absurde.
 */

import { chatTextOfEvent } from '@cirqix/types';
import type { RunEvent, RunSink } from './run-sink';

/** Borne de `project_messages.content` — la même que le CHECK de la migration. */
export const CHAT_MESSAGE_MAX_CHARS = 100_000;

export type ChatRole = 'user' | 'assistant';

export interface ChatMessageInput {
  projectId: string;
  userId: string;
  role: ChatRole;
  content: string;
}

export interface ChatMessageWriter {
  /**
   * `true` si la ligne est écrite. `false` si rien n'est écrit — message vide,
   * ou échec signalé à `onError`. Ne lève jamais.
   */
  append(message: ChatMessageInput): Promise<boolean>;
}

/** Ligne insérée dans `project_messages`. */
export interface ProjectMessageInsert {
  project_id: string;
  user_id: string;
  role: ChatRole;
  content: string;
}

/** Ce que l'écriture exige d'un client — un `SupabaseClient` y satisfait. */
export interface ChatMessageTableClient {
  from(table: string): {
    insert(row: ProjectMessageInsert): PromiseLike<{ error: unknown }>;
  };
}

/** Transmet chaque événement tel quel et retient le texte de la bulle de l'agent. */
export class TranscriptSink implements RunSink {
  private text = '';

  constructor(private readonly inner: RunSink) {}

  async emit(event: RunEvent): Promise<void> {
    // Retenir AVANT de transmettre : si le transport lève (flux SSE fermé par
    // un onglet parti), la réponse doit tout de même rejoindre l'historique.
    const chunk = chatTextOfEvent(event);
    if (chunk !== null) this.text += chunk;
    await this.inner.emit(event);
  }

  transcript(): string {
    return this.text;
  }
}

export function createChatMessageWriter(
  client: ChatMessageTableClient,
  onError?: (err: unknown, message: ChatMessageInput) => void,
): ChatMessageWriter {
  return {
    async append(message: ChatMessageInput): Promise<boolean> {
      if (message.content.trim() === '') return false;
      const row: ProjectMessageInsert = {
        project_id: message.projectId,
        user_id: message.userId,
        role: message.role,
        content: message.content.slice(0, CHAT_MESSAGE_MAX_CHARS),
      };
      try {
        const { error } = await client.from('project_messages').insert(row);
        if (error) {
          onError?.(error, message);
          return false;
        }
        return true;
      } catch (err) {
        onError?.(err, message);
        return false;
      }
    },
  };
}
