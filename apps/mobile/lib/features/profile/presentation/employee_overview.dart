import 'package:flutter/material.dart';

import '../../../core/theme/app_theme.dart';
import '../../../core/widgets/ui.dart';
import '../data/employee_repository.dart';

/// The Overview of an employee record — shared by My Profile and the manager view. Mirrors
/// `apps/web/src/components/employee/employee-overview.tsx`.
class EmployeeOverview extends StatelessWidget {
  const EmployeeOverview({super.key, required this.employee, this.actions = const []});

  final Employee employee;

  /// Buttons shown under the name (edit, deactivate, …).
  final List<Widget> actions;

  @override
  Widget build(BuildContext context) {
    final theme = Theme.of(context);
    final name = employee.fullName.isEmpty ? employee.employeeCode : employee.fullName;
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
                    child: InitialsAvatar(name: name, size: 56),
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
                        Text(employee.employeeCode, style: TextStyle(color: Colors.white.withValues(alpha: 0.7), fontSize: 13)),
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
            _OverviewField('Employee code', employee.employeeCode),
            _OverviewField('Date of birth', employee.dateOfBirth),
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
      ],
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
  const _OverviewSection({required this.title, required this.icon, required this.fields});

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
                        style: TextStyle(fontSize: 10.5, fontWeight: FontWeight.w700, color: scheme.onSurfaceVariant, letterSpacing: 0.6),
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
