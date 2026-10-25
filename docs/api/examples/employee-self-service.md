# Employee self-service flow (invite, accept, punch, leave, payslips) - recorded exchanges

> **Recorded, not synthesized.** Produced by [`../tools/record_examples.py`](../tools/record_examples.py) against a local API (`ENVIRONMENT=development`, isolated `hrms_test` database, `COMPANY_APPROVAL_REQUIRED=false`, `EMAIL_PROVIDER=logging`) on 2026-10-24. Access tokens, refresh cookies and one-time email tokens are redacted; all other values are verbatim. The throwaway password in these files is a documentation-only value.

### [setup] Create a legal entity

```http
POST /v1/legal-entities
Authorization: Bearer <access_token>
Content-Type: application/json

{
  "name": "Docs Legal Entity b98e2392"
}
```

**Response `201`**

```http
content-type: application/json
x-request-id: 8552b56f-c2bf-4889-af0b-a0f486170a7e

{
  "data": {
    "id": "9567a0cf-6d8a-4ae4-b24d-5e1d00631110",
    "company_id": "d3e41c33-a411-4d21-bbe0-2de3eb93eb8f",
    "name": "Docs Legal Entity b98e2392",
    "registered_address": null,
    "pan": null,
    "tan": null,
    "cin": null,
    "gstin": null,
    "pf_code": null,
    "esi_code": null,
    "lwf_reg": null,
    "signatory_name": null,
    "signatory_designation": null,
    "signature_image_url": null,
    "is_active": true,
    "version": 1,
    "created_at": "2026-10-24T16:58:40.445208Z",
    "updated_at": "2026-10-24T16:58:40.445208Z"
  },
  "meta": {
    "request_id": "8552b56f-c2bf-4889-af0b-a0f486170a7e",
    "server_time": "2026-10-24T16:58:40.446378Z"
  }
}
```

### [setup] Create an employee

```http
POST /v1/employees
Authorization: Bearer <access_token>
Content-Type: application/json

{
  "first_name": "Ravi",
  "last_name": "Kumar",
  "personal_email": "docs.employee.b98e2392@example.com"
}
```

**Response `201`**

```http
content-type: application/json
x-request-id: bf95187b-0c0a-4681-996a-5e369e807885

{
  "data": {
    "id": "210ea709-0d72-4d82-a43e-6772eb888a62",
    "company_id": "d3e41c33-a411-4d21-bbe0-2de3eb93eb8f",
    "employee_code": "EMP-0001",
    "first_name": "Ravi",
    "middle_name": null,
    "last_name": "Kumar",
    "display_name": null,
    "date_of_birth": null,
    "gender": null,
    "blood_group": null,
    "marital_status": null,
    "nationality": null,
    "father_or_husband_name": null,
    "personal_email": "docs.employee.b98e2392@example.com",
    "personal_mobile": null,
    "present_address_line1": null,
    "present_address_line2": null,
    "present_city": null,
    "present_state_code": null,
    "present_pincode": null,
    "present_country_code": null,
    "permanent_address_line1": null,
    "permanent_address_line2": null,
    "permanent_city": null,
    "permanent_state_code": null,
    "permanent_pincode": null,
    "permanent_country_code": null,
    "permanent_same_as_present": true,
    "emergency_contact_name": null,
    "emergency_contact_relationship": null,
    "emergency_contact_phone": null,
    "photo_url": null,
    "status": "PRE_JOINING",
    "custom_fields": null,
    "is_active": true,
    "version": 1,
    "created_at": "2026-10-24T16:58:40.492926Z",
    "updated_at": "2026-10-24T16:58:40.492926Z",
    "employment_joining_date": null,
    "employment_last_working_day": null
  },
  "meta": {
    "request_id": "bf95187b-0c0a-4681-996a-5e369e807885",
    "server_time": "2026-10-24T16:58:40.494490Z"
  }
}
```

### [setup] Start the employment (joining date in the past)

```http
POST /v1/employees/210ea709-0d72-4d82-a43e-6772eb888a62/employments
Authorization: Bearer <access_token>
Content-Type: application/json

{
  "legal_entity_id": "9567a0cf-6d8a-4ae4-b24d-5e1d00631110",
  "joining_date": "2026-01-01"
}
```

**Response `201`**

```http
content-type: application/json
x-request-id: 51cff0f0-179a-4df5-8e5a-131c74c395a7

{
  "data": {
    "id": "80df4e90-6d0d-410a-8281-f4e619cdeb10",
    "company_id": "d3e41c33-a411-4d21-bbe0-2de3eb93eb8f",
    "employee_id": "210ea709-0d72-4d82-a43e-6772eb888a62",
    "legal_entity_id": "9567a0cf-6d8a-4ae4-b24d-5e1d00631110",
    "joining_date": "2026-01-01",
    "last_working_day": null,
    "probation_end_date": null,
    "pay_basis": "MONTHLY",
    "status": "ACTIVE",
    "previous_employment_id": null,
    "version": 1,
    "created_at": "2026-10-24T16:58:40.502922Z",
    "updated_at": "2026-10-24T16:58:40.502922Z"
  },
  "meta": {
    "request_id": "51cff0f0-179a-4df5-8e5a-131c74c395a7",
    "server_time": "2026-10-24T16:58:40.506948Z"
  }
}
```

### [setup] Invite the employee to create an account

No request body: the invite goes to the employee's `personal_email`.

```http
POST /v1/employees/210ea709-0d72-4d82-a43e-6772eb888a62/invite
Authorization: Bearer <access_token>
```

**Response `201`**

```http
content-type: application/json
x-request-id: 5054942a-87ad-4c63-9a9f-4b9641df0c8c

{
  "data": {
    "id": "6884e8c2-19d4-4bd8-bd94-cad740c7d39b",
    "email": "docs.employee.b98e2392@example.com",
    "role_code": "EMPLOYEE",
    "expires_at": "2026-10-31T16:58:40.733975Z",
    "invite_url": "http://localhost:3000/accept-invite/<one-time-token>",
    "email_sent": true
  },
  "meta": {
    "request_id": "5054942a-87ad-4c63-9a9f-4b9641df0c8c",
    "server_time": "2026-10-24T16:58:40.736470Z"
  }
}
```

### Resolve the invite link (public)

```http
GET /v1/public/account-invites/<one-time-token>
```

**Response `200`**

```http
content-type: application/json
x-request-id: 078ad8a5-9bcf-4dee-bd7e-a6da1a717299

{
  "data": {
    "email": "docs.employee.b98e2392@example.com",
    "company_name": "Docs Example Pvt Ltd b98e2392",
    "expires_at": "2026-10-31T16:58:40.733975Z",
    "existing_account": false
  },
  "meta": {
    "request_id": "078ad8a5-9bcf-4dee-bd7e-a6da1a717299",
    "server_time": "2026-10-24T16:58:40.741806Z"
  }
}
```

### Accept the invite (public) - creates the account and signs in

Returns the same token payload as login; the refresh token is again only in `Set-Cookie`.

```http
POST /v1/public/account-invites/<one-time-token>/accept
Content-Type: application/json

{
  "password": "Docs-Example-Pass1"
}
```

**Response `201`**

```http
content-type: application/json
set-cookie: hrms_refresh=<refresh-token>; HttpOnly; Max-Age=2592000; Path=/v1/auth; SameSite=lax
x-request-id: fed55407-4cff-450a-91d9-bef6331bfef4

{
  "data": {
    "access_token": "<jwt-access-token>",
    "token_type": "Bearer",
    "expires_in_minutes": 15,
    "company_id": "d3e41c33-a411-4d21-bbe0-2de3eb93eb8f",
    "companies": [
      {
        "id": "d3e41c33-a411-4d21-bbe0-2de3eb93eb8f",
        "name": "Docs Example Pvt Ltd b98e2392",
        "is_primary": true
      }
    ]
  },
  "meta": {
    "request_id": "fed55407-4cff-450a-91d9-bef6331bfef4",
    "server_time": "2026-10-24T16:58:40.792831Z"
  }
}
```

### Employee: `/auth/me` (note `employee_id` and `permissions`)

```http
GET /v1/auth/me
Authorization: Bearer <access_token>
```

**Response `200`**

```http
content-type: application/json
x-request-id: a909694f-c45e-43e5-bfcf-ed3ffe29e90b

{
  "data": {
    "user": {
      "id": "ed9d1b76-24cc-4ea5-b761-8516a661ecec",
      "email": "docs.employee.b98e2392@example.com",
      "company_id": "d3e41c33-a411-4d21-bbe0-2de3eb93eb8f",
      "employee_id": "210ea709-0d72-4d82-a43e-6772eb888a62",
      "permissions": [
        "ATTENDANCE.PUNCH",
        "ATTENDANCE.REGULARIZATION_REQUEST",
        "ATTENDANCE.VIEW",
        "EMPLOYEE.VIEW",
        "EMPLOYEE.VIEW_BANKING",
        "EMPLOYEE.VIEW_COMPENSATION",
        "EMPLOYEE.VIEW_DOCUMENTS",
        "EMPLOYEE.VIEW_EXPERIENCE",
        "EMPLOYEE.VIEW_NOMINEE",
        "EMPLOYEE.VIEW_SENSITIVE",
        "EMPLOYEE.VIEW_STATUTORY",
        "LEAVE.APPLICATION_SUBMIT",
        "LEAVE.BALANCE_VIEW",
        "PAYROLL.PAYSLIP_VIEW_OWN"
      ],
      "company_timezone": "Asia/Kolkata",
      "company_status": "TRIAL"
    }
  },
  "meta": {
    "request_id": "a909694f-c45e-43e5-bfcf-ed3ffe29e90b",
    "server_time": "2026-10-24T16:58:40.797838Z"
  }
}
```

### Employee: self punch IN (default `EMPLOYEE` role, no extra setup)

Since the C-1 remediation the default `EMPLOYEE` role holds SELF-scoped ATTENDANCE.PUNCH/VIEW/REGULARIZATION_REQUEST; before it this call returned 403 PERMISSION_DENIED.

```http
POST /v1/attendance/punches/me
Authorization: Bearer <access_token>
Content-Type: application/json

{
  "direction": "IN",
  "reference": "docs-example"
}
```

**Response `201`**

```http
content-type: application/json
x-request-id: 612a1d76-ad14-4be7-b603-cc31ee72b108

{
  "data": {
    "id": "c211ef19-04c8-4104-b091-25b2d7ec4dbd",
    "company_id": "d3e41c33-a411-4d21-bbe0-2de3eb93eb8f",
    "employee_id": "210ea709-0d72-4d82-a43e-6772eb888a62",
    "punch_time": "2026-10-24T16:58:40.803432Z",
    "direction": "IN",
    "source": "WEB",
    "idempotency_key": null,
    "recorded_by_user_id": "ed9d1b76-24cc-4ea5-b761-8516a661ecec",
    "reference": "docs-example",
    "created_at": "2026-10-24T16:58:40.803432Z"
  },
  "meta": {
    "request_id": "612a1d76-ad14-4be7-b603-cc31ee72b108",
    "server_time": "2026-10-24T16:58:40.835349Z"
  }
}
```

### Employee: cannot punch for someone else -> 403

```http
POST /v1/attendance/punches
Authorization: Bearer <access_token>
Content-Type: application/json

{
  "employee_id": "210ea709-0d72-4d82-a43e-6772eb888a62",
  "direction": "IN",
  "reference": "x",
  "punch_time": "2026-02-02T09:00:00Z"
}
```

**Response `403`**

```http
content-type: application/json
x-request-id: 63569fbe-63ab-4440-845c-3098cc4dcef4

{
  "error": {
    "code": "PERMISSION_DENIED",
    "message": "Permission ATTENDANCE.PUNCH_ON_BEHALF is required",
    "details": [],
    "request_id": "63569fbe-63ab-4440-845c-3098cc4dcef4",
    "documentation_url": null
  }
}
```

### Employee: punch IN again (what happens on a duplicate direction?)

```http
POST /v1/attendance/punches/me
Authorization: Bearer <access_token>
Content-Type: application/json

{
  "direction": "IN"
}
```

**Response `201`**

```http
content-type: application/json
x-request-id: 5ea09a67-1414-4999-9bd9-ea3332ee725f

{
  "data": {
    "id": "ba16d757-1844-4ec3-be24-6d0811046d95",
    "company_id": "d3e41c33-a411-4d21-bbe0-2de3eb93eb8f",
    "employee_id": "210ea709-0d72-4d82-a43e-6772eb888a62",
    "punch_time": "2026-10-24T16:58:40.845119Z",
    "direction": "IN",
    "source": "WEB",
    "idempotency_key": null,
    "recorded_by_user_id": "ed9d1b76-24cc-4ea5-b761-8516a661ecec",
    "reference": null,
    "created_at": "2026-10-24T16:58:40.845119Z"
  },
  "meta": {
    "request_id": "5ea09a67-1414-4999-9bd9-ea3332ee725f",
    "server_time": "2026-10-24T16:58:40.864342Z"
  }
}
```

### Employee: bad direction -> 422

```http
POST /v1/attendance/punches/me
Authorization: Bearer <access_token>
Content-Type: application/json

{
  "direction": "SIDEWAYS"
}
```

**Response `422`**

```http
content-type: application/json
x-request-id: 777d8a7c-ba4e-44ec-8134-a3288f69e705

{
  "error": {
    "code": "REQUEST_VALIDATION_ERROR",
    "message": "Request validation failed",
    "details": [
      {
        "field": "body.direction",
        "code": "value_error",
        "message": "direction must be one of ('IN', 'OUT')",
        "context": null
      }
    ],
    "request_id": "777d8a7c-ba4e-44ec-8134-a3288f69e705",
    "documentation_url": null
  }
}
```

### Employee: self punch OUT

```http
POST /v1/attendance/punches/me
Authorization: Bearer <access_token>
Content-Type: application/json

{
  "direction": "OUT"
}
```

**Response `201`**

```http
content-type: application/json
x-request-id: f03112db-01a6-42f8-ba95-82563630cbde

{
  "data": {
    "id": "8ecb0bbf-c709-489d-b0f1-2c0c94577caa",
    "company_id": "d3e41c33-a411-4d21-bbe0-2de3eb93eb8f",
    "employee_id": "210ea709-0d72-4d82-a43e-6772eb888a62",
    "punch_time": "2026-10-24T16:58:40.872530Z",
    "direction": "OUT",
    "source": "WEB",
    "idempotency_key": null,
    "recorded_by_user_id": "ed9d1b76-24cc-4ea5-b761-8516a661ecec",
    "reference": null,
    "created_at": "2026-10-24T16:58:40.872530Z"
  },
  "meta": {
    "request_id": "f03112db-01a6-42f8-ba95-82563630cbde",
    "server_time": "2026-10-24T16:58:40.885048Z"
  }
}
```

### Employee: my punches today

```http
GET /v1/attendance/punches?employee_id=210ea709-0d72-4d82-a43e-6772eb888a62&date_from=2026-10-24&date_to=2026-10-24
Authorization: Bearer <access_token>
```

**Response `200`**

```http
content-type: application/json
x-request-id: 9cfaffde-4e9d-4c83-a980-20ee1b662689

{
  "data": [
    {
      "id": "8ecb0bbf-c709-489d-b0f1-2c0c94577caa",
      "company_id": "d3e41c33-a411-4d21-bbe0-2de3eb93eb8f",
      "employee_id": "210ea709-0d72-4d82-a43e-6772eb888a62",
      "punch_time": "2026-10-24T16:58:40.872530Z",
      "direction": "OUT",
      "source": "WEB",
      "idempotency_key": null,
      "recorded_by_user_id": "ed9d1b76-24cc-4ea5-b761-8516a661ecec",
      "reference": null,
      "created_at": "2026-10-24T16:58:40.872530Z"
    },
    {
      "id": "ba16d757-1844-4ec3-be24-6d0811046d95",
      "company_id": "d3e41c33-a411-4d21-bbe0-2de3eb93eb8f",
      "employee_id": "210ea709-0d72-4d82-a43e-6772eb888a62",
      "punch_time": "2026-10-24T16:58:40.845119Z",
      "direction": "IN",
      "source": "WEB",
      "idempotency_key": null,
      "recorded_by_user_id": "ed9d1b76-24cc-4ea5-b761-8516a661ecec",
      "reference": null,
      "created_at": "2026-10-24T16:58:40.845119Z"
    },
    {
      "id": "c211ef19-04c8-4104-b091-25b2d7ec4dbd",
      "company_id": "d3e41c33-a411-4d21-bbe0-2de3eb93eb8f",
      "employee_id": "210ea709-0d72-4d82-a43e-6772eb888a62",
      "punch_time": "2026-10-24T16:58:40.803432Z",
      "direction": "IN",
      "source": "WEB",
      "idempotency_key": null,
      "recorded_by_user_id": "ed9d1b76-24cc-4ea5-b761-8516a661ecec",
      "reference": "docs-example",
      "created_at": "2026-10-24T16:58:40.803432Z"
    }
  ],
  "pagination": {
    "page": 1,
    "per_page": 500,
    "total": 3,
    "total_pages": 1,
    "next_cursor": null
  },
  "meta": {
    "request_id": "9cfaffde-4e9d-4c83-a980-20ee1b662689",
    "server_time": "2026-10-24T16:58:40.891043Z"
  }
}
```

### Employee: bounded list - `per_page=1` pages through my punches

```http
GET /v1/attendance/punches?employee_id=210ea709-0d72-4d82-a43e-6772eb888a62&per_page=1&page=2
Authorization: Bearer <access_token>
```

**Response `200`**

```http
content-type: application/json
x-request-id: 0c1677d1-0176-4559-b971-decb499d7332

{
  "data": [
    {
      "id": "ba16d757-1844-4ec3-be24-6d0811046d95",
      "company_id": "d3e41c33-a411-4d21-bbe0-2de3eb93eb8f",
      "employee_id": "210ea709-0d72-4d82-a43e-6772eb888a62",
      "punch_time": "2026-10-24T16:58:40.845119Z",
      "direction": "IN",
      "source": "WEB",
      "idempotency_key": null,
      "recorded_by_user_id": "ed9d1b76-24cc-4ea5-b761-8516a661ecec",
      "reference": null,
      "created_at": "2026-10-24T16:58:40.845119Z"
    }
  ],
  "pagination": {
    "page": 2,
    "per_page": 1,
    "total": 3,
    "total_pages": 3,
    "next_cursor": null
  },
  "meta": {
    "request_id": "0c1677d1-0176-4559-b971-decb499d7332",
    "server_time": "2026-10-24T16:58:40.896014Z"
  }
}
```

### Employee: my attendance days

```http
GET /v1/attendance/days?employee_id=210ea709-0d72-4d82-a43e-6772eb888a62&date_from=2026-10-24&date_to=2026-10-24
Authorization: Bearer <access_token>
```

**Response `200`**

```http
content-type: application/json
x-request-id: 1bf34c2e-a117-4481-a7bd-0a9444e82348

{
  "data": [
    {
      "id": "5ae5d88b-553f-4a07-89f5-8bfb07bea9ed",
      "company_id": "d3e41c33-a411-4d21-bbe0-2de3eb93eb8f",
      "employee_id": "210ea709-0d72-4d82-a43e-6772eb888a62",
      "attendance_date": "2026-10-24",
      "timezone": "Asia/Kolkata",
      "shift_id": null,
      "shift_version_id": null,
      "work_calendar_id": null,
      "attendance_policy_version_id": null,
      "overtime_policy_version_id": null,
      "regularization_policy_version_id": null,
      "calendar_day_type": null,
      "holiday_name": null,
      "holiday_on_weekly_off": false,
      "scheduled_start": null,
      "scheduled_end": null,
      "scheduled_minutes": null,
      "actual_first_in": null,
      "actual_last_out": null,
      "worked_minutes": 0,
      "unpaid_break_minutes": 0,
      "paid_break_minutes": 0,
      "excess_break_minutes": 0,
      "attendance_status": "CONFIG_ERROR",
      "late_minutes": 0,
      "early_departure_minutes": 0,
      "late_classification": null,
      "early_departure_classification": null,
      "missing_punch": false,
      "auto_closed": false,
      "is_late": false,
      "is_early_out": false,
      "is_overtime": false,
      "is_regularized": false,
      "is_pending_approval": false,
      "worked_on_holiday": false,
      "worked_on_weekly_off": false,
      "work_on_leave_flagged": false,
      "work_on_leave_resolution": null,
      "work_on_leave_resolution_reason": null,
      "work_on_leave_resolved_by": null,
      "work_on_leave_resolved_at": null,
      "is_core_hours_breach": false,
      "on_duty": false,
      "on_duty_regularization_id": null,
      "paid_day_fraction": "0.00",
      "lop_fraction": "0.00",
      "leave_fraction": "0.00",
      "weekly_off_fraction": "0.00",
      "unpaid_off_fraction": "0.00",
      "ot_minutes_detected": 0,
      "ot_minutes_approved": 0,
      "ot_pending": false,
      "ot_classification": null,
      "ot_day_class": null,
      "comp_off_minutes_earned": 0,
      "calculation_version": 3,
      "engine_version": 2,
      "computation_snapshot": {
        "inputs": {
          "timezone": "Asia/Kolkata",
          "punch_ids": [
            "c211ef19-04c8-4104-b091-25b2d7ec4dbd",
            "ba16d757-1844-4ec3-be24-6d0811046d95",
            "8ecb0bbf-c709-489d-b0f1-2c0c94577caa"
          ],
          "employee_id": "210ea709-0d72-4d82-a43e-6772eb888a62",
          "attendance_date": "2026-10-24",
          "calendar_day_type": null,
          "population_status": "ACTIVE"
        },
        "derived_inputs": {
          "pay_basis": "MONTHLY",
          "holiday_type": null,
          "leave_entries": [],
          "holiday_is_paid": true,
          "on_duty_approved": false,
          "weekly_off_fraction": "1.00",
          "roster_week_off_override": false,
          "prior_late_days_in_window": 0,
          "remaining_weekly_ot_minutes": null,
          "early_departure_pre_approved": false,
          "remaining_monthly_ot_minutes": null,
          "roster_holiday_working_override": false,
          "prior_excess_break_days_in_window": 0
        },
        "engine_version": 2,
        "terminal_reason": "no_calendar_resolved"
      },
      "calculated_at": "2026-10-24T16:58:40.881726Z",
      "is_locked": false,
      "locked_at": null,
      "locked_by": null,
      "breaks": [],
      "created_at": "2026-10-24T16:58:40.829076Z",
      "updated_at": "2026-10-24T16:58:40.881720Z"
    }
  ],
  "pagination": {
    "page": 1,
    "per_page": 500,
    "total": 1,
    "total_pages": 1,
    "next_cursor": null
  },
  "meta": {
    "request_id": "1bf34c2e-a117-4481-a7bd-0a9444e82348",
    "server_time": "2026-10-24T16:58:40.903142Z"
  }
}
```

### Employee: another employee's id is refused/empty

```http
GET /v1/attendance/days?employee_id=7d41d870-a6e5-49f8-9aa9-cbd9d2a3aa03
Authorization: Bearer <access_token>
```

**Response `200`**

```http
content-type: application/json
x-request-id: bbc667c5-d519-4c6d-bc6d-9dfaa4db9496

{
  "data": [],
  "pagination": {
    "page": 1,
    "per_page": 500,
    "total": 0,
    "total_pages": 0,
    "next_cursor": null
  },
  "meta": {
    "request_id": "bbc667c5-d519-4c6d-bc6d-9dfaa4db9496",
    "server_time": "2026-10-24T16:58:40.909140Z"
  }
}
```

### Employee: leave types

```http
GET /v1/leave-types
Authorization: Bearer <access_token>
```

**Response `200`**

```http
content-type: application/json
x-request-id: 7b2b54e2-53b6-42ac-bb65-e7a753875f3f

{
  "data": [],
  "pagination": null,
  "meta": {
    "request_id": "7b2b54e2-53b6-42ac-bb65-e7a753875f3f",
    "server_time": "2026-10-24T16:58:40.914594Z"
  }
}
```

### Employee: leave balances (employee_id is a REQUIRED query param)

```http
GET /v1/leave-balances?employee_id=210ea709-0d72-4d82-a43e-6772eb888a62
Authorization: Bearer <access_token>
```

**Response `200`**

```http
content-type: application/json
x-request-id: 48db5a6e-cd82-4394-8284-00e8ff82d29a

{
  "data": [],
  "pagination": null,
  "meta": {
    "request_id": "48db5a6e-cd82-4394-8284-00e8ff82d29a",
    "server_time": "2026-10-24T16:58:40.921713Z"
  }
}
```

### Employee: leave balances without employee_id -> 422

```http
GET /v1/leave-balances
Authorization: Bearer <access_token>
```

**Response `422`**

```http
content-type: application/json
x-request-id: 21cff33e-0d42-48eb-abb6-ed2fa5cdcf1f

{
  "error": {
    "code": "REQUEST_VALIDATION_ERROR",
    "message": "Request validation failed",
    "details": [
      {
        "field": "query.employee_id",
        "code": "missing",
        "message": "Field required",
        "context": null
      }
    ],
    "request_id": "21cff33e-0d42-48eb-abb6-ed2fa5cdcf1f",
    "documentation_url": null
  }
}
```

### Employee: my own record

```http
GET /v1/employees/210ea709-0d72-4d82-a43e-6772eb888a62
Authorization: Bearer <access_token>
```

**Response `200`**

```http
content-type: application/json
x-request-id: 5723f4b1-f5f1-4aab-9fe3-b167dc1ad0c9

{
  "data": {
    "id": "210ea709-0d72-4d82-a43e-6772eb888a62",
    "company_id": "d3e41c33-a411-4d21-bbe0-2de3eb93eb8f",
    "employee_code": "EMP-0001",
    "first_name": "Ravi",
    "middle_name": null,
    "last_name": "Kumar",
    "display_name": null,
    "date_of_birth": null,
    "gender": null,
    "blood_group": null,
    "marital_status": null,
    "nationality": null,
    "father_or_husband_name": null,
    "personal_email": "docs.employee.b98e2392@example.com",
    "personal_mobile": null,
    "present_address_line1": null,
    "present_address_line2": null,
    "present_city": null,
    "present_state_code": null,
    "present_pincode": null,
    "present_country_code": null,
    "permanent_address_line1": null,
    "permanent_address_line2": null,
    "permanent_city": null,
    "permanent_state_code": null,
    "permanent_pincode": null,
    "permanent_country_code": null,
    "permanent_same_as_present": true,
    "emergency_contact_name": null,
    "emergency_contact_relationship": null,
    "emergency_contact_phone": null,
    "photo_url": null,
    "status": "PROBATION",
    "custom_fields": null,
    "is_active": true,
    "version": 2,
    "created_at": "2026-10-24T16:58:40.492926Z",
    "updated_at": "2026-10-24T16:58:40.744164Z",
    "employment_joining_date": null,
    "employment_last_working_day": null
  },
  "meta": {
    "request_id": "5723f4b1-f5f1-4aab-9fe3-b167dc1ad0c9",
    "server_time": "2026-10-24T16:58:40.928870Z"
  }
}
```

### Employee: my payslips (none yet)

```http
GET /v1/me/payslips
Authorization: Bearer <access_token>
```

**Response `200`**

```http
content-type: application/json
x-request-id: b9bc5456-8999-4332-bcd7-3d368c91caf2

{
  "data": [],
  "pagination": null,
  "meta": {
    "request_id": "b9bc5456-8999-4332-bcd7-3d368c91caf2",
    "server_time": "2026-10-24T16:58:40.935908Z"
  }
}
```

### Employee: admin-only route -> 403

```http
GET /v1/companies/current
Authorization: Bearer <access_token>
```

**Response `403`**

```http
content-type: application/json
x-request-id: 1f1a3532-b885-4b0f-b259-51785d80199e

{
  "error": {
    "code": "PERMISSION_DENIED",
    "message": "Permission ORG.COMPANY.MANAGE is required",
    "details": [],
    "request_id": "1f1a3532-b885-4b0f-b259-51785d80199e",
    "documentation_url": null
  }
}
```

### Employee: write to a manager-only route -> 403

```http
POST /v1/branches
Authorization: Bearer <access_token>
Content-Type: application/json

{
  "name": "x"
}
```

**Response `403`**

```http
content-type: application/json
x-request-id: 6345ac46-1751-4223-8b40-a31db2a8e3eb

{
  "error": {
    "code": "PERMISSION_DENIED",
    "message": "Permission ORG.BRANCH.MANAGE is required",
    "details": [],
    "request_id": "6345ac46-1751-4223-8b40-a31db2a8e3eb",
    "documentation_url": null
  }
}
```

### Employee: logout

```http
POST /v1/auth/logout
Authorization: Bearer <access_token>
```

**Response `204`**

```http
content-type: application/json
set-cookie: hrms_refresh=""; expires=Sat, 24 Oct 2026 16:58:40 GMT; Max-Age=0; Path=/v1/auth; SameSite=lax
x-request-id: a9b4bde9-c3f6-4ea1-acb8-b2fd05dbd541

(empty body)
```
