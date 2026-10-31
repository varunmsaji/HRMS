import 'package:flutter_riverpod/flutter_riverpod.dart';

import '../../../core/time.dart';
import '../data/attendance_repository.dart';
import '../domain/today_state.dart';

/// Whose today, and in which zone. Providers keyed by this are per employee, so one user's
/// attendance can never be shown to the next user of the same device.
typedef TodayKey = ({String employeeId, String zone});

/// The two existing reads behind "today" (API matrix §5.2/§5.3), each failing on its own:
/// a null list means that read failed (not that it was empty).
class TodayData {
  const TodayData({required this.punches, required this.days, required this.today});

  /// Recent punches, newest first (the D-06 window); null if the read failed.
  final List<Punch>? punches;

  /// Day rows from a few days back through today; null if the read failed.
  final List<AttendanceDay>? days;

  /// The company-zone business date these were read for.
  final String today;

  AttendanceDay? get todayRow {
    for (final d in days ?? const <AttendanceDay>[]) {
      if (d.attendanceDate == today) return d;
    }
    return null;
  }

  /// Up to [count] previous days that have a row, newest first.
  List<AttendanceDay> recentDays([int count = 3]) {
    final rows = [for (final d in days ?? const <AttendanceDay>[]) if (d.attendanceDate.compareTo(today) < 0) d]
      ..sort((a, b) => b.attendanceDate.compareTo(a.attendanceDate));
    return rows.take(count).toList();
  }
}

Future<T?> _orNull<T>(Future<T> read) async {
  try {
    return await read;
  } catch (_) {
    return null;
  }
}

/// Reads punches and day rows in parallel. Neither blocks the other. No attendance logic here:
/// [resolveTodayState] decides what the two answers mean.
final todayDataProvider = FutureProvider.autoDispose.family<TodayData, TodayKey>((ref, key) async {
  final repo = ref.watch(attendanceRepositoryProvider);
  final today = businessToday(key.zone);
  final window = todayPunchWindow(key.zone);
  final results = await Future.wait<Object?>([
    _orNull(repo.listPunches(employeeId: key.employeeId, dateFrom: window.from, dateTo: window.to)),
    _orNull(repo.listAttendanceDays(employeeId: key.employeeId, dateFrom: businessDayOffset(key.zone, -4), dateTo: today)),
  ]);
  final punches = results[0] as List<Punch>?;
  final days = results[1] as List<AttendanceDay>?;
  return TodayData(punches: punches, days: days, today: today);
});

/// The resolver applied to the provider's answer. [data] is null while loading.
TodayState todayStateOf(AsyncValue<TodayData> data, TodayKey key) {
  final value = data.valueOrNull;
  return resolveTodayState(
    hasEmployee: true,
    loading: value == null && !data.hasError,
    punches: value?.punches,
    day: value?.todayRow,
    dayFailed: data.hasError || value?.days == null,
    zone: key.zone,
    today: value?.today ?? businessToday(key.zone),
  );
}
