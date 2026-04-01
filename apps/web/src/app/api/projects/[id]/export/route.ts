import { NextRequest, NextResponse } from 'next/server';
import JSZip from 'jszip';
import { createRouteHandlerClient } from '@/shared/lib/supabase-server';
import { runTSCircuitEngine } from '@layrix/agents';
import type { SchemaJson } from '@layrix/agents';

export async function GET(
  _req: NextRequest,
  { params }: { params: Promise<{ id: string }> }
) {
  const { id } = await params;
  const supabase = await createRouteHandlerClient();

  const { data: { user } } = await supabase.auth.getUser();
  if (!user) {
    return NextResponse.json({ success: false, error: 'Unauthorized' }, { status: 401 });
  }

  // Fetch project pcb_state
  const { data, error } = await supabase
    .from('projects')
    .select('pcb_state, name')
    .eq('id', id)
    .eq('user_id', user.id)
    .single();

  if (error) {
    const status = error.code === 'PGRST116' ? 404 : 500;
    return NextResponse.json({ success: false, error: error.message }, { status });
  }

  const pcbState = data.pcb_state as Record<string, unknown> | null;

  if (!pcbState) {
    return NextResponse.json(
      { success: false, error: 'No PCB data yet. Run the agent first.' },
      { status: 422 }
    );
  }

  // Re-run engine to get Gerbers from the stored schema
  const schema = extractSchema(pcbState);
  if (!schema.components.length) {
    return NextResponse.json(
      { success: false, error: 'PCB state has no components.' },
      { status: 422 }
    );
  }

  const boardW = Number(pcbState['board_width_mm'] ?? 50);
  const boardH = Number(pcbState['board_height_mm'] ?? 50);
  const result = await runTSCircuitEngine(schema, boardW, boardH);

  if (!Object.keys(result.gerbers).length) {
    return NextResponse.json(
      { success: false, error: 'Gerber generation failed.' },
      { status: 500 }
    );
  }

  // Build ZIP
  const zip = new JSZip();
  const projectName = sanitizeFilename(String(data.name ?? 'layrix_pcb'));

  for (const [layer, content] of Object.entries(result.gerbers)) {
    const ext = gerberExtension(layer);
    zip.file(`${projectName}_${layer}${ext}`, content);
  }

  // Add basic BOM
  const bom = [
    'Ref,Value,Footprint,LCSC',
    ...schema.components.map((c) => `${c.ref},${c.value},${c.footprint},${c.lcsc ?? ''}`),
  ].join('\n');
  zip.file(`${projectName}_BOM.csv`, bom);

  const zipBuffer = await zip.generateAsync({ type: 'uint8array' });

  return new Response(zipBuffer as unknown as BodyInit, {
    headers: {
      'Content-Type': 'application/zip',
      'Content-Disposition': `attachment; filename="${projectName}_gerbers.zip"`,
      'Cache-Control': 'no-store',
    },
  });
}

// --- Helpers -------------------------------------------------------------

function extractSchema(pcbState: Record<string, unknown>): SchemaJson {
  // Try placements field (set by call_agent_placement)
  const placements = pcbState['placements'] as Array<{ ref: string }> | undefined;
  if (placements?.length) {
    return {
      components: placements.map((p) => ({
        ref: p.ref,
        value: String((pcbState['components'] as Record<string, string> | undefined)?.[p.ref] ?? p.ref),
        footprint: '0402',
      })),
      nets: (pcbState['nets'] as string[] | undefined) ?? [],
    };
  }

  // Try components field directly
  const components = pcbState['components'] as SchemaJson['components'] | undefined;
  if (Array.isArray(components) && components.length) {
    return {
      components,
      nets: (pcbState['nets'] as string[] | undefined) ?? [],
    };
  }

  return { components: [], nets: [] };
}

function sanitizeFilename(name: string): string {
  return name.replace(/[^a-zA-Z0-9_\-]/g, '_').slice(0, 50);
}

function gerberExtension(layer: string): string {
  const map: Record<string, string> = {
    'F.Cu': '.gtl', 'B.Cu': '.gbl',
    'F.SilkS': '.gto', 'B.SilkS': '.gbo',
    'F.Mask': '.gts', 'B.Mask': '.gbs',
    'Edge.Cuts': '.gko',
    'drill': '.drl',
  };
  return map[layer] ?? '.gbr';
}
