'use client';

import { use, useState, useRef, useEffect } from 'react';
import { useRouter } from 'next/navigation';
import { ChatPanel } from '@/features/dashboard/ui/ChatPanel';
import { ViewerPanel } from '@/widgets/viewer';
import { AgentProgressBar } from '@/features/dashboard/ui/AgentProgressBar';
import { useAppStore } from '@/shared/store/app-store';
import { Pencil, Trash2 } from 'lucide-react';

function ProjectTitle({ projectId, initialName }: { projectId: string; initialName: string }) {
  const updateProjectName = useAppStore((s) => s.updateProjectName);
  const [editing, setEditing] = useState(false);
  const [value, setValue] = useState(initialName);
  const inputRef = useRef<HTMLInputElement>(null);

  useEffect(() => { setValue(initialName); }, [initialName]);
  useEffect(() => { if (editing) inputRef.current?.select(); }, [editing]);

  const commit = async () => {
    const trimmed = value.trim();
    if (!trimmed || trimmed === initialName) { setValue(initialName); setEditing(false); return; }
    updateProjectName(projectId, trimmed);
    setEditing(false);
    await fetch(`/api/projects/${projectId}`, {
      method: 'PATCH',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ name: trimmed }),
    });
  };

  if (editing) {
    return (
      <input
        ref={inputRef}
        value={value}
        onChange={(e) => setValue(e.target.value)}
        onBlur={() => { void commit(); }}
        onKeyDown={(e) => {
          if (e.key === 'Enter') { void commit(); }
          if (e.key === 'Escape') { setValue(initialName); setEditing(false); }
        }}
        maxLength={100}
        className="text-sm font-semibold bg-transparent border-b border-primary outline-none text-foreground w-full max-w-[240px]"
      />
    );
  }

  return (
    <button
      type="button"
      onClick={() => setEditing(true)}
      className="group flex items-center gap-1.5 text-sm font-semibold text-foreground hover:text-primary transition-colors truncate max-w-[240px]"
      title="Click to rename"
    >
      <span className="truncate">{value}</span>
      <Pencil size={11} className="shrink-0 opacity-0 group-hover:opacity-60 transition-opacity" />
    </button>
  );
}

function DeleteButton({ projectId }: { projectId: string }) {
  const router = useRouter();
  const removeProject = useAppStore((s) => s.removeProject);
  const [confirming, setConfirming] = useState(false);

  const handleDelete = async () => {
    removeProject(projectId);
    router.push('/dashboard');
    await fetch(`/api/projects/${projectId}`, { method: 'DELETE' });
  };

  if (confirming) {
    return (
      <div className="flex items-center gap-1.5">
        <span className="text-xs text-muted-foreground">Delete?</span>
        <button
          type="button"
          onClick={() => { void handleDelete(); }}
          className="text-xs px-2 py-0.5 rounded bg-red-500/20 text-red-400 hover:bg-red-500/30 transition-colors"
        >
          Yes
        </button>
        <button
          type="button"
          onClick={() => setConfirming(false)}
          className="text-xs px-2 py-0.5 rounded bg-[#1a1a1a] text-muted-foreground hover:text-foreground transition-colors"
        >
          No
        </button>
      </div>
    );
  }

  return (
    <button
      type="button"
      onClick={() => setConfirming(true)}
      className="w-7 h-7 rounded-md flex items-center justify-center text-muted-foreground hover:text-red-400 hover:bg-red-500/10 transition-colors"
      title="Delete project"
    >
      <Trash2 size={13} />
    </button>
  );
}

const MIN_CHAT_WIDTH = 280;
const MAX_CHAT_WIDTH = 600;
const DEFAULT_CHAT_WIDTH = 380;

export default function ProjectPage({ params }: { params: Promise<{ id: string }> }) {
  const { id } = use(params);
  const project = useAppStore((s) => s.projects.find((p) => p.id === id));
  const agentStep = useAppStore((s) => s.agentStep);
  const setSelectedProjectId = useAppStore((s) => s.setSelectedProjectId);

  const [chatWidth, setChatWidth] = useState(DEFAULT_CHAT_WIDTH);
  const isDragging = useRef(false);
  const containerRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    setSelectedProjectId(id);
    return () => setSelectedProjectId(null);
  }, [id, setSelectedProjectId]);

  useEffect(() => {
    const onMouseMove = (e: MouseEvent) => {
      if (!isDragging.current || !containerRef.current) return;
      const rect = containerRef.current.getBoundingClientRect();
      const newWidth = Math.min(Math.max(e.clientX - rect.left, MIN_CHAT_WIDTH), MAX_CHAT_WIDTH);
      setChatWidth(newWidth);
    };
    const onMouseUp = () => {
      if (!isDragging.current) return;
      isDragging.current = false;
      document.body.style.cursor = '';
      document.body.style.userSelect = '';
    };
    document.addEventListener('mousemove', onMouseMove);
    document.addEventListener('mouseup', onMouseUp);
    return () => {
      document.removeEventListener('mousemove', onMouseMove);
      document.removeEventListener('mouseup', onMouseUp);
    };
  }, []);

  const handleResizeMouseDown = (e: React.MouseEvent) => {
    e.preventDefault();
    isDragging.current = true;
    document.body.style.cursor = 'col-resize';
    document.body.style.userSelect = 'none';
  };

  if (!project) return <div className="text-muted-foreground p-6">Project not found</div>;

  return (
    <div className="flex flex-col -m-6 overflow-hidden" style={{ height: 'calc(100vh - var(--header-height, 57px))' }}>
      <AgentProgressBar step={agentStep} />
      <div ref={containerRef} className="flex flex-1 overflow-hidden">
        {/* Chat — resizable */}
        <div
          className="border-r border-border flex flex-col overflow-hidden shrink-0"
          style={{ width: chatWidth }}
        >
          <div className="px-4 py-3 border-b border-border flex items-center justify-between gap-2">
            <ProjectTitle projectId={id} initialName={project.name} />
            <DeleteButton projectId={id} />
          </div>
          <ChatPanel projectId={id} />
        </div>

        {/* Resize handle */}
        <div
          onMouseDown={handleResizeMouseDown}
          className="w-1 shrink-0 bg-border hover:bg-primary/50 active:bg-primary/70 cursor-col-resize transition-colors"
          title="Drag to resize"
        />

        {/* Viewer — remaining space */}
        <div className="flex-1 overflow-hidden">
          <ViewerPanel projectId={id} />
        </div>
      </div>
    </div>
  );
}
