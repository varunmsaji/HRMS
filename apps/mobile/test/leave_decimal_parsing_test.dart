import 'package:flutter_test/flutter_test.dart';
import 'package:hrms_mobile/features/leave/data/leave_repository.dart';

// The API serialises Decimal fields as strings ("12.50"); these used to be read `as num` and
// threw on the live backend.
void main() {
  test('leave balance accepts string decimals', () {
    final b = LeaveBalance.fromJson({
      'employee_id': 'e',
      'leave_type_id': 't',
      'leave_type_code': 'CL',
      'leave_type_name': 'Casual',
      'balance': '12.50',
      'reserved_balance': '1.00',
    });
    expect(b.balance, 12.5);
    expect(b.reservedBalance, 1);
    expect(b.leaveTypeId, 't');
  });

  test('ledger entry accepts string and signed decimals', () {
    final e = LeaveLedgerEntry.fromJson({
      'id': 'l',
      'leave_type_id': 't',
      'entry_type': 'ENCASHMENT',
      'amount': '-2.00',
      'effective_date': '2026-10-01',
      'reason': null,
      'created_at': '2026-10-01T00:00:00Z',
    });
    expect(e.amount, -2);
  });

  test('statutory minimum and application day counts accept strings and numbers', () {
    final m = StatutoryLeaveMinimum.fromJson({'id': 'i', 'state_code': null, 'establishment_type': null, 'leave_category': 'CASUAL', 'min_days_per_year': '7.00', 'note': null});
    expect(m.minDaysPerYear, 7);
    final withNumber = StatutoryLeaveMinimum.fromJson({'id': 'i', 'leave_category': 'CASUAL', 'min_days_per_year': 7});
    expect(withNumber.minDaysPerYear, 7);
  });
}
