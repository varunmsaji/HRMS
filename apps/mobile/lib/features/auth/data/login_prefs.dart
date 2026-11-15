import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:flutter_secure_storage/flutter_secure_storage.dart';

/// What the login screen remembers between sign-ins on this device: the identifier (email or
/// employee ID) and the company code, so an employee does not retype their company code every time
/// the session ends (audit MOB-UX-030). Never the password.
///
/// Kept in the platform's secure storage like the session. Every failure is treated as "nothing
/// remembered": sign-in must work even when storage does not.
class LoginPrefs {
  const LoginPrefs([this._storage = const FlutterSecureStorage()]);

  final FlutterSecureStorage _storage;

  static const _identifierKey = 'login.identifier';
  static const _companyCodeKey = 'login.company_code';

  Future<({String? identifier, String? companyCode})> read() async {
    try {
      final values = await Future.wait([_storage.read(key: _identifierKey), _storage.read(key: _companyCodeKey)]);
      return (identifier: values[0], companyCode: values[1]);
    } catch (_) {
      return (identifier: null, companyCode: null);
    }
  }

  /// Saves after a successful sign-in. A sign-in by email clears the company code.
  Future<void> remember({required String identifier, String? companyCode}) async {
    try {
      await _storage.write(key: _identifierKey, value: identifier);
      if (companyCode == null || companyCode.isEmpty) {
        await _storage.delete(key: _companyCodeKey);
      } else {
        await _storage.write(key: _companyCodeKey, value: companyCode);
      }
    } catch (_) {}
  }

  /// "Not you?": forget both.
  Future<void> forget() async {
    try {
      await _storage.delete(key: _identifierKey);
      await _storage.delete(key: _companyCodeKey);
    } catch (_) {}
  }
}

final loginPrefsProvider = Provider<LoginPrefs>((ref) => const LoginPrefs());
