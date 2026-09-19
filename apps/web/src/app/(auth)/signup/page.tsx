import { SignupForm } from '@/features/auth/ui/SignupForm';

// La marque est ajoutée par le gabarit racine (`%s | Cirqix`) : ne pas la répéter.
export const metadata = { title: 'Create account' };

export default function SignupPage() {
  return <SignupForm />;
}
