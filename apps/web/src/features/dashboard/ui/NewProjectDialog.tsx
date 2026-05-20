'use client';

import { useRouter } from 'next/navigation';
import { useState } from 'react';
import { Plus, Loader2 } from 'lucide-react';
import { Button } from '@/shared/ui/button';
import { Textarea } from '@/shared/ui/textarea';
import {
  Dialog,
  DialogTrigger,
  DialogContent,
  DialogHeader,
  DialogTitle,
  DialogDescription,
  DialogFooter,
  DialogClose,
} from '@/shared/ui/dialog';
import { useAppStore } from '@/shared/store/app-store';

const EXAMPLES = [
  'ESP32-S3 weather station with BME280 and OLED',
  '555 LED blinker, 5V powered',
  'LM7805 linear power supply with input/output caps',
];

function deriveNameFromDescription(desc: string): string {
  const words = desc.trim().split(/\s+/);
  const slug = words.slice(0, 6).join(' ');
  return slug.length > 60 ? slug.slice(0, 57) + '…' : slug;
}

export function NewProjectDialog() {
  const router = useRouter();
  const createProject = useAppStore((s) => s.createProject);
  const [open, setOpen] = useState(false);
  const [description, setDescription] = useState('');
  const [submitting, setSubmitting] = useState(false);
  const [error, setError] = useState<string | null>(null);

  function reset() {
    setDescription('');
    setError(null);
    setSubmitting(false);
  }

  async function onSubmit(e: React.FormEvent) {
    e.preventDefault();
    if (!description.trim()) {
      setError('Please describe what you want to build.');
      return;
    }
    setSubmitting(true);
    setError(null);
    const project = await createProject({
      name: deriveNameFromDescription(description),
      description: description.trim(),
    });
    if (!project) {
      setError('Could not create project. Try again.');
      setSubmitting(false);
      return;
    }
    setOpen(false);
    reset();
    router.push(`/dashboard/projects/${project.id}`);
  }

  return (
    <Dialog
      open={open}
      onOpenChange={(v) => {
        setOpen(v);
        if (!v) reset();
      }}
    >
      <DialogTrigger asChild>
        <Button size="sm" className="gap-1.5">
          <Plus size={14} />
          New project
        </Button>
      </DialogTrigger>
      <DialogContent>
        <DialogHeader>
          <DialogTitle>Start a new PCB</DialogTitle>
          <DialogDescription>
            Describe what you want and Layrix designs it.
          </DialogDescription>
        </DialogHeader>

        <form onSubmit={onSubmit} className="flex flex-col gap-4">
          <Textarea
            id="project-description"
            placeholder="Describe the circuit: components, power requirements, interfaces…"
            value={description}
            onChange={(e) => setDescription(e.target.value)}
            maxLength={500}
            rows={4}
            autoFocus
            disabled={submitting}
          />

          <div className="flex flex-wrap gap-1.5">
            {EXAMPLES.map((ex) => (
              <button
                key={ex}
                type="button"
                onClick={() => setDescription(ex)}
                disabled={submitting}
                className="text-[11px] px-2 py-1 rounded-md border border-border bg-[#0a0a0a] text-muted-foreground hover:border-primary/40 hover:text-primary transition-colors"
              >
                {ex}
              </button>
            ))}
          </div>

          {error && (
            <p className="text-xs text-destructive bg-destructive/10 border border-destructive/20 rounded-md px-3 py-2">
              {error}
            </p>
          )}

          <DialogFooter className="gap-2">
            <DialogClose asChild>
              <Button type="button" variant="ghost" disabled={submitting}>
                Cancel
              </Button>
            </DialogClose>
            <Button type="submit" disabled={submitting || !description.trim()} className="gap-1.5">
              {submitting && <Loader2 size={14} className="animate-spin" />}
              {submitting ? 'Creating…' : 'Create project'}
            </Button>
          </DialogFooter>
        </form>
      </DialogContent>
    </Dialog>
  );
}
