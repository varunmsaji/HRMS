import 'dart:convert';
import 'dart:io';

import 'package:flutter_test/flutter_test.dart';
import 'package:hrms_mobile/core/forms/form_spec.dart';
import 'package:hrms_mobile/features/employees/domain/employee_forms.dart';
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
  'attendance.RegularizationRequestRead': RegularizationRequest.fromJson,
  'organisation.ShiftRead': Shift.fromJson,
  'attendance.OvertimeRecordRead': OvertimeRecord.fromJson,
  'attendance.ShiftRosterRead': ShiftRoster.fromJson,
  'attendance.AttendancePeriodRead': AttendancePeriod.fromJson,
  'attendance.AttendanceDayRead': AttendanceDay.fromJson,
  'organisation.PolicyAssignmentRead': PolicyAssignment.fromJson,
  'organisation.CalendarResolutionRead': CalendarResolution.fromJson,
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
  'organisation.CompanyProfileRead': CompanyProfile.fromJson,
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
    final mine = spec.fields.map((f) => f.key).toSet();
    expect(mine.difference(backend), isEmpty, reason: 'keys the backend (extra="forbid") would reject');
    expect(backend.difference(mine).difference(notInForm), isEmpty, reason: 'backend fields the form does not offer');
    final requiredInSpec = spec.fields.where((f) => f.required).map((f) => f.key).toSet();
    // A field the backend requires must be required in the form too — unless it is a toggle,
    // which always has a value (false).
    final toggles = spec.fields.where((f) => f.kind == FieldKind.toggle).map((f) => f.key).toSet();
    expect(_requiredBy(schema).difference(requiredInSpec).difference(toggles), isEmpty, reason: 'backend-required fields the form lets you leave empty');
  });
}

void writeFormTests() {
  group('employee write forms match the backend create/update schemas', () {
    _writeFormMatches('employeeSpec', employeeSpec, 'employee.EmployeeCreate', notInForm: {'custom_fields'});
    _writeFormMatches('employeeSpec (update)', employeeSpec, 'employee.EmployeeUpdate', notInForm: {'custom_fields', 'is_active'});
    _writeFormMatches('employmentCreateSpec', employmentCreateSpec, 'employee.EmploymentCreate');
    _writeFormMatches('employmentEditSpec', employmentEditSpec, 'employee.EmploymentUpdate');
    _writeFormMatches('employmentTerminateSpec', employmentTerminateSpec, 'employee.EmploymentTerminate');
    _writeFormMatches('assignmentSpec', assignmentSpec(const ['INITIAL']), 'employee.AssignmentCreate', notInForm: {'cost_centre_id'});
    _writeFormMatches('compensationSpec', compensationSpec, 'employee.CompensationCreate');
    _writeFormMatches('statutorySpec', statutorySpec, 'employee.StatutoryCreate');
    _writeFormMatches('bankSpec', bankSpec, 'employee.BankCreate');
    _writeFormMatches('identitySpec', identitySpec, 'employee.EmployeeIdentityUpdate');
    _writeFormMatches('experienceSpec', experienceSpec, 'employee.EmployeeExperienceCreate', notInForm: {'document_id'});
    _writeFormMatches('educationSpec', educationSpec, 'employee.EmployeeEducationCreate', notInForm: {'document_id'});
    _writeFormMatches('dependentSpec', dependentSpec, 'employee.EmployeeDependentCreate', notInForm: {'document_id'});
  });
}
