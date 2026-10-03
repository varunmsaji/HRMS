/// Permission code constants — added as each screen that checks one gets
/// built, not a full transcription of `apps/api`'s permission catalogue.
/// Mirrors `apps/api/src/hrms/modules/organisation/permissions.py`.
library;

const dashboardCompanyView = 'DASHBOARD.COMPANY.VIEW';

// Employee-record tabs (mirrors `apps/api/src/hrms/modules/employee/permissions.py`).
const employeeViewCompensation = 'EMPLOYEE.VIEW_COMPENSATION';
const employeeViewStatutory = 'EMPLOYEE.VIEW_STATUTORY';
const employeeViewBanking = 'EMPLOYEE.VIEW_BANKING';
const employeeViewSensitive = 'EMPLOYEE.VIEW_SENSITIVE';
const employeeViewExperience = 'EMPLOYEE.VIEW_EXPERIENCE';
const employeeViewNominee = 'EMPLOYEE.VIEW_NOMINEE';

// Onboarding (mirrors `apps/api/src/hrms/modules/onboarding/permissions.py`).
const onboardingCreate = 'ONBOARDING.CREATE';
const onboardingReview = 'ONBOARDING.REVIEW';
const onboardingActivate = 'ONBOARDING.ACTIVATE';

// Leave (mirrors `apps/api/src/hrms/modules/leave/permissions.py`).
const leaveBalanceViewAll = 'LEAVE.BALANCE_VIEW_ALL';
const leaveBalanceAdjust = 'LEAVE.BALANCE_ADJUST';

// Payroll (mirrors `apps/api/src/hrms/modules/payroll/permissions.py`).
const payrollRunProcess = 'PAYROLL.RUN_PROCESS';
const payrollRunApprove = 'PAYROLL.RUN_APPROVE';
const payrollBankAdviceDownload = 'PAYROLL.BANK_ADVICE_DOWNLOAD';
const payrollSetupManage = 'PAYROLL.SETUP_MANAGE';
const payrollStatutoryManage = 'PAYROLL.STATUTORY_MANAGE';

// Employee writes (mirrors `apps/api/src/hrms/modules/employee/permissions.py`).
const employeeCreate = 'EMPLOYEE.CREATE';
const employeeUpdate = 'EMPLOYEE.UPDATE';
const employeeDeactivate = 'EMPLOYEE.DEACTIVATE';
const employeeTerminate = 'EMPLOYEE.TERMINATE';
const employeeTransfer = 'EMPLOYEE.TRANSFER';
const employeePromote = 'EMPLOYEE.PROMOTE';
const employeeUpdateCompensation = 'EMPLOYEE.UPDATE_COMPENSATION';
const employeeUpdateSensitive = 'EMPLOYEE.UPDATE_SENSITIVE';
const employeeConfirm = 'EMPLOYEE.CONFIRM';
const employeeInvite = 'EMPLOYEE.INVITE';
const employeeBulkImport = 'EMPLOYEE.BULK_IMPORT';
