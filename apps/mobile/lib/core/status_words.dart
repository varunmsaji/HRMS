/// The one set of words for the status of a request that goes through approval: a leave
/// application, an attendance correction, an overtime record (audit MOB-UX-042). Every list, detail
/// screen, Home row and decision card reads its status word from here, so the same request never
/// says "Submitted" on one screen and "Pending approval" on the next.
///
/// The API's codes differ by resource (`SUBMITTED` for leave and corrections, `PENDING` for
/// overtime); a person only needs to know it is waiting on someone.
const requestStatusWords = <String, String>{
  'DRAFT': 'Draft',
  'SUBMITTED': 'Awaiting approval',
  'PENDING': 'Awaiting approval',
  'PENDING_APPROVAL': 'Awaiting approval',
  'APPROVED': 'Approved',
  'AUTO_APPROVED': 'Auto-approved',
  'REJECTED': 'Rejected',
  'CANCELLED': 'Cancelled',
  'CANCELED': 'Cancelled',
  'WITHDRAWN': 'Withdrawn',
};

/// The word for a request status code; an unknown code is shown in plain words ("ON_HOLD" ->
/// "On hold") rather than hidden.
String requestStatusLabel(String code) {
  final known = requestStatusWords[code.toUpperCase()];
  if (known != null) return known;
  final words = code.replaceAll('_', ' ').toLowerCase().trim();
  return words.isEmpty ? code : words[0].toUpperCase() + words.substring(1);
}
