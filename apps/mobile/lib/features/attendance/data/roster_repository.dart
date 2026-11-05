import 'package:flutter_riverpod/flutter_riverpod.dart';

import '../../../core/api/api_client.dart';
import '../../../core/providers.dart';
import '../../profile/data/employee_repository.dart';
import '../domain/roster_views.dart';

/// `GET /rosters` returns at most 500 rows a page; this many pages is the safety bound on one view.
const _rosterPerPage = 500;
const _maxRosterPages = 10;
const _employeesPerPage = 100;
const _maxEmployeePages = 10;

class RosterRepository {
  RosterRepository(this._client);
  final ApiClient _client;

  /// Every entry in the range up to the bound. [total] says if the range held more than came back.
  Future<({List<RosterEntry> entries, int total})> listEntries(String from, String to) async {
    final entries = <RosterEntry>[];
    var total = 0;
    for (var page = 1; page <= _maxRosterPages; page++) {
      final env = await _client.getList('/rosters', query: PageQuery(page: page, perPage: _rosterPerPage), filters: {'date_from': from, 'date_to': to}, parseItem: (d) => RosterEntry.fromJson(d as Map<String, dynamic>));
      entries.addAll(env.data);
      total = env.pagination?.total ?? entries.length;
      if (!(env.pagination?.hasNext ?? false)) break;
    }
    return (entries: entries, total: total);
  }

  Future<List<RosterShift>> listShifts() async {
    final env = await _client.getList('/shifts', query: PageQuery(perPage: 100), parseItem: (d) => RosterShift.fromJson(d as Map<String, dynamic>));
    return env.data;
  }

  /// Employees up to the bound; [more] says some were left out.
  Future<({List<Employee> rows, bool more})> listBoardEmployees() async {
    final rows = <Employee>[];
    for (var page = 1; page <= _maxEmployeePages; page++) {
      final env = await _client.getList('/employees', query: PageQuery(page: page, perPage: _employeesPerPage), parseItem: (d) => Employee.fromJson(d as Map<String, dynamic>));
      rows.addAll(env.data);
      if (!(env.pagination?.hasNext ?? false)) return (rows: rows, more: false);
    }
    return (rows: rows, more: true);
  }

  Future<RosterEntry> _publishIfDraft(RosterEntry entry) async {
    if (!entry.isDraft) return entry;
    return _client.post('/rosters/${entry.id}/publish', body: const {}, ifMatch: entry.version.toString(), parse: (d) => RosterEntry.fromJson(d as Map<String, dynamic>));
  }

  /// Puts an employee in [target] for [date]: a column from [boardColumnOf]. The change is published,
  /// so it takes effect immediately. Resolves to the employee's entry now, or null if none remains.
  Future<RosterEntry?> moveEmployee({required String employeeId, required String date, required RosterEntry? existing, required String target}) async {
    if (target == unassignedColumn) {
      if (existing != null) await _client.delete<Object?>('/rosters/${existing.id}', ifMatch: existing.version.toString(), parse: (_) => null);
      return null;
    }
    final weekOff = target == weekOffColumn;
    final fields = {'shift_id': weekOff ? null : target, 'is_week_off_override': weekOff};
    final saved = existing != null
        ? await _client.patch('/rosters/${existing.id}', body: fields, ifMatch: existing.version.toString(), parse: (d) => RosterEntry.fromJson(d as Map<String, dynamic>))
        : await _client.post('/rosters', body: {'employee_id': employeeId, 'roster_date': date, ...fields}, parse: (d) => RosterEntry.fromJson(d as Map<String, dynamic>));
    return _publishIfDraft(saved);
  }

  /// Copies [entries] to [date], published, skipping anyone already rostered that day. Resolves to
  /// how many were copied.
  Future<int> copyEntries(List<RosterEntry> entries, String date) async {
    final taken = (await listEntries(date, date)).entries.map((r) => r.employeeId).toSet();
    var copied = 0;
    for (final r in entries) {
      if (taken.contains(r.employeeId)) continue;
      final created = await _client.post(
        '/rosters',
        body: {'employee_id': r.employeeId, 'roster_date': date, 'shift_id': r.shiftId, 'is_week_off_override': r.isWeekOff, 'is_holiday_working_override': r.isHolidayWorking},
        parse: (d) => RosterEntry.fromJson(d as Map<String, dynamic>),
      );
      await _publishIfDraft(created);
      copied++;
    }
    return copied;
  }
}

final rosterRepositoryProvider = Provider<RosterRepository>((ref) => RosterRepository(ref.watch(apiClientProvider)));
