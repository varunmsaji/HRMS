/** Mirrors `apps/api/src/hrms/core/auth/passwords.py::is_password_strong_enough` so the client
 * can reject an obviously-too-weak password before a round trip, without redefining the policy
 * — the backend remains the source of truth and re-validates regardless. */
export const PASSWORD_MIN_LENGTH = 8;

export function isPasswordStrongEnough(password: string): boolean {
  if (password.length < PASSWORD_MIN_LENGTH) return false;
  const hasLetter = /[a-zA-Z]/.test(password);
  const hasDigit = /[0-9]/.test(password);
  return hasLetter && hasDigit;
}

export function passwordRequirementMessage(): string {
  return `Must be at least ${PASSWORD_MIN_LENGTH} characters and include a letter and a digit.`;
}

const EMAIL_PATTERN = /^[^\s@]+@[^\s@]+\.[^\s@]+$/;

export function isValidEmail(email: string): boolean {
  return EMAIL_PATTERN.test(email);
}
