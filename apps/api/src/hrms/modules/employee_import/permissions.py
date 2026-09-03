"""employee_import defines no permission codes of its own — every endpoint reuses
`EMPLOYEE.BULK_IMPORT`, defined in `employee/permissions.py` (see that module's docstring for
why it lives there: it's picked up automatically by `OrganisationService.register_company`'s
existing `EMPLOYEE_PERMISSIONS` grant loop and by `seed/bootstrap.py`, both of which already
iterate that list). Re-exported here only so this module's router has a local, discoverable
import point matching the Module Standard's per-module `permissions.py` shape."""

from hrms.modules.employee.permissions import EMPLOYEE_BULK_IMPORT

__all__ = ["EMPLOYEE_BULK_IMPORT"]
