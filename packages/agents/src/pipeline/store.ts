/**
 * Persistance d'un run — ce que le pipeline demande, sans savoir qui le fait.
 *
 * Le pipeline dépendait de Supabase par trois points : l'upload des artefacts
 * KiCad, la mise à jour de `projects`, et la RPC de finalisation. C'est ce qui
 * l'empêchait de tourner ailleurs que dans la route web — donc de sortir de
 * l'invocation plafonnée à 300 s, alors qu'un routage complexe en demande 900 et
 * davantage.
 *
 * Cette interface est la frontière. Le porteur fournit l'implémentation :
 * l'adaptateur Supabase de `apps/web` aujourd'hui, le worker demain, avec le
 * même code de pipeline.
 *
 * ⚠️ `finalizeSuccess` ne prend PAS de provenance en paramètre, et c'est
 * délibéré. `agent_mode` gouverne le gate de `POST /api/jlcpcb/order` — une
 * commande réelle et payante. Le pipeline ne doit pas pouvoir déclarer la
 * sienne : c'est le porteur qui la connaît, parce que c'est lui qui a décidé
 * quel chemin exécuter. Un bug dans le pipeline ne peut donc plus promouvoir un
 * repli en run commandable.
 */

import type { PCBState, PCBStatus } from '@cirqix/types';

/**
 * Artefacts KiCad qu'un run peut déposer.
 *
 * Union fermée à dessein : le viewer et le bucket s'appuient sur ces deux noms
 * exacts. Un nom libre laisserait passer une faute de frappe jusqu'au stockage,
 * où elle produirait un artefact que rien ne saurait relire.
 */
export type KicadArtifactName = 'schematic.kicad_sch' | 'pcb.kicad_pcb';

/** Résultat d'un dépôt d'artefact. `signedUrl` absent = échec non bloquant. */
export interface StoredArtifact {
  signedUrl?: string | undefined;
}

export interface PipelineStore {
  /**
   * Dépose un fichier KiCad et renvoie une URL signée pour le viewer.
   * Un échec ne doit pas interrompre le run : le board reste valide sans son
   * aperçu.
   */
  uploadArtifact(name: KicadArtifactName, content: string): Promise<StoredArtifact>;

  /**
   * Publie un état intermédiaire. Best-effort : la progression est un confort,
   * l'interrompre pour une écriture ratée coûterait le run entier.
   */
  persistProgress(status: PCBStatus, state: PCBState): Promise<void>;

  /**
   * Clôt le run : débit et publication de l'état atteint, en une transaction.
   * La provenance appartient au porteur, jamais au pipeline.
   */
  finalizeSuccess(status: PCBStatus, state: PCBState): Promise<void>;
}
