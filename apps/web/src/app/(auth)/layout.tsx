import Link from 'next/link';
import { CirqixLogo } from '@/shared/ui/cirqix-logo';

export default function AuthLayout({ children }: { children: React.ReactNode }) {
  return (
    <div className="min-h-screen bg-[#080808] flex flex-col items-center justify-center px-4">
      <Link href="/" className="mb-8">
        <CirqixLogo height={28} />
      </Link>
      <div className="w-full max-w-sm">{children}</div>
    </div>
  );
}
