import { Sidebar } from '@/features/dashboard/ui/Sidebar';
import { Header } from '@/features/dashboard/ui/Header';
import { DashboardInitializer } from '@/features/dashboard/ui/DashboardInitializer';

export default function DashboardLayout({ children }: { children: React.ReactNode }) {
  return (
    <div className="flex h-screen bg-background overflow-hidden" style={{ '--header-height': '57px' } as React.CSSProperties}>
      <DashboardInitializer />
      <div className="hidden md:block shrink-0">
        <Sidebar />
      </div>
      <div className="flex flex-col flex-1 overflow-hidden min-w-0">
        <Header />
        <main className="flex-1 overflow-y-auto p-4 md:p-6">{children}</main>
      </div>
    </div>
  );
}
