import Image from 'next/image';

interface CirqixLogoProps {
  /** 'full' = logo complet | 'icon' = icône seule */
  variant?: 'full' | 'icon';
  height?: number;
  className?: string;
}

export function CirqixLogo({ variant = 'full', height = 32, className = '' }: CirqixLogoProps) {
  if (variant === 'icon') {
    return (
      <Image
        src="/icone.svg"
        alt="Cirqix"
        width={height}
        height={height}
        className={`object-contain ${className}`}
        priority
      />
    );
  }

  return (
    <Image
      src="/logo.svg"
      alt="Cirqix"
      width={Math.round(height * 3.5)}
      height={height}
      className={`object-contain ${className}`}
      priority
    />
  );
}
