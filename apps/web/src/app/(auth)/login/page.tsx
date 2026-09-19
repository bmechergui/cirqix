import { LoginForm } from '@/features/auth/ui/LoginForm';

// La marque est ajoutée par le gabarit racine (`%s | Cirqix`) : ne pas la répéter.
export const metadata = { title: 'Sign in' };

export default function LoginPage() {
  return <LoginForm />;
}
