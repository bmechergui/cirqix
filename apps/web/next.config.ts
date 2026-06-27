import type { NextConfig } from 'next';
import path from 'path';

const nextConfig: NextConfig = {
  transpilePackages: ['@cirqix/db', '@cirqix/agents'],
  outputFileTracingRoot: path.join(__dirname, '../../'),
};

export default nextConfig;
