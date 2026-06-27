'use client';

import { useRouter } from 'next/navigation';
import { useState } from 'react';
import { Plus, Loader2 } from 'lucide-react';
import { Button } from '@/shared/ui/button';
import { Input } from '@/shared/ui/input';
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

export function NewProjectDialog() {
  const router = useRouter();
  const createProject = useAppStore((s) => s.createProject);
  const [open, setOpen] = useState(false);
  const [name, setName] = useState('');
  const [submitting, setSubmitting] = useState(false);
  const [error, setError] = useState<string | null>(null);

  function reset() {
    setName('');
    setError(null);
    setSubmitting(false);
  }

  async function onSubmit(e: React.FormEvent) {
    e.preventDefault();
    if (!name.trim()) {
      setError('Project name is required.');
      return;
    }
    setSubmitting(true);
    setError(null);
    const project = await createProject({
      name: name.trim(),
      description: name.trim(),
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
            Describe what you want and Cirqix designs it.
          </DialogDescription>
        </DialogHeader>

        <form onSubmit={onSubmit} className="flex flex-col gap-4">
          <Input
            id="project-name"
            placeholder="e.g. ESP32 Weather Station"
            value={name}
            onChange={(e) => setName(e.target.value)}
            maxLength={100}
            autoFocus
            disabled={submitting}
          />

          <div className="flex flex-wrap gap-1.5">
            {EXAMPLES.map((ex) => (
              <button
                key={ex}
                type="button"
                onClick={() => setName(ex)}
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
            <Button type="submit" disabled={submitting || !name.trim()} className="gap-1.5">
              {submitting && <Loader2 size={14} className="animate-spin" />}
              {submitting ? 'Creating…' : 'Create project'}
            </Button>
          </DialogFooter>
        </form>
      </DialogContent>
    </Dialog>
  );
}
