import type { SupabaseClient } from '@supabase/supabase-js';
import { logger } from '@cirqix/logger';

const log = logger.child({ module: 'kicad-storage' });

const BUCKET = 'kicad-files';
const SIGNED_URL_EXPIRES_SECONDS = 60 * 60; // 1h

interface UploadResult {
  signedUrl: string | null;
  path: string;
}

export async function uploadKicadArtifact(
  supabase: SupabaseClient,
  userId: string,
  projectId: string,
  filename: 'schematic.kicad_sch' | 'pcb.kicad_pcb',
  content: string,
): Promise<UploadResult> {
  const path = `${userId}/${projectId}/${filename}`;
  // KiCad files are plain S-expression text. The bucket whitelist accepts
  // only 'text/plain' and 'application/octet-stream' — must be exact, no
  // charset suffix (Supabase Storage matches strictly).
  const contentType = 'text/plain';

  log.debug({ path, bytes: content.length }, 'upload start');

  const { error: uploadError } = await supabase.storage
    .from(BUCKET)
    .upload(path, content, {
      contentType,
      upsert: true,
      cacheControl: '0',
    });
  if (uploadError) {
    log.error({ path, err: uploadError }, 'upload FAILED');
    return { signedUrl: null, path };
  }
  log.debug({ path }, 'upload OK');

  const { data: signed, error: signError } = await supabase.storage
    .from(BUCKET)
    .createSignedUrl(path, SIGNED_URL_EXPIRES_SECONDS);
  if (signError || !signed) {
    log.error({ path, err: signError }, 'sign FAILED');
    return { signedUrl: null, path };
  }
  log.debug({ path }, 'signed URL ready');

  return { signedUrl: signed.signedUrl, path };
}
