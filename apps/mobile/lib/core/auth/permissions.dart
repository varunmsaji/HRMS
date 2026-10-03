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
