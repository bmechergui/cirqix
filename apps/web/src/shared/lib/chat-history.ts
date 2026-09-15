import type { Message } from '@cirqix/types';

/** Ligne rendue par `GET /api/projects/:id/messages`. */
export interface ProjectMessageRow {
  id: string;
  role: string;
  content: string;
  created_at: string;
}

function isChatRole(role: string): role is Message['role'] {
  return role === 'user' || role === 'assistant';
}

/** `HH:MM` en heure locale — le format des messages envoyés en direct. */
export function formatChatTimestamp(iso: string): string {
  const d = new Date(iso);
  if (Number.isNaN(d.getTime())) return '';
  return `${d.getHours().toString().padStart(2, '0')}:${d.getMinutes().toString().padStart(2, '0')}`;
}

/**
 * Convertit une ligne persistée en `Message`. Un rôle inconnu est écarté
 * (`null`) plutôt qu'affiché de travers : `Message.role` n'admet que
 * `user | assistant`.
 */
export function toChatMessage(row: ProjectMessageRow): Message | null {
  if (!isChatRole(row.role)) return null;
  return {
    id: row.id,
    role: row.role,
    content: row.content,
    timestamp: formatChatTimestamp(row.created_at),
  };
}
