import 'package:flutter/widgets.dart' show Column;
import '../../../core/auth/permissions.dart';
import '../../../core/forms/form_spec.dart';
import '../../../core/resource/resource_config.dart';
import '../../../core/resource/sub_resource_section.dart';
import '../../../core/time.dart';
import '../presentation/day_type_lookup.dart';

/// Resource configs for the organisation module — each spec mirrors a `*Create`/`*Update` schema
/// in `apps/api/.../organisation/schemas.py` and the matching web form.

const _active = FieldSpec('is_active', 'Active', kind: FieldKind.toggle, editOnly: true);

String? _join(Iterable<dynamic> parts, [String sep = ' · ']) {
  final s = parts.where((p) => p != null && p.toString().isNotEmpty).join(sep);
  return s.isEmpty ? null : s;
}

const legalEntitySpec = FormSpec(name: 'legal_entity', label: 'Legal entity', fields: [
  FieldSpec('name', 'Name', required: true),
  FieldSpec('registered_address', 'Registered address', kind: FieldKind.multiline),
  FieldSpec('pan', 'PAN', kind: FieldKind.upper),
  FieldSpec('tan', 'TAN', kind: FieldKind.upper),
  FieldSpec('cin', 'CIN', kind: FieldKind.upper),
  FieldSpec('gstin', 'GSTIN', kind: FieldKind.upper),
  FieldSpec('pf_code', 'PF code'),
  FieldSpec('esi_code', 'ESI code'),
  FieldSpec('lwf_reg', 'LWF registration'),
  FieldSpec('signatory_name', 'Authorised signatory'),
  FieldSpec('signatory_designation', 'Signatory designation'),
  FieldSpec('signature_image_url', 'Signature image URL'),
  _active,
]);

final legalEntityResource = ResourceConfig(
  title: 'Legal Entities',
  singular: 'Legal entity',
  path: '/legal-entities',
  spec: legalEntitySpec,
  rowTitle: (r) => r['name'] as String,
  rowSubtitle: (r) => _join([r['pan'], r['gstin']]),
  manage: orgLegalEntityManage,
);

/// Built at first use: the timezone options come from the tz database.
FormSpec branchSpec() => FormSpec(name: 'branch', label: 'Branch', fields: [
      const FieldSpec('legal_entity_id', 'Legal entity', kind: FieldKind.choice, choiceKey: 'legal_entities', required: true),
      const FieldSpec('name', 'Name', required: true),
      const FieldSpec('address_line1', 'Address line 1'),
      const FieldSpec('address_line2', 'Address line 2'),
      const FieldSpec('city', 'City'),
      const FieldSpec('state_code', 'State code'),
      const FieldSpec('pincode', 'Pincode'),
      FieldSpec('timezone', 'Timezone', kind: FieldKind.select, options: allTimeZones(), hint: "Leave unset to inherit the company's timezone."),
      const FieldSpec('latitude', 'Latitude', kind: FieldKind.decimal),
      const FieldSpec('longitude', 'Longitude', kind: FieldKind.decimal),
      const FieldSpec('geofence_radius_m', 'Geofence radius (metres)', kind: FieldKind.integer),
      _active,
    ]);

ResourceConfig branchResource() => ResourceConfig(
      title: 'Branches',
      singular: 'Branch',
      path: '/branches',
      spec: branchSpec(),
      rowTitle: (r) => r['name'] as String,
      rowSubtitle: (r) => _join([r['code'], r['city']]),
      manage: orgBranchManage,
    );

const departmentSpec = FormSpec(name: 'department', label: 'Department', fields: [
  FieldSpec('name', 'Name', required: true),
  FieldSpec('branch_id', 'Branch', kind: FieldKind.choice, choiceKey: 'branches'),
  FieldSpec('parent_id', 'Parent department', kind: FieldKind.choice, choiceKey: 'departments'),
  FieldSpec('head_employee_id', 'Department head', kind: FieldKind.choice, choiceKey: 'employees'),
  _active,
]);

final departmentResource = ResourceConfig(
  title: 'Departments',
  singular: 'Department',
  path: '/departments',
  spec: departmentSpec,
  rowTitle: (r) => r['name'] as String,
  rowSubtitle: (r) => r['code'] as String?,
  manage: orgDepartmentManage,
);

const designationSpec = FormSpec(name: 'designation', label: 'Designation', fields: [
  FieldSpec('title', 'Title', required: true),
  FieldSpec('department_id', 'Department', kind: FieldKind.choice, choiceKey: 'departments'),
  FieldSpec('grade_id', 'Grade', kind: FieldKind.choice, choiceKey: 'grades'),
  _active,
]);

final designationResource = ResourceConfig(
  title: 'Designations',
  singular: 'Designation',
  path: '/designations',
  spec: designationSpec,
  rowTitle: (r) => r['title'] as String,
  rowSubtitle: (r) => r['code'] as String?,
  manage: orgDesignationManage,
);

const gradeSpec = FormSpec(name: 'grade', label: 'Grade', fields: [
  FieldSpec('name', 'Name', required: true),
  FieldSpec('level', 'Level', kind: FieldKind.integer),
  FieldSpec('min_ctc', 'Minimum CTC', kind: FieldKind.integer, hint: 'Whole rupees'),
  FieldSpec('max_ctc', 'Maximum CTC', kind: FieldKind.integer, hint: 'Whole rupees'),
  FieldSpec('notice_period_days', 'Notice period (days)', kind: FieldKind.integer),
  FieldSpec('probation_days', 'Probation (days)', kind: FieldKind.integer),
  FieldSpec('approval_limit', 'Approval limit', kind: FieldKind.integer),
  _active,
]);

final gradeResource = ResourceConfig(
  title: 'Grades',
  singular: 'Grade',
  path: '/grades',
  spec: gradeSpec,
  rowTitle: (r) => r['name'] as String,
  rowSubtitle: (r) => _join([r['code'], r['level'] != null ? 'Level ${r['level']}' : null]),
  manage: orgGradeManage,
);

// ---- calendars --------------------------------------------------------------------------------

const holidayCalendarSpec = FormSpec(name: 'holiday_calendar', label: 'Holiday calendar', defaults: {'kind': 'COMPANY'}, fields: [
  FieldSpec('name', 'Name', required: true),
  FieldSpec('kind', 'Kind', kind: FieldKind.select, required: true, options: ['NATIONAL', 'REGIONAL', 'COMPANY', 'LOCATION']),
  FieldSpec('state_code', 'State code'),
  FieldSpec('valid_from', 'Valid from', kind: FieldKind.date),
  FieldSpec('valid_to', 'Valid to', kind: FieldKind.date),
  _active,
]);

const holidayTypeLabels = {'PUBLIC': 'Public', 'COMPANY': 'Company', 'OPTIONAL': 'Optional', 'RESTRICTED': 'Restricted', 'WORKING_HOLIDAY': 'Working holiday'};

const holidaySpec = FormSpec(name: 'holiday', label: 'Holiday', defaults: {'holiday_type': 'PUBLIC', 'is_paid': true}, fields: [
  FieldSpec('date', 'Date', kind: FieldKind.date, required: true, readOnlyOnEdit: true),
  FieldSpec('name', 'Name', required: true),
  FieldSpec('holiday_type', 'Type', kind: FieldKind.select, required: true, options: ['PUBLIC', 'COMPANY', 'OPTIONAL', 'RESTRICTED', 'WORKING_HOLIDAY'], optionLabels: holidayTypeLabels),
  FieldSpec('is_paid', 'Paid', kind: FieldKind.toggle),
  FieldSpec('is_working', 'Working day', kind: FieldKind.toggle),
  FieldSpec('region_note', 'Region note'),
  _active,
]);

final holidayCalendarResource = ResourceConfig(
  title: 'Holiday Calendars',
  singular: 'Holiday calendar',
  path: '/holiday-calendars',
  spec: holidayCalendarSpec,
  rowTitle: (r) => r['name'] as String,
  rowSubtitle: (r) => _join([r['kind'], r['valid_from'] != null ? '${r['valid_from']} → ${r['valid_to'] ?? 'open'}' : null]),
  manage: orgCalendarManage,
  detailExtras: (context, row, reload) => SubResourceSection(
    title: 'Holidays',
    singular: 'holiday',
    listPath: '/holiday-calendars/${row['id']}/holidays',
    itemPath: (h) => '/holidays/${h['id']}',
    spec: holidaySpec,
    manage: orgHolidayManage,
    rowTitle: (h) => '${h['date']} · ${h['name']}',
    rowSubtitle: (h) => _join([holidayTypeLabels[h['holiday_type']] ?? h['holiday_type'], h['is_paid'] == true ? 'paid' : 'unpaid', h['is_working'] == true ? 'working' : null]),
    emptyLabel: 'No holidays in this calendar yet.',
  ),
);

const exceptionTypeLabels = {
  'SPECIAL_WORKING': 'Special working day',
  'SHUTDOWN': 'Shutdown',
  'SUBSTITUTE_HOLIDAY': 'Substitute holiday',
  'CANCEL_HOLIDAY': 'Cancel holiday',
};

const calendarExceptionSpec = FormSpec(name: 'calendar_exception', label: 'Calendar exception', fields: [
  FieldSpec('exception_date', 'Date', kind: FieldKind.date, required: true, readOnlyOnEdit: true),
  FieldSpec('exception_type', 'Type', kind: FieldKind.select, required: true, readOnlyOnEdit: true, options: ['SPECIAL_WORKING', 'SHUTDOWN', 'SUBSTITUTE_HOLIDAY', 'CANCEL_HOLIDAY'], optionLabels: exceptionTypeLabels),
  FieldSpec('name', 'Name'),
  FieldSpec('reason', 'Reason', kind: FieldKind.multiline),
  FieldSpec('is_paid', 'Paid', kind: FieldKind.toggle),
  _active,
]);

const workCalendarSpec = FormSpec(name: 'work_calendar', label: 'Work calendar', fields: [
  FieldSpec('name', 'Name', required: true),
  FieldSpec('description', 'Description', kind: FieldKind.multiline),
  FieldSpec('weekly_off_pattern_id', 'Weekly-off pattern', kind: FieldKind.choice, choiceKey: 'weekly_off_patterns'),
  FieldSpec('restricted_holidays_are_off_by_default', 'Restricted holidays are off by default', kind: FieldKind.toggle),
  FieldSpec('holiday_calendar_ids', 'Holiday calendars', kind: FieldKind.multiChoice, choiceKey: 'holiday_calendars'),
  _active,
]);

final workCalendarResource = ResourceConfig(
  title: 'Work Calendars',
  singular: 'Work calendar',
  path: '/work-calendars',
  spec: workCalendarSpec,
  rowTitle: (r) => r['name'] as String,
  rowSubtitle: (r) => r['code'] as String?,
  manage: orgCalendarManage,
  detailExtras: (context, row, reload) => Column(children: [
    SubResourceSection(
      title: 'Exceptions',
      singular: 'exception',
      listPath: '/work-calendars/${row['id']}/exceptions',
      itemPath: (e) => '/calendar-exceptions/${e['id']}',
      spec: calendarExceptionSpec,
      manage: orgCalendarManage,
      rowTitle: (e) => '${e['exception_date']} · ${exceptionTypeLabels[e['exception_type']] ?? e['exception_type']}',
      rowSubtitle: (e) => _join([e['name'], e['reason']]),
      emptyLabel: 'No exceptions yet.',
    ),
    DayTypeLookup(calendarId: row['id'] as String),
  ]),
);

// ---- weekly-off patterns ----------------------------------------------------------------------

const weekdayLabels = {'0': 'Monday', '1': 'Tuesday', '2': 'Wednesday', '3': 'Thursday', '4': 'Friday', '5': 'Saturday', '6': 'Sunday'};

const weeklyOffRuleSpec = FormSpec(name: 'weekly_off_rule', label: 'Rule', defaults: {'weekday': 6, 'off_fraction': '1.00'}, fields: [
  FieldSpec('weekday', 'Weekday', kind: FieldKind.select, required: true, intValue: true, options: ['0', '1', '2', '3', '4', '5', '6'], optionLabels: weekdayLabels),
  FieldSpec('nth_in_month', 'Which one in the month', kind: FieldKind.select, intValue: true, options: ['1', '2', '3', '4', '5', '-1'], optionLabels: {'-1': 'Last', '1': '1st', '2': '2nd', '3': '3rd', '4': '4th', '5': '5th'}, hint: 'Leave empty for every week'),
  FieldSpec('cycle_start_date', 'Cycle start date', kind: FieldKind.date, hint: 'For alternating patterns'),
  FieldSpec('off_fraction', 'Day off', kind: FieldKind.select, required: true, options: ['1.00', '0.50'], optionLabels: {'1.00': 'Full day', '0.50': 'Half day'}),
  FieldSpec('week_parity', 'Week parity', kind: FieldKind.select, options: ['EVEN', 'ODD'], hint: 'For alternating patterns'),
]);

const weeklyOffPatternSpec = FormSpec(name: 'weekly_off_pattern', label: 'Weekly-off pattern', defaults: {'pattern_kind': 'FIXED_WEEKDAYS'}, fields: [
  FieldSpec('name', 'Name', required: true),
  FieldSpec('pattern_kind', 'Pattern kind', kind: FieldKind.select, required: true, options: ['FIXED_WEEKDAYS', 'NTH_WEEKDAY', 'ALTERNATE', 'CUSTOM']),
  FieldSpec('rules', 'Rules', kind: FieldKind.rows, required: true, rowNoun: 'rule', rowSpec: weeklyOffRuleSpec),
  _active,
]);

final weeklyOffPatternResource = ResourceConfig(
  title: 'Weekly-Off Patterns',
  singular: 'Weekly-off pattern',
  path: '/weekly-off-patterns',
  spec: weeklyOffPatternSpec,
  rowTitle: (r) => r['name'] as String,
  rowSubtitle: (r) => _join([r['code'], prettyEnum('${r['pattern_kind']}')]),
  manage: orgCalendarManage,
);
