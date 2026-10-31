import 'package:flutter/material.dart';

import 'employee_status_chip.dart';
import 'layout.dart';
import 'status_map.dart';

/// One leave application, correction or overtime record: title, caption, status chip, chevron.
/// Put several inside an [EmployeeListGroup].
class RequestRow extends StatelessWidget {
  const RequestRow({super.key, required this.title, this.caption, required this.status, this.onTap});

  final String title;
  final String? caption;
  final EmployeeStatus status;
  final VoidCallback? onTap;

  @override
  Widget build(BuildContext context) => EmployeeListRow(
        title: title,
        caption: caption,
        trailing: EmployeeStatusChip(status: status),
        onTap: onTap,
      );
}
