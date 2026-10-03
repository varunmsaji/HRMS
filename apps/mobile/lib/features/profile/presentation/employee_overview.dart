import 'package:flutter/material.dart';

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
    final scheme = Theme.of(context).colorScheme;
    return ListView(
      padding: const EdgeInsets.all(16),
      children: [
        Row(
          children: [
            CircleAvatar(
              radius: 28,
              backgroundColor: scheme.primaryContainer.withValues(alpha: 0.3),
              child: Text(
                employee.fullName.isEmpty ? '?' : employee.fullName.trim()[0].toUpperCase(),
                style: TextStyle(fontSize: 22, fontWeight: FontWeight.w700, color: scheme.primary),
              ),
            ),
            const SizedBox(width: 14),
            Expanded(
              child: Column(
                crossAxisAlignment: CrossAxisAlignment.start,
                children: [
                  Text(employee.fullName, style: Theme.of(context).textTheme.headlineMedium),
                  Text(employee.employeeCode, style: TextStyle(color: scheme.onSurfaceVariant)),
                ],
              ),
            ),
            Container(
              padding: const EdgeInsets.symmetric(horizontal: 8, vertical: 2),
              decoration: BoxDecoration(color: scheme.surfaceContainerHigh, borderRadius: BorderRadius.circular(4)),
              child: Text(employee.status.toUpperCase(), style: const TextStyle(fontSize: 11, fontWeight: FontWeight.w600)),
            ),
          ],
        ),
        if (actions.isNotEmpty) ...[const SizedBox(height: 12), Wrap(spacing: 8, runSpacing: 8, children: actions)],
        const SizedBox(height: 12),
        _OverviewSection(
          title: 'Identity',
          fields: [
            _OverviewField('Employee code', employee.employeeCode),
            _OverviewField('Date of birth', employee.dateOfBirth),
            _OverviewField('Gender', employee.gender),
            _OverviewField('Marital status', employee.maritalStatus),
            _OverviewField('Blood group', employee.bloodGroup),
            _OverviewField('Nationality', employee.nationality),
          ],
        ),
        const SizedBox(height: 20),
        _OverviewSection(
          title: 'Personal contact',
          fields: [
            _OverviewField('Personal email', employee.personalEmail),
            _OverviewField('Personal mobile', employee.personalMobile),
          ],
        ),
        const SizedBox(height: 20),
        _OverviewSection(
          title: 'Present address',
          fields: [
            _OverviewField('Address', employee.presentAddressLine1),
            _OverviewField('Address line 2', employee.presentAddressLine2),
            _OverviewField('City', employee.presentCity),
            _OverviewField('State', employee.presentStateCode),
            _OverviewField('Pincode', employee.presentPincode),
            _OverviewField('Country', employee.presentCountryCode),
          ],
        ),
        const SizedBox(height: 20),
        _OverviewSection(
          title: 'Emergency contact',
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

class _OverviewField {
  const _OverviewField(this.label, this.value);
  final String label;
  final String? value;
}

class _OverviewSection extends StatelessWidget {
  const _OverviewSection({required this.title, required this.fields});

  final String title;
  final List<_OverviewField> fields;

  @override
  Widget build(BuildContext context) {
    final scheme = Theme.of(context).colorScheme;
    return Container(
      padding: const EdgeInsets.all(16),
      decoration: BoxDecoration(
        color: scheme.surfaceContainerLowest,
        borderRadius: BorderRadius.circular(12),
        border: Border.all(color: scheme.outlineVariant),
      ),
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          Text(title, style: Theme.of(context).textTheme.headlineSmall),
          const SizedBox(height: 12),
          Wrap(
            runSpacing: 16,
            children: [
              for (final field in fields)
                SizedBox(
                  width: (MediaQuery.of(context).size.width - 32 - 32) / 2,
                  child: Column(
                    crossAxisAlignment: CrossAxisAlignment.start,
                    children: [
                      Text(
                        field.label.toUpperCase(),
                        style: TextStyle(fontSize: 11, fontWeight: FontWeight.w600, color: scheme.onSurfaceVariant, letterSpacing: 0.4),
                      ),
                      const SizedBox(height: 3),
                      Text(
                        (field.value != null && field.value!.trim().isNotEmpty) ? field.value! : 'Not configured',
                        style: TextStyle(
                          color: (field.value != null && field.value!.trim().isNotEmpty) ? scheme.onSurface : scheme.onSurfaceVariant,
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
