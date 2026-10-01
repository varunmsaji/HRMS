/// Mirrors `apps/web/src/lib/validation.ts`, which in turn mirrors
/// `apps/api/src/hrms/core/auth/passwords.py::is_password_strong_enough`. The
/// backend remains the source of truth and re-validates regardless — this is
/// only a fast first pass that avoids an obviously-doomed round trip.
library;

const passwordMinLength = 8;

bool isPasswordStrongEnough(String password) {
  if (password.length < passwordMinLength) return false;
  final hasLetter = RegExp(r'[a-zA-Z]').hasMatch(password);
  final hasDigit = RegExp(r'[0-9]').hasMatch(password);
  return hasLetter && hasDigit;
}

String passwordRequirementMessage() =>
    'Must be at least $passwordMinLength characters and include a letter and a digit.';

final _emailPattern = RegExp(r'^[^\s@]+@[^\s@]+\.[^\s@]+$');

bool isValidEmail(String email) => _emailPattern.hasMatch(email);
