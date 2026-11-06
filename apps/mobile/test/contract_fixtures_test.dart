import 'dart:convert';
import 'dart:io';

import 'package:flutter_test/flutter_test.dart';
import 'package:hrms_mobile/features/organisation/domain/company_profile_form.dart';
import 'package:hrms_mobile/core/forms/form_spec.dart';
import 'package:hrms_mobile/features/employees/domain/employee_forms.dart';
import 'package:hrms_mobile/features/attendance/domain/policy_resources.dart';
import 'package:hrms_mobile/features/attendance/domain/policy_assignment_form.dart';
import 'package:hrms_mobile/features/attendance/domain/request_resources.dart';
import 'package:hrms_mobile/features/attendance/domain/roster_form.dart';
import 'package:hrms_mobile/features/attendance/presentation/attendance_period_detail_screen.dart' show periodActionLabels, periodBlockingReasonLabels, periodSummaryColumns;
import 'package:hrms_mobile/features/attendance/presentation/attendance_periods_screen.dart' show attendancePeriodSpec;
import 'package:hrms_mobile/features/leave/domain/leave_application_form.dart';
import 'package:hrms_mobile/features/leave/domain/leave_resources.dart';
import 'package:hrms_mobile/features/organisation/domain/org_resources.dart';
import 'package:hrms_mobile/features/payroll/domain/payroll_resources.dart';
import 'package:hrms_mobile/core/auth/auth_types.dart';
import 'package:hrms_mobile/features/attendance/data/attendance_repository.dart';
import 'package:hrms_mobile/features/attendance/data/policy_repository.dart';
import 'package:hrms_mobile/features/auth/data/auth_repository.dart';
import 'package:hrms_mobile/features/dashboard/data/dashboard_repository.dart';
import 'package:hrms_mobile/features/leave/data/leave_repository.dart';
import 'package:hrms_mobile/features/onboarding/data/onboarding_repository.dart';
import 'package:hrms_mobile/features/onboarding/data/public_onboarding_repository.dart';
import 'package:hrms_mobile/features/onboarding/domain/onboarding_form_spec.dart';
import 'package:hrms_mobile/features/organisation/data/organisation_repository.dart';
import 'package:hrms_mobile/features/payroll/data/payroll_repository.dart';
import 'package:hrms_mobile/features/profile/data/employee_repository.dart';
import 'package:hrms_mobile/features/profile/presentation/employee_record_sections.dart';

// Offline contract tests. The fixtures are generated from the backend's own response schemas
// (apps/mobile/tool/export_contract_fixtures.py) in two shapes: every field populated, and every
// nullable field null. Each mobile model must parse both. Regenerate after a backend schema
// change; a failure here names the model and the field that no longer lines up.

dynamic _load(String schema, String variant) =>
    jsonDecode(File('test/fixtures/contract/$schema.$variant.json').readAsStringSync());

typedef _Parser = Object? Function(Map<String, dynamic>);

final Map<String, _Parser> _models = {
  // attendance
  'organisation.ShiftRead': Shift.fromJson,
  'attendance.AttendanceDayRead': AttendanceDay.fromJson,
  'organisation.HolidayCalendarRead': HolidayCalendar.fromJson,
  'organisation.HolidayRead': Holiday.fromJson,
  'organisation.WeeklyOffPatternRead': WeeklyOffPattern.fromJson,
  'organisation.WorkCalendarRead': WorkCalendar.fromJson,
  'attendance.FacePunchRead': FacePunchResult.fromJson,
  'attendance.FaceEnrollmentStatusRead': FaceEnrollmentStatus.fromJson,
  'attendance.AttendancePolicyRead': PolicyIdentity.fromJson,
  'attendance.OvertimePolicyRead': PolicyIdentity.fromJson,
  'attendance.RegularizationPolicyRead': PolicyIdentity.fromJson,
  'attendance.AttendancePolicyVersionRead': PolicyVersion.fromJson,
  'attendance.OvertimePolicyVersionRead': PolicyVersion.fromJson,
  'attendance.RegularizationPolicyVersionRead': PolicyVersion.fromJson,
  // auth
  'identity.TokenResponseData': TokenResponseData.fromJson,
  'identity.CompanySummary': CompanySummary.fromJson,
  'identity.UserProfile': UserProfile.fromJson,
  'organisation.RegistrationConfigRead': RegistrationConfig.fromJson,
  'account_invite.PublicAccountInviteRead': PublicAccountInvite.fromJson,
  // dashboard
  'organisation.CompanyDashboardSummary': CompanyDashboardSummary.fromJson,
  'organisation.SubscriptionSummary': SubscriptionSummary.fromJson,
  'organisation.DashboardSetupProgress': DashboardSetupProgress.fromJson,
  // leave
  'leave.LeaveBalanceRead': LeaveBalance.fromJson,
  'leave.LeaveLedgerEntryRead': LeaveLedgerEntry.fromJson,
  'leave.LeaveApplicationRead': LeaveApplication.fromJson,
  'leave.LeaveTypeRead': LeaveType.fromJson,
  'leave.LeaveCombinationRuleRead': LeaveCombinationRule.fromJson,
  'leave.StatutoryLeaveMinimumRead': StatutoryLeaveMinimum.fromJson,
  'leave.LeaveYearSettingRead': LeaveYearSetting.fromJson,
  // onboarding
  'onboarding.OnboardingCaseRead': OnboardingCase.fromJson,
  'onboarding.OnboardingCaseDetailRead': OnboardingCaseDetail.fromJson,
  'onboarding.PublicOnboardingCaseRead': PublicOnboardingCase.fromJson,
  'onboarding.OnboardingDocumentRead': OnboardingDocument.fromJson,
  'onboarding.OnboardingDocumentWithUrlRead': OnboardingDocument.fromJson,
  'onboarding.OnboardingSectionReviewRead': SectionReview.fromJson,
  'organisation.SetupStepSummary': SetupStep.fromJson,
  'account_invite.UserSummary': UserSummary.fromJson,
  // organisation
  'organisation.LegalEntityRead': LegalEntity.fromJson,
  'organisation.BranchRead': Branch.fromJson,
  'organisation.DepartmentRead': Department.fromJson,
  'organisation.DesignationRead': Designation.fromJson,
  'organisation.GradeRead': Grade.fromJson,
  // payroll
  'payroll.PayRunRead': PayRun.fromJson,
  'payroll.PayRunEmployeeRead': PayRunEmployee.fromJson,
  'payroll.PayRunEmployeeDetailRead': PayRunEmployeeDetail.fromJson,
  'payroll.PayRunIssueRead': PayRunIssue.fromJson,
  'payroll.PayRunLineRead': PayRunLine.fromJson,
  'payroll.PayslipRead': Payslip.fromJson,
  'payroll.PayslipLineRead': PayslipLine.fromJson,
  'payroll.PayslipSummaryRead': PayslipSummary.fromJson,
  'payroll.PayAdjustmentRead': PayAdjustment.fromJson,
  'payroll.PayrollSettingRead': PayrollSetting.fromJson,
  'payroll.SalaryComponentRead': SalaryComponent.fromJson,
  'payroll.SalaryStructureRead': SalaryStructure.fromJson,
  'payroll.StatutoryRateRead': StatutoryRate.fromJson,
  // employee
  'employee.EmployeeRead': Employee.fromJson,
};

void main() {
  writeFormTests();
  group('every mobile model parses the backend schema', () {
    for (final entry in _models.entries) {
      for (final variant in const ['full', 'sparse']) {
        test('${entry.key} ($variant)', () {
          final json = _load(entry.key, variant) as Map<String, dynamic>;
          expect(() => entry.value(json), returnsNormally);
        });
      }
    }
  });

  group('employee record tabs read keys that exist in the backend schema', () {
    const schemaFor = {
      'Employment': 'employee.EmploymentRead',
      'Assignment': 'employee.AssignmentRead',
      'Compensation': 'employee.CompensationRead',
      'Statutory': 'employee.StatutoryRead',
      'Banking': 'employee.BankRead',
      'Identity': 'employee.EmployeeIdentityRead',
      'Experience': 'employee.EmployeeExperienceRead',
      'Education': 'employee.EmployeeEducationRead',
      'Dependents': 'employee.EmployeeDependentRead',
    };
    for (final section in employeeRecordSections) {
      test(section.title, () {
        final keys = (_load(schemaFor[section.title]!, 'full') as Map<String, dynamic>).keys.toSet();
        for (final f in section.fields) {
          expect(keys, contains(f.key), reason: '${section.title}: "${f.key}" is not in ${schemaFor[section.title]}');
        }
      });
    }
  });

  group('onboarding form specs cover exactly the backend section fields', () {
    // A PATCH replaces the whole section, so a field the form does not know about is silently
    // wiped on save — and a field the backend does not know about is rejected.
    const schemaFor = {
      'personal_info': 'onboarding.PersonalInfoSection',
      'address_info': 'onboarding.AddressInfoSection',
      'emergency_contact': 'onboarding.EmergencyContactSection',
      'bank_info': 'onboarding.BankInfoSection',
      'statutory_info': 'onboarding.StatutoryInfoSection',
      'compensation_info': 'onboarding.CompensationInfoSection',
      'previous_employment_info': 'onboarding.PreviousEmploymentItem',
      'education_info': 'onboarding.EducationItem',
      'nominee_info': 'onboarding.NomineeItem',
    };
    for (final spec in onboardingSections) {
      test(spec.name, () {
        final backend = (_load(schemaFor[spec.name]!, 'full') as Map<String, dynamic>).keys.toSet();
        final mine = spec.fields.map((f) => f.key).toSet();
        expect(mine.difference(backend), isEmpty, reason: 'keys the backend would reject');
        expect(backend.difference(mine), isEmpty, reason: 'backend fields the form would silently drop');
      });
    }
  });
}

// ---- write forms -----------------------------------------------------------------------------

Set<String> _requiredBy(String schema) => ((jsonDecode(File('test/fixtures/contract/_required.json').readAsStringSync()) as Map<String, dynamic>)[schema] as List).cast<String>().toSet();

void _writeFormMatches(String name, FormSpec spec, String schema, {Set<String> notInForm = const {}}) {
  test('$name -> $schema', () {
    final backend = (_load(schema, 'full') as Map<String, dynamic>).keys.toSet();
    // Edit-only fields (the active flag) exist only on the Update schemas.
    final isCreate = schema.endsWith('Create');
    // Create-only fields (read-only on edit) never reach a PATCH.
    final mine = spec.fields.where((f) => !(isCreate && f.editOnly) && !(!isCreate && f.readOnlyOnEdit)).map((f) => f.key).toSet();
    expect(mine.difference(backend), isEmpty, reason: 'keys the backend (extra="forbid") would reject');
    expect(backend.difference(mine).difference(notInForm), isEmpty, reason: 'backend fields the form does not offer');
    final requiredInSpec = spec.fields.where((f) => f.required).map((f) => f.key).toSet();
    if (!isCreate) return; // Update schemas make everything optional.
    // A field the backend requires must be required in the form too — unless it is a toggle,
    // which always has a value (false).
    final toggles = spec.fields.where((f) => f.kind == FieldKind.toggle).map((f) => f.key).toSet();
    expect(_requiredBy(schema).difference(requiredInSpec).difference(toggles), isEmpty, reason: 'backend-required fields the form lets you leave empty');
  });
}

void orgFormTests() {
  group('organisation write forms match the backend create/update schemas', () {
    for (final (name, spec, base) in [
      ('legalEntitySpec', legalEntitySpec, 'LegalEntity'),
      ('branchSpec', branchSpec(), 'Branch'),
      ('departmentSpec', departmentSpec, 'Department'),
      ('designationSpec', designationSpec, 'Designation'),
      ('gradeSpec', gradeSpec, 'Grade'),
      ('holidayCalendarSpec', holidayCalendarSpec, 'HolidayCalendar'),
      ('holidaySpec', holidaySpec, 'Holiday'),
      ('workCalendarSpec', workCalendarSpec, 'WorkCalendar'),
      ('calendarExceptionSpec', calendarExceptionSpec, 'CalendarException'),
      ('weeklyOffPatternSpec', weeklyOffPatternSpec, 'WeeklyOffPattern'),
    ]) {
      // `replaced_holiday_id` is an optional link the web does not offer either.
      _writeFormMatches('$name (create)', spec, 'organisation.${base}Create', notInForm: const {'replaced_holiday_id'});
      _writeFormMatches('$name (update)', spec, 'organisation.${base}Update', notInForm: const {'replaced_holiday_id'});
    }
  });

  group('organisation detail fields exist on the read schema', () {
    for (final (name, spec, read) in [
      ('legalEntity', legalEntitySpec, 'LegalEntityRead'),
      ('branch', branchSpec(), 'BranchRead'),
      ('department', departmentSpec, 'DepartmentRead'),
      ('designation', designationSpec, 'DesignationRead'),
      ('grade', gradeSpec, 'GradeRead'),
      ('holidayCalendar', holidayCalendarSpec, 'HolidayCalendarRead'),
      ('holiday', holidaySpec, 'HolidayRead'),
      ('workCalendar', workCalendarSpec, 'WorkCalendarRead'),
      ('calendarException', calendarExceptionSpec, 'CalendarExceptionRead'),
      ('weeklyOffPattern', weeklyOffPatternSpec, 'WeeklyOffPatternRead'),
    ]) {
      test(name, () {
        final keys = (_load('organisation.$read', 'full') as Map<String, dynamic>).keys.toSet();
        for (final f in spec.fields) {
          expect(keys, contains(f.key), reason: '$name shows "${f.key}" but $read has no such field');
        }
      });
    }
  });
}

void weeklyOffRuleTest() {
  test('weekly-off rules match WeeklyOffRuleInput', () {
    final backend = (_load('organisation.WeeklyOffRuleInput', 'full') as Map<String, dynamic>).keys.toSet();
    final mine = weeklyOffRuleSpec.fields.map((f) => f.key).toSet();
    expect(mine, backend);
    expect(weeklyOffRuleSpec.fields.firstWhere((f) => f.key == 'weekday').intValue, isTrue);
  });
}

void payrollFormTests() {
  group('payroll configuration forms match the backend schemas', () {
    _writeFormMatches('salaryComponentSpec (create)', salaryComponentSpec, 'payroll.SalaryComponentCreate');
    _writeFormMatches('salaryComponentSpec (update)', salaryComponentSpec, 'payroll.SalaryComponentUpdate');
    _writeFormMatches('salaryStructureSpec (create)', salaryStructureSpec, 'payroll.SalaryStructureCreate', notInForm: const {'lines'});
    _writeFormMatches('salaryStructureSpec (update)', salaryStructureSpec, 'payroll.SalaryStructureUpdate');
    test('structure lines match SalaryStructureLineInput', () {
      final backend = (_load('payroll.SalaryStructureLineInput', 'full') as Map<String, dynamic>).keys.toSet();
      final mine = structureLineSpec.fields.map((f) => f.key).toSet();
      expect(mine.difference(backend), isEmpty);
      expect(backend.difference(mine).difference(const {'display_order'}), isEmpty);
    });
    test('component and structure detail fields exist on the read schemas', () {
      for (final (spec, read) in [(salaryComponentSpec, 'payroll.SalaryComponentRead'), (salaryStructureSpec, 'payroll.SalaryStructureRead')]) {
        final keys = (_load(read, 'full') as Map<String, dynamic>).keys.toSet();
        for (final f in spec.fields) {
          expect(keys, contains(f.key), reason: '${spec.name} shows "${f.key}" but $read has none');
        }
      }
    });
    for (final (scheme, spec, schema) in [
      ('PF', pfParametersSpec, 'payroll.PfParameters'),
      ('ESI', esiParametersSpec, 'payroll.EsiParameters'),
      ('PT', ptParametersSpec, 'payroll.PtParameters'),
      ('LWF', lwfParametersSpec, 'payroll.LwfParameters'),
      ('TDS', tdsParametersSpec, 'payroll.TdsParameters'),
    ]) {
      test('$scheme parameters match $schema', () {
        final backend = (_load(schema, 'full') as Map<String, dynamic>).keys.toSet();
        final mine = spec.fields.map((f) => f.key).toSet();
        expect(mine, backend, reason: 'every parameter the backend defines, and no others');
        final required = _requiredBy(schema);
        final specRequired = spec.fields.where((f) => f.required).map((f) => f.key).toSet();
        expect(required.difference(specRequired), isEmpty, reason: 'backend-required parameters the form lets you skip');
      });
    }
    for (final (name, spec, schema) in [
      ('PT slabs', ptParametersSpec.fields.first.rowSpec!, 'payroll.PtSlab'),
      ('LWF slabs', lwfParametersSpec.fields.last.rowSpec!, 'payroll.LwfSlab'),
      ('TDS slabs', tdsParametersSpec.fields.last.rowSpec!, 'payroll.TdsSlab'),
    ]) {
      test('$name match $schema', () {
        final backend = (_load(schema, 'full') as Map<String, dynamic>).keys.toSet();
        expect(spec.fields.map((f) => f.key).toSet(), backend);
      });
    }
  });
}

void requestConfigTests() {
  group('request workflows render every backend field shape', () {
    for (final (name, config, read) in [
      ('regularization', regularizationConfig, 'attendance.RegularizationRequestRead'),
      ('overtime', overtimeConfig, 'attendance.OvertimeRecordRead'),
    ]) {
      for (final variant in const ['full', 'sparse']) {
        test('$name ($variant)', () {
          final row = _load(read, variant) as Map<String, dynamic>;
          expect(() => config.rowTitle(row, 'Asha'), returnsNormally);
          expect(() => config.rowSubtitle?.call(row), returnsNormally);
          expect(() => config.sections(row, 'Asia/Kolkata'), returnsNormally);
          expect(() => config.isPending(row), returnsNormally);
        });
      }
    }
    _writeFormMatchesRegularization();
  });
}

/// The regularization form has three UI-only keys that become `requested_punches`/`requested_shift_id`.
void _writeFormMatchesRegularization() {
  test('regularization form + body builder match RegularizationRequestCreate', () {
    final backend = (_load('attendance.RegularizationRequestCreate', 'full') as Map<String, dynamic>).keys.toSet();
    final body = buildRegularizationBody({
      'attendance_date': '2026-10-01',
      'request_type': 'MISSING_PUNCH',
      'employee_id': 'e',
      'reason': 'r',
      'attachment_reference': 'a',
      'correct_shift': false,
      'punch_in_time': '09:00',
      'punch_out_time': null,
    }, 'Asia/Kolkata');
    expect(body.keys.toSet().difference(backend), isEmpty, reason: 'keys the backend would reject');
    expect(body['requested_punches'], [
      {'direction': 'IN', 'requested_time': '2026-10-01T03:30:00.000Z'},
    ]);
    final shiftBody = buildRegularizationBody({'attendance_date': '2026-10-01', 'request_type': 'WRONG_SHIFT', 'correct_shift': true, 'requested_shift_id': 's', 'punch_in_time': null, 'punch_out_time': null}, 'Asia/Kolkata');
    expect(shiftBody.containsKey('requested_punches'), isFalse);
    expect(shiftBody['requested_shift_id'], 's');
    final formKeys = regularizationSpec(true).fields.map((f) => f.key).toSet();
    // The break-correction fields are not offered on the web either.
    expect(backend.difference(formKeys).difference(const {'requested_punches', 'break_start_event_id', 'requested_break_end', 'requested_break_minutes'}), isEmpty, reason: 'backend fields the form does not offer');
  });
}

void rosterContractTests() {
  group('roster form matches the backend schemas', () {
    test('create/update bodies use only ShiftRosterCreate/Update keys', () {
      final create = (_load('attendance.ShiftRosterCreate', 'full') as Map<String, dynamic>).keys.toSet();
      final update = (_load('attendance.ShiftRosterUpdate', 'full') as Map<String, dynamic>).keys.toSet();
      final p = {'employee_id': 'e', 'roster_date': '2026-10-01', 'day_kind': 'SHIFT', 'shift_id': 's', 'reason': 'r'};
      expect(rosterCreateBody(p).keys.toSet().difference(create), isEmpty);
      expect(rosterPatchBody(p).keys.toSet().difference(update), isEmpty);
      expect(create.difference(rosterCreateBody(p).keys.toSet()), isEmpty, reason: 'every create field is sent');
    });
    test('the read schema carries what the form needs to be edited', () {
      final keys = (_load('attendance.ShiftRosterRead', 'full') as Map<String, dynamic>).keys.toSet();
      expect(keys, containsAll(['employee_id', 'roster_date', 'shift_id', 'is_week_off_override', 'is_holiday_working_override', 'status', 'reason', 'version']));
    });
  });
}

void attendancePeriodTests() {
  rosterContractTests();
  group('attendance periods match the backend schemas', () {
    test('open-period form matches AttendancePeriodCreate', () {
      final backend = (_load('attendance.AttendancePeriodCreate', 'full') as Map<String, dynamic>).keys.toSet();
      final uiOnly = {'custom_range'};
      final mine = attendancePeriodSpec.fields.map((f) => f.key).toSet().difference(uiOnly);
      expect(mine, backend);
    });
    test('summary columns exist on AttendancePeriodSummaryRead', () {
      final keys = (_load('attendance.AttendancePeriodSummaryRead', 'full') as Map<String, dynamic>).keys.toSet();
      for (final (key, _) in periodSummaryColumns) {
        expect(keys, contains(key));
      }
    });
    test('the blocking-reason codes and action labels cover what the backend can say', () {
      // A label missing for a code the server sends would show the raw code — still readable, but flag it.
      expect(periodBlockingReasonLabels.keys, containsAll(['EMPLOYEES_WITHOUT_ATTENDANCE', 'PENDING_REGULARIZATION', 'UNPUBLISHED_ROSTER']));
      expect(periodActionLabels.keys, containsAll(['OPENED', 'VALIDATED', 'VALIDATION_FAILED', 'CLOSED', 'REOPENED']));
    });
  });
}

void leaveConfigTests() {
  group('leave configuration forms match the backend schemas', () {
    _writeFormMatches('leaveTypeSpec (create)', leaveTypeSpec, 'leave.LeaveTypeCreate');
    _writeFormMatches('leaveTypeSpec (update)', leaveTypeSpec, 'leave.LeaveTypeUpdate');
    _writeFormMatches('leaveCombinationRuleSpec', leaveCombinationRuleSpec, 'leave.LeaveCombinationRuleCreate');
    _writeFormMatches('statutoryLeaveMinimumSpec', statutoryLeaveMinimumSpec, 'leave.StatutoryLeaveMinimumCreate');
    for (final (spec, read) in [(leaveTypeSpec, 'leave.LeaveTypeRead'), (leaveCombinationRuleSpec, 'leave.LeaveCombinationRuleRead'), (statutoryLeaveMinimumSpec, 'leave.StatutoryLeaveMinimumRead')]) {
      test('${spec.name} fields exist on $read', () {
        final keys = (_load(read, 'full') as Map<String, dynamic>).keys.toSet();
        for (final f in spec.fields) {
          expect(keys, contains(f.key));
        }
      });
    }
  });
}

void companyProfileContractTests() {
  for (final variant in ['full', 'sparse']) {
    test('the company profile form reads $variant CompanyProfileRead and builds a patch the backend accepts', () {
      final profile = _load('organisation.CompanyProfileRead', variant) as Map<String, dynamic>;
      final form = profileToForm(profile);
      final spec = companyProfileSpec(currencyLocked: false);
      expect(form.keys, containsAll([for (final f in spec.fields) f.key]));
      expect(buildProfilePatch(form, const {}), isEmpty);
    });
  }
}

void resolutionContractTests() {
  companyProfileContractTests();
  test('the policy-resolution screen reads keys that exist on the backend schemas', () {
    final policy = (_load('attendance.PolicyResolutionRead', 'full') as Map<String, dynamic>).keys.toSet();
    expect(policy, containsAll(['config_incomplete', 'resolved_policy_name', 'resolved_policy_code', 'resolved_through', 'resolved_version_id']));
    final calendar = (_load('organisation.CalendarResolutionRead', 'full') as Map<String, dynamic>).keys.toSet();
    expect(calendar, containsAll(['config_incomplete', 'work_calendar_name', 'resolved_scope_type', 'weekly_off_resolved_scope_type', 'day_type']));
    final dayType = (_load('organisation.DayTypeRead', 'full') as Map<String, dynamic>).keys.toSet();
    expect(dayType, containsAll(['day_type', 'holiday_name']));
  });
}

void policyAssignmentContractTests() {
  resolutionContractTests();
  group('policy assignment form matches PolicyAssignmentCreate', () {
    _writeFormMatches('policyAssignmentSpec', policyAssignmentSpec, 'organisation.PolicyAssignmentCreate', notInForm: const {'priority', 'effective_to'});
    test('every policy and scope source the form can offer is a loadable choice source', () {
      expect(choiceSourcesOf(policyAssignmentSpec), containsAll([...assignablePolicySources.values, ...scopeSources.values, 'leave_types']));
    });
    test('the read schema has what the list shows', () {
      final keys = (_load('organisation.PolicyAssignmentRead', 'full') as Map<String, dynamic>).keys.toSet();
      expect(keys, containsAll(['policy_kind', 'policy_id', 'leave_type_id', 'scope_type', 'scope_id', 'effective_from', 'effective_to', 'reason', 'version']));
    });
  });
}

void leaveApplicationFormTests() {
  policyAssignmentContractTests();
  leaveConfigTests();
  attendancePeriodTests();
  requestConfigTests();
  group('onboarding case form matches OnboardingCaseCreate', () {
    _writeFormMatches('onboardingCaseSpec', onboardingCaseSpec, 'onboarding.OnboardingCaseCreate');
  });
  group('leave application form matches LeaveApplicationCreate', () {
    _writeFormMatches('self', leaveApplicationSpec(onBehalf: false), 'leave.LeaveApplicationCreate', notInForm: const {'employee_id'});
    _writeFormMatches('on behalf', leaveApplicationSpec(onBehalf: true), 'leave.LeaveApplicationCreate');
  });
}

void versionedFormTests() {
  leaveApplicationFormTests();
  payrollFormTests();
  weeklyOffRuleTest();
  void rowsMatch(FormSpec spec, Map<String, String> rowSchemas, {Set<String> orderKeys = const {'sort_order', 'sequence'}, Set<String> notInForm = const {}}) {
    for (final e in rowSchemas.entries) {
      final field = spec.fields.firstWhere((f) => f.key == e.key);
      test('${spec.name}.${e.key} rows -> ${e.value}', () {
        final backend = (_load(e.value, 'full') as Map<String, dynamic>).keys.toSet();
        final mine = field.rowSpec!.fields.map((f) => f.key).toSet();
        expect(mine.difference(backend), isEmpty, reason: 'row keys the backend would reject');
        expect(backend.difference(mine).difference(orderKeys).difference(notInForm), isEmpty, reason: 'row fields the form does not offer');
        final requiredInSpec = field.rowSpec!.fields.where((f) => f.required).map((f) => f.key).toSet();
        final toggles = field.rowSpec!.fields.where((f) => f.kind == FieldKind.toggle).map((f) => f.key).toSet();
        expect(_requiredBy(e.value).difference(requiredInSpec).difference(toggles).difference(orderKeys), isEmpty, reason: 'backend-required row fields left optional');
      });
    }
  }

  void readHas(String label, FormSpec spec, String read) {
    test('$label version fields exist on $read', () {
      final keys = (_load(read, 'full') as Map<String, dynamic>).keys.toSet();
      for (final f in spec.fields) {
        expect(keys, contains(f.key), reason: '$label shows "${f.key}" but $read has no such field');
      }
    });
  }

  group('versioned resources match the backend schemas', () {
    final shiftSpec = shiftVersionSpec();
    final all = <(String, FormSpec, String, String, Map<String, String>)>[
      ('attendance policy', attendancePolicyVersionSpec, 'attendance.AttendancePolicyVersion', 'attendance.AttendancePolicyVersionRead', {
        'hour_bands': 'attendance.AttendancePolicyHourBandInput',
        'late_bands': 'attendance.AttendancePolicyLateBandInput',
        'early_departure_bands': 'attendance.AttendancePolicyEarlyDepartureBandInput',
      }),
      ('overtime policy', overtimePolicyVersionSpec, 'attendance.OvertimePolicyVersion', 'attendance.OvertimePolicyVersionRead', {'rate_rows': 'attendance.OvertimePolicyRateRowInput'}),
      ('regularization policy', regularizationPolicyVersionSpec, 'attendance.RegularizationPolicyVersion', 'attendance.RegularizationPolicyVersionRead', {'allowed_types': 'attendance.RegularizationPolicyAllowedTypeInput'}),
      ('shift', shiftSpec, 'organisation.ShiftVersion', 'organisation.ShiftVersionRead', {'breaks': 'organisation.ShiftBreakCreate', 'duty_blocks': 'organisation.ShiftDutyBlockCreate'}),
      ('leave policy', leavePolicyVersionSpec, 'leave.LeavePolicyVersion', 'leave.LeavePolicyVersionRead', const {}),
    ];
    for (final (label, spec, base, read, rows) in all) {
      // Not offered on the web either.
      final notInForm = label == 'leave policy' ? const {'max_consecutive_days'} : const <String>{};
      _writeFormMatches('$label version (create)', spec, '${base}Create', notInForm: notInForm);
      _writeFormMatches('$label version (update)', spec, '${base}Update', notInForm: notInForm);
      readHas(label, spec, read);
      // The newer per-break rules are not offered on the web either.
      rowsMatch(spec, rows, notInForm: const {'auto_deduct_full', 'break_type', 'excess_outcome', 'is_enabled', 'mode', 'optional_recorded_deducts', 'optional_scheduled_fallback'});
    }
    _writeFormMatches('attendance policy', attendancePolicyIdentitySpec, 'attendance.AttendancePolicyCreate');
    _writeFormMatches('attendance policy (update)', attendancePolicyIdentitySpec, 'attendance.AttendancePolicyUpdate');
    _writeFormMatches('overtime policy', overtimePolicyIdentitySpec, 'attendance.OvertimePolicyCreate');
    _writeFormMatches('overtime policy (update)', overtimePolicyIdentitySpec, 'attendance.OvertimePolicyUpdate');
    _writeFormMatches('regularization policy', regularizationPolicyIdentitySpec, 'attendance.RegularizationPolicyCreate');
    _writeFormMatches('regularization policy (update)', regularizationPolicyIdentitySpec, 'attendance.RegularizationPolicyUpdate');
    _writeFormMatches('shift', shiftIdentitySpec, 'organisation.ShiftCreate');
    _writeFormMatches('shift (update)', shiftIdentitySpec, 'organisation.ShiftUpdate');
    _writeFormMatches('leave policy', leavePolicyIdentitySpec, 'leave.LeavePolicyCreate');
    _writeFormMatches('leave policy (update)', leavePolicyIdentitySpec, 'leave.LeavePolicyUpdate');
  });
}

void writeFormTests() {
  orgFormTests();
  versionedFormTests();
  group('employee write forms match the backend create/update schemas', () {
    _writeFormMatches('employeeSpec', employeeSpec, 'employee.EmployeeCreate', notInForm: {'custom_fields'});
    _writeFormMatches('employeeSpec (update)', employeeSpec, 'employee.EmployeeUpdate', notInForm: {'custom_fields', 'is_active'});
    _writeFormMatches('employmentCreateSpec', employmentCreateSpec, 'employee.EmploymentCreate');
    _writeFormMatches('employmentEditSpec', employmentEditSpec, 'employee.EmploymentUpdate');
    _writeFormMatches('employmentTerminateSpec', employmentTerminateSpec, 'employee.EmploymentTerminate');
    _writeFormMatches('assignmentSpec', assignmentSpec(const ['INITIAL']), 'employee.AssignmentCreate', notInForm: {
      'cost_centre_id',
      // Not offered on the web either.
      'clear_reporting_manager',
      // Sent by the confirmation step, not typed into the form.
      'confirm_pending_request_impact',
      'pending_impact_token',
    });
    _writeFormMatches('compensationSpec', compensationSpec, 'employee.CompensationCreate');
    _writeFormMatches('statutorySpec', statutorySpec, 'employee.StatutoryCreate');
    _writeFormMatches('bankSpec', bankSpec, 'employee.BankCreate');
    _writeFormMatches('identitySpec', identitySpec, 'employee.EmployeeIdentityUpdate');
    _writeFormMatches('experienceSpec', experienceSpec, 'employee.EmployeeExperienceCreate', notInForm: {'document_id'});
    _writeFormMatches('educationSpec', educationSpec, 'employee.EmployeeEducationCreate', notInForm: {'document_id'});
    _writeFormMatches('dependentSpec', dependentSpec, 'employee.EmployeeDependentCreate', notInForm: {'document_id'});
  });
}
