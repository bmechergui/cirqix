/** Authentication helpers shared by every KiCad microservice client. */

export class KicadServiceAuthConfigError extends Error {
  constructor(message = 'KICAD_SERVICE_TOKEN not configured') {
    super(message);
    this.name = 'KicadServiceAuthConfigError';
  }
}

const MIN_SERVICE_TOKEN_LENGTH = 32;

export function buildKicadServiceHeaders(): Record<string, string> {
  const token = process.env['KICAD_SERVICE_TOKEN']?.trim();
  if (!token || token.length < MIN_SERVICE_TOKEN_LENGTH) {
    throw new KicadServiceAuthConfigError(
      `KICAD_SERVICE_TOKEN not configured or shorter than ${MIN_SERVICE_TOKEN_LENGTH} characters`,
    );
  }

  return {
    'Content-Type': 'application/json',
    Authorization: `Bearer ${token}`,
  };
}
