import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';

import '../../../core/api/api_error.dart';
import '../../../core/format.dart';
import '../../../core/theme/app_theme.dart';
import '../../../core/time.dart';
import '../../../core/widgets/ui.dart';
import '../../auth/state/auth_controller.dart';
import '../../leave/data/leave_repository.dart';
import '../data/employee_repository.dart';
import 'profile_screen.dart' show employeeRepositoryProvider;

const _workLocationLabels = {'OFFICE': 'Office', 'WFH': 'Work from home', 'HYBRID': 'Hybrid', 'FIELD': 'Field'};
const _payBasisLabels = {'MONTHLY': 'Monthly salaried', 'DAILY_WAGE': 'Daily wage'};

/// Whole years from [dateOfBirth] (`yyyy-mm-dd`) to [today]; null when unparseable or in the future.
int? ageOn(String dateOfBirth, DateTime today) {
  final d = DateTime.tryParse(dateOfBirth);
  if (d == null) return null;
  var age = today.year - d.year;
  if (today.month < d.month || (today.month == d.month && today.day < d.day)) age -= 1;
  return age >= 0 ? age : null;
}

/// The Overview of an employee record — shared by My Profile and the manager view. Mirrors
/// `apps/web/src/components/employee/employee-overview.tsx`.
class EmployeeOverview extends ConsumerStatefulWidget {
  const EmployeeOverview({super.key, required this.employee, this.actions = const [], this.now});

  final Employee employee;

  /// Buttons shown under the name (edit, deactivate, …).
  final List<Widget> actions;

  /// The current instant, for the age and the next-leave cut-off (tests pin it).
  final DateTime? now;

  @override
  ConsumerState<EmployeeOverview> createState() => _EmployeeOverviewState();
}

class _EmployeeOverviewState extends ConsumerState<EmployeeOverview> {
  EmployeeWorkSummary? _work;
  ApiError? _workError;
  bool _workLoading = true;
  List<LeaveBalance>? _balances;
  LeaveApplication? _nextLeave;
  List<EmployeeDocumentRow>? _documents;

  Employee get employee => widget.employee;
  List<Widget> get actions => widget.actions;
  DateTime get _now => widget.now ?? DateTime.now();

  @override
  void initState() {
    super.initState();
    _loadAll();
  }

  @override
  void didUpdateWidget(EmployeeOverview old) {
    super.didUpdateWidget(old);
    if (old.employee.id != widget.employee.id) _loadAll();
  }

  /// Each piece loads on its own and is left out when the viewer cannot read it, never shown
  /// empty (web `EmployeeSideCards`); the work card shows its error instead.
  void _loadAll() {
    final id = employee.id;
    final repo = ref.read(employeeRepositoryProvider);
    final leave = ref.read(leaveRepositoryProvider);
    final zone = ref.read(authControllerProvider).user?.companyTimezone ?? 'Asia/Kolkata';
    final today = businessToday(zone, now: _now);
    setState(() => _workLoading = true);
    repo.workSummary(id).then((w) {
      if (mounted && id == employee.id) setState(() { _work = w; _workError = null; _workLoading = false; });
    }).catchError((Object e) {
      if (mounted && id == employee.id) setState(() { _work = null; _workError = (e is ApiError ? e : null) ?? ApiError(status: 0, code: 'UNKNOWN_ERROR', message: 'Something went wrong.'); _workLoading = false; });
    });
    leave.listLeaveBalances(id).then((b) {
      if (mounted && id == employee.id) setState(() => _balances = b);
    }).catchError((Object _) {});
    leave.listLeaveApplicationsPage(employeeId: id, dateFrom: today, status: 'APPROVED').then((env) {
      final upcoming = env.data.where((a) => a.endDate.compareTo(today) >= 0).toList()..sort((a, b) => a.startDate.compareTo(b.startDate));
      if (mounted && id == employee.id) setState(() => _nextLeave = upcoming.firstOrNull);
    }).catchError((Object _) {});
    repo.listDocuments(id).then((d) {
      if (mounted && id == employee.id) setState(() => _documents = d);
    }).catchError((Object _) {});
  }

  @override
  Widget build(BuildContext context) {
    final theme = Theme.of(context);
    final name = employee.fullName.isEmpty ? employee.employeeCode : employee.fullName;
    final work = _work;
    final role = [work?.designation, work?.department].where((p) => p != null && p.isNotEmpty).join(' · ');
    final legalName = [employee.firstName, employee.middleName, employee.lastName].where((p) => p != null && p.trim().isNotEmpty).join(' ');
    final displayName = employee.displayName?.trim() ?? '';
    final age = employee.dateOfBirth == null ? null : ageOn(employee.dateOfBirth!, _now);
    final photoUrl = employee.raw['photo_url'] as String?;
    return ListView(
      padding: const EdgeInsets.fromLTRB(16, 4, 16, 32),
      children: [
        Container(
          padding: const EdgeInsets.all(18),
          decoration: BoxDecoration(
            borderRadius: BorderRadius.circular(AppRadii.card + 4),
            gradient: const LinearGradient(
              begin: Alignment.topLeft,
              end: Alignment.bottomRight,
              colors: [AppBrand.navy, AppBrand.navyDeep],
            ),
          ),
          child: Column(
            crossAxisAlignment: CrossAxisAlignment.start,
            children: [
              Row(
                children: [
                  Container(
                    padding: const EdgeInsets.all(2.5),
                    decoration: BoxDecoration(shape: BoxShape.circle, border: Border.all(color: Colors.white.withValues(alpha: 0.35), width: 1.5)),
                    child: (photoUrl != null && photoUrl.isNotEmpty)
                        ? ClipOval(child: Image.network(photoUrl, width: 56, height: 56, fit: BoxFit.cover, errorBuilder: (_, __, ___) => InitialsAvatar(name: name, size: 56)))
                        : InitialsAvatar(name: name, size: 56),
                  ),
                  const SizedBox(width: 14),
                  Expanded(
                    child: Column(
                      crossAxisAlignment: CrossAxisAlignment.start,
                      children: [
                        Text(
                          name,
                          maxLines: 2,
                          overflow: TextOverflow.ellipsis,
                          style: theme.textTheme.headlineMedium?.copyWith(color: Colors.white, fontWeight: FontWeight.w700),
                        ),
                        const SizedBox(height: 2),
                        Text(
                          role.isEmpty ? employee.employeeCode : '${employee.employeeCode} · $role',
                          maxLines: 2,
                          overflow: TextOverflow.ellipsis,
                          style: TextStyle(color: Colors.white.withValues(alpha: 0.7), fontSize: 13),
                        ),
                      ],
                    ),
                  ),
                ],
              ),
              const SizedBox(height: 14),
              Wrap(
                spacing: 8,
                runSpacing: 8,
                children: [
                  _HeroPill(label: humanize(employee.status)),
                  if (!employee.isActive) const _HeroPill(label: 'Inactive'),
                  if (work?.manager != null) _HeroPill(label: 'Reports to ${work!.manager!.name}'),
                  if (work?.branch != null) _HeroPill(label: work!.branch!),
                  if (work?.joiningDate != null) _HeroPill(label: 'Joined ${formatFullDate(work!.joiningDate!)}'),
                ],
              ),
            ],
          ),
        ),
        if (actions.isNotEmpty) ...[
          const SizedBox(height: 14),
          Wrap(spacing: 8, runSpacing: 8, children: actions),
        ],
        const SizedBox(height: 16),
        _OverviewSection(
          title: 'Identity',
          icon: Icons.badge_outlined,
          fields: [
            _OverviewField('Legal name', legalName),
            if (displayName.isNotEmpty && displayName != legalName) _OverviewField('Display name', displayName),
            _OverviewField('Employee code', employee.employeeCode),
            _OverviewField('Date of birth', employee.dateOfBirth == null ? null : '${employee.dateOfBirth}${age != null ? ' ($age yrs)' : ''}'),
            _OverviewField('Gender', employee.gender),
            _OverviewField('Marital status', employee.maritalStatus),
            _OverviewField('Blood group', employee.bloodGroup),
            _OverviewField('Nationality', employee.nationality),
          ],
        ),
        const SizedBox(height: 14),
        _OverviewSection(
          title: 'Personal contact',
          icon: Icons.alternate_email_rounded,
          fields: [
            _OverviewField('Personal email', employee.personalEmail),
            _OverviewField('Personal mobile', employee.personalMobile),
          ],
        ),
        const SizedBox(height: 14),
        _currentWork(context),
        const SizedBox(height: 14),
        _OverviewSection(
          title: 'Present address',
          icon: Icons.home_outlined,
          fields: [
            _OverviewField('Address', employee.presentAddressLine1),
            _OverviewField('Address line 2', employee.presentAddressLine2),
            _OverviewField('City', employee.presentCity),
            _OverviewField('State', employee.presentStateCode),
            _OverviewField('Pincode', employee.presentPincode),
            _OverviewField('Country', employee.presentCountryCode),
          ],
        ),
        const SizedBox(height: 14),
        _OverviewSection(
          title: 'Emergency contact',
          icon: Icons.emergency_outlined,
          fields: [
            _OverviewField('Name', employee.emergencyContactName),
            _OverviewField('Relationship', employee.emergencyContactRelationship),
            _OverviewField('Phone', employee.emergencyContactPhone),
          ],
        ),
        if (_balances != null) ...[const SizedBox(height: 14), _leaveBalancesCard(context)],
        if (_documents != null) ...[const SizedBox(height: 14), _documentsCard(context)],
      ],
    );
  }

  /// Web's "Current work" card: where they sit and how they are employed.
  Widget _currentWork(BuildContext context) {
    final scheme = Theme.of(context).colorScheme;
    final work = _work;
    if (_workLoading) {
      return const AppCard(key: Key('overview-work-loading'), child: Center(child: Padding(padding: EdgeInsets.all(12), child: CircularProgressIndicator(strokeWidth: 2))));
    }
    final error = _workError;
    if (error != null || work == null) {
      return AppCard(
        key: const Key('overview-work-error'),
        child: Text(
          error?.status == 403 ? "You do not have permission to view this employee's work information." : (error?.message ?? 'Could not load work information.'),
          style: TextStyle(color: scheme.error),
        ),
      );
    }
    final section = _OverviewSection(
      key: const Key('overview-work'),
      title: 'Current work',
      icon: Icons.work_outline_rounded,
      fields: [
        _OverviewField('Company', work.company),
        _OverviewField('Designation', work.designation),
        _OverviewField('Department', work.department),
        _OverviewField('Branch', work.branch),
        _OverviewField('Reporting manager', work.manager?.name),
        _OverviewField('Shift', work.shift),
        _OverviewField('Work location', work.workLocationType == null ? null : (_workLocationLabels[work.workLocationType] ?? work.workLocationType)),
        _OverviewField('Joining date', work.joiningDate == null ? null : formatFullDate(work.joiningDate!)),
        _OverviewField('Probation ends', work.probationEndDate == null ? null : formatFullDate(work.probationEndDate!)),
        _OverviewField('Pay basis', work.payBasis == null ? null : (_payBasisLabels[work.payBasis] ?? work.payBasis)),
      ],
    );
    if (work.employment != null) return section;
    return Column(children: [
      section,
      const SizedBox(height: 8),
      Text(
        'This employee has no employment record yet. Add one from the Employment section.',
        key: const Key('overview-no-employment'),
        style: TextStyle(fontSize: 12, color: scheme.onSurfaceVariant),
      ),
    ]);
  }

  Widget _sideCard(BuildContext context, {required String title, required IconData icon, required List<Widget> children}) {
    return AppCard(
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          Row(children: [
            IconBadge(icon: icon, size: 32),
            const SizedBox(width: 10),
            Expanded(child: Text(title, style: Theme.of(context).textTheme.headlineSmall?.copyWith(fontWeight: FontWeight.w700))),
          ]),
          const SizedBox(height: 14),
          ...children,
        ],
      ),
    );
  }

  Widget _leaveBalancesCard(BuildContext context) {
    final scheme = Theme.of(context).colorScheme;
    final balances = _balances!;
    final next = _nextLeave;
    return KeyedSubtree(
      key: const Key('overview-leave-balances'),
      child: _sideCard(context, title: 'Leave balances', icon: Icons.event_available_outlined, children: [
        if (balances.isEmpty)
          Text('No balance-tracked leave types.', style: TextStyle(color: scheme.onSurfaceVariant))
        else
          for (final b in balances)
            Padding(
              padding: const EdgeInsets.only(bottom: 10),
              child: Row(children: [
                Expanded(child: Text('${b.leaveTypeName} (${b.leaveTypeCode})', style: TextStyle(color: scheme.onSurfaceVariant))),
                Text(formatDayCount(b.balance), style: const TextStyle(fontWeight: FontWeight.w700)),
                if (b.reservedBalance > 0) Text(' (${formatLeaveDays(b.reservedBalance)} pending)', style: TextStyle(color: scheme.tertiary, fontSize: 12)),
              ]),
            ),
        if (next != null)
          Container(
            key: const Key('overview-next-leave'),
            width: double.infinity,
            margin: const EdgeInsets.only(top: 4),
            padding: const EdgeInsets.all(12),
            decoration: BoxDecoration(color: scheme.primaryContainer.withValues(alpha: 0.4), borderRadius: BorderRadius.circular(12)),
            child: Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
              const Text('Next approved leave', style: TextStyle(fontWeight: FontWeight.w700)),
              const SizedBox(height: 2),
              Text('${next.endDate == next.startDate ? formatFullDate(next.startDate) : '${formatFullDate(next.startDate)} – ${formatFullDate(next.endDate)}'}'
                  '${next.totalDays == null ? '' : ' (${formatDayCount(next.totalDays!)})'}'),
            ]),
          ),
      ]),
    );
  }

  Widget _documentsCard(BuildContext context) {
    final scheme = Theme.of(context).colorScheme;
    final docs = _documents!;
    final verified = docs.where((d) => d.status == 'VERIFIED').length;
    return KeyedSubtree(
      key: const Key('overview-documents'),
      child: _sideCard(context, title: 'Documents ($verified of ${docs.length} verified)', icon: Icons.folder_open_outlined, children: [
        if (docs.isEmpty) Text('No documents uploaded.', style: TextStyle(color: scheme.onSurfaceVariant)),
        for (final d in docs.take(5))
          Padding(
            padding: const EdgeInsets.only(bottom: 10),
            child: Row(children: [
              Icon(Icons.description_outlined, size: 18, color: scheme.onSurfaceVariant),
              const SizedBox(width: 10),
              Expanded(
                child: Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
                  Text(d.originalFilename, maxLines: 1, overflow: TextOverflow.ellipsis, style: const TextStyle(fontWeight: FontWeight.w600)),
                  Text(d.documentType.replaceAll('_', ' ').toLowerCase(), style: TextStyle(fontSize: 12, color: scheme.onSurfaceVariant)),
                ]),
              ),
              Icon(
                d.status == 'VERIFIED' ? Icons.check_circle_rounded : d.status == 'REJECTED' ? Icons.cancel_rounded : Icons.hourglass_bottom_rounded,
                size: 18,
                semanticLabel: d.status == 'VERIFIED' ? 'Verified' : d.status == 'REJECTED' ? 'Rejected' : 'Pending verification',
                color: d.status == 'VERIFIED' ? scheme.primary : d.status == 'REJECTED' ? scheme.error : scheme.tertiary,
              ),
            ]),
          ),
        if (docs.length > 5) Text('Showing 5 of ${docs.length}. See the Documents tab.', style: TextStyle(fontSize: 12, color: scheme.onSurfaceVariant)),
      ]),
    );
  }
}

class _HeroPill extends StatelessWidget {
  const _HeroPill({required this.label});
  final String label;

  @override
  Widget build(BuildContext context) => Container(
        padding: const EdgeInsets.symmetric(horizontal: 10, vertical: 4),
        decoration: BoxDecoration(
          color: Colors.white.withValues(alpha: 0.12),
          borderRadius: BorderRadius.circular(AppRadii.full),
          border: Border.all(color: Colors.white.withValues(alpha: 0.18)),
        ),
        child: Text(label, style: TextStyle(fontSize: 12, fontWeight: FontWeight.w600, color: Colors.white.withValues(alpha: 0.92))),
      );
}

class _OverviewField {
  const _OverviewField(this.label, this.value);
  final String label;
  final String? value;
}

class _OverviewSection extends StatelessWidget {
  const _OverviewSection({super.key, required this.title, required this.icon, required this.fields});

  final String title;
  final IconData icon;
  final List<_OverviewField> fields;

  @override
  Widget build(BuildContext context) {
    final scheme = Theme.of(context).colorScheme;
    final width = (MediaQuery.of(context).size.width - 32 - 32 - 12) / 2;
    return AppCard(
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          Row(
            children: [
              IconBadge(icon: icon, size: 32),
              const SizedBox(width: 10),
              Text(title, style: Theme.of(context).textTheme.headlineSmall?.copyWith(fontWeight: FontWeight.w700)),
            ],
          ),
          const SizedBox(height: 16),
          Wrap(
            spacing: 12,
            runSpacing: 16,
            children: [
              for (final field in fields)
                SizedBox(
                  width: width,
                  child: Column(
                    crossAxisAlignment: CrossAxisAlignment.start,
                    children: [
                      Text(
                        field.label.toUpperCase(),
                        style: TextStyle(fontSize: 11, fontWeight: FontWeight.w700, color: scheme.onSurfaceVariant, letterSpacing: 0.6),
                      ),
                      const SizedBox(height: 3),
                      Text(
                        (field.value != null && field.value!.trim().isNotEmpty) ? field.value! : 'Not set',
                        style: TextStyle(
                          fontWeight: FontWeight.w500,
                          color: (field.value != null && field.value!.trim().isNotEmpty)
                              ? scheme.onSurface
                              : scheme.onSurfaceVariant.withValues(alpha: 0.6),
                        ),
                      ),
                    ],
                  ),
                ),
            ],
          ),
        ],
      ),
    );
  }
}
