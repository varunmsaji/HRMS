# Envelope, pagination, validation & error conventions - recorded exchanges

> **Recorded, not synthesized.** Produced by [`../tools/record_examples.py`](../tools/record_examples.py) against a local API (`ENVIRONMENT=development`, isolated `hrms_test` database, `COMPANY_APPROVAL_REQUIRED=false`, `EMAIL_PROVIDER=logging`) on 2026-10-24. Access tokens, refresh cookies and one-time email tokens are redacted; all other values are verbatim. The throwaway password in these files is a documentation-only value.

### Request without a token -> 401

```http
GET /v1/branches
```

**Response `401`**

```http
www-authenticate: Bearer
content-type: application/json
x-request-id: 310cea72-7360-46c3-8221-4d4374af5846

{
  "error": {
    "code": "UNAUTHORIZED",
    "message": "Authentication required",
    "details": [],
    "request_id": "310cea72-7360-46c3-8221-4d4374af5846",
    "documentation_url": null
  }
}
```

### `X-Company-Id` that does not match the token -> 404

```http
GET /v1/branches
Authorization: Bearer <access_token>
X-Company-Id: 69ea15f0-c0e8-4458-8ea3-f67a35896898
```

**Response `404`**

```http
content-type: application/json
x-request-id: 5f83f44d-3f02-4cb7-a023-ac482c4cd083

{
  "error": {
    "code": "NOT_FOUND",
    "message": "Resource not found",
    "details": [],
    "request_id": "5f83f44d-3f02-4cb7-a023-ac482c4cd083",
    "documentation_url": null
  }
}
```

### Paginated list (employees) - `pagination` object present

```http
GET /v1/employees?page=1&per_page=5
Authorization: Bearer <access_token>
```

**Response `200`**

```http
content-type: application/json
x-request-id: fe96e102-3fe6-418c-9b2c-07c04c95963e

{
  "data": [
    {
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
      "employment_joining_date": "2026-01-01",
      "employment_last_working_day": null
    }
  ],
  "pagination": {
    "page": 1,
    "per_page": 5,
    "total": 1,
    "total_pages": 1,
    "next_cursor": null
  },
  "meta": {
    "request_id": "fe96e102-3fe6-418c-9b2c-07c04c95963e",
    "server_time": "2026-10-24T16:58:40.955227Z"
  }
}
```

### `per_page` above the cap (100) -> 422

```http
GET /v1/employees?per_page=500
Authorization: Bearer <access_token>
```

**Response `422`**

```http
content-type: application/json
x-request-id: b9fb2c58-9d22-43bb-b5d2-d10d403a9f55

{
  "error": {
    "code": "REQUEST_VALIDATION_ERROR",
    "message": "Request validation failed",
    "details": [
      {
        "field": "query.per_page",
        "code": "less_than_equal",
        "message": "Input should be less than or equal to 100",
        "context": null
      }
    ],
    "request_id": "b9fb2c58-9d22-43bb-b5d2-d10d403a9f55",
    "documentation_url": null
  }
}
```

### Create employee with an `Idempotency-Key`

```http
POST /v1/employees
Authorization: Bearer <access_token>
Idempotency-Key: docs-debd86077c214e0da01d40ed6818234b
Content-Type: application/json

{
  "first_name": "Idem",
  "personal_email": "docs.idem.b98e2392@example.com"
}
```

**Response `201`**

```http
content-type: application/json
x-request-id: b8a24972-d99a-4eca-8010-cd40fc7ab0ef

{
  "data": {
    "id": "355b0a65-a29b-40b2-91e5-61d0a5a8b46d",
    "company_id": "d3e41c33-a411-4d21-bbe0-2de3eb93eb8f",
    "employee_code": "EMP-0002",
    "first_name": "Idem",
    "middle_name": null,
    "last_name": null,
    "display_name": null,
    "date_of_birth": null,
    "gender": null,
    "blood_group": null,
    "marital_status": null,
    "nationality": null,
    "father_or_husband_name": null,
    "personal_email": "docs.idem.b98e2392@example.com",
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
    "created_at": "2026-10-24T16:58:40.965346Z",
    "updated_at": "2026-10-24T16:58:40.965346Z",
    "employment_joining_date": null,
    "employment_last_working_day": null
  },
  "meta": {
    "request_id": "b8a24972-d99a-4eca-8010-cd40fc7ab0ef",
    "server_time": "2026-10-24T16:58:40.967377Z"
  }
}
```

### Retry with the same key -> replay (`Idempotent-Replayed: true`, same employee)

```http
POST /v1/employees
Authorization: Bearer <access_token>
Idempotency-Key: docs-debd86077c214e0da01d40ed6818234b
Content-Type: application/json

{
  "first_name": "Idem",
  "personal_email": "docs.idem.b98e2392@example.com"
}
```

**Response `201`**

```http
content-type: application/json
idempotent-replayed: true
x-request-id: 9dbdefb4-5c2e-4e53-a355-1ff2127a8fdc

{
  "data": {
    "id": "355b0a65-a29b-40b2-91e5-61d0a5a8b46d",
    "company_id": "d3e41c33-a411-4d21-bbe0-2de3eb93eb8f",
    "employee_code": "EMP-0002",
    "first_name": "Idem",
    "middle_name": null,
    "last_name": null,
    "display_name": null,
    "date_of_birth": null,
    "gender": null,
    "blood_group": null,
    "marital_status": null,
    "nationality": null,
    "father_or_husband_name": null,
    "personal_email": "docs.idem.b98e2392@example.com",
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
    "created_at": "2026-10-24T16:58:40.965346Z",
    "updated_at": "2026-10-24T16:58:40.965346Z",
    "employment_joining_date": null,
    "employment_last_working_day": null
  },
  "meta": {
    "request_id": "9dbdefb4-5c2e-4e53-a355-1ff2127a8fdc",
    "server_time": "2026-10-24T16:58:40.973505Z"
  }
}
```

### Same key, different body -> 409

```http
POST /v1/employees
Authorization: Bearer <access_token>
Idempotency-Key: docs-debd86077c214e0da01d40ed6818234b
Content-Type: application/json

{
  "first_name": "Other",
  "personal_email": "docs.idem.b98e2392@example.com"
}
```

**Response `409`**

```http
content-type: application/json
x-request-id: 151cb525-4c5d-4d61-ba05-a8f570735d9f

{
  "error": {
    "code": "IDEMPOTENCY_KEY_CONFLICT",
    "message": "This Idempotency-Key was already used for a different request",
    "details": [
      {
        "field": "Idempotency-Key",
        "code": "IDEMPOTENCY_KEY_CONFLICT",
        "message": "Use a new Idempotency-Key for a different request",
        "context": null
      }
    ],
    "request_id": "151cb525-4c5d-4d61-ba05-a8f570735d9f",
    "documentation_url": null
  }
}
```

### Bounded collection: attendance days

```http
GET /v1/attendance/days?per_page=2
Authorization: Bearer <access_token>
```

**Response `200`**

```http
content-type: application/json
x-request-id: 0f26973d-bec8-4c72-b6bc-967c5e75ad6c

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
    "per_page": 2,
    "total": 1,
    "total_pages": 1,
    "next_cursor": null
  },
  "meta": {
    "request_id": "0f26973d-bec8-4c72-b6bc-967c5e75ad6c",
    "server_time": "2026-10-24T16:58:40.989453Z"
  }
}
```

### Counter-example: master-data lists are NOT paginated

`/v1/branches` accepts no `page`/`per_page`: the query is ignored and `pagination` is `null` (the whole collection is returned).

```http
GET /v1/branches?page=2&per_page=5
Authorization: Bearer <access_token>
```

**Response `200`**

```http
content-type: application/json
x-request-id: 59472d28-c5d3-4211-996d-7e89c7cd6b45

{
  "data": [],
  "pagination": null,
  "meta": {
    "request_id": "59472d28-c5d3-4211-996d-7e89c7cd6b45",
    "server_time": "2026-10-24T16:58:40.995260Z"
  }
}
```

### Validation error shape

```http
POST /v1/branches
Authorization: Bearer <access_token>
Content-Type: application/json

{
  "name": ""
}
```

**Response `422`**

```http
content-type: application/json
x-request-id: 3d59c8f7-d60a-41b1-ba6e-4999e8449cab

{
  "error": {
    "code": "REQUEST_VALIDATION_ERROR",
    "message": "Request validation failed",
    "details": [
      {
        "field": "body.legal_entity_id",
        "code": "missing",
        "message": "Field required",
        "context": null
      },
      {
        "field": "body.name",
        "code": "string_too_short",
        "message": "String should have at least 1 character",
        "context": null
      }
    ],
    "request_id": "3d59c8f7-d60a-41b1-ba6e-4999e8449cab",
    "documentation_url": null
  }
}
```

### PATCH without `If-Match` -> 422

```http
PATCH /v1/companies/current
Authorization: Bearer <access_token>
Content-Type: application/json

{
  "name": "Renamed"
}
```

**Response `422`**

```http
content-type: application/json
x-request-id: 20ec1d66-b9a0-438f-81f8-3a999e888f9c

{
  "error": {
    "code": "REQUEST_VALIDATION_ERROR",
    "message": "Request validation failed",
    "details": [
      {
        "field": "header.If-Match",
        "code": "missing",
        "message": "Field required",
        "context": null
      }
    ],
    "request_id": "20ec1d66-b9a0-438f-81f8-3a999e888f9c",
    "documentation_url": null
  }
}
```

### Company profile (`version` is the concurrency token)

```http
GET /v1/companies/current
Authorization: Bearer <access_token>
```

**Response `200`**

```http
content-type: application/json
x-request-id: 7c4e00c5-e3a2-4863-a974-25a6aeccd6d9

{
  "data": {
    "id": "d3e41c33-a411-4d21-bbe0-2de3eb93eb8f",
    "name": "Docs Example Pvt Ltd b98e2392",
    "legal_name": null,
    "registration_number": null,
    "subdomain": null,
    "contact": {
      "email": null,
      "phone": null,
      "website": null
    },
    "address": {
      "line1": null,
      "line2": null,
      "city": null,
      "state": null,
      "postal_code": null,
      "country_code": null
    },
    "industry_code": null,
    "company_size": null,
    "country_code": "IN",
    "currency": "INR",
    "timezone": "Asia/Kolkata",
    "locale": {
      "language_code": "en-IN",
      "date_format": "DD/MM/YYYY"
    },
    "fiscal_year": {
      "start_month": 4
    },
    "working_days": [
      {
        "day": "MON",
        "is_working": true,
        "is_alternate": false
      },
      {
        "day": "TUE",
        "is_working": true,
        "is_alternate": false
      },
      {
        "day": "WED",
        "is_working": true,
        "is_alternate": false
      },
      {
        "day": "THU",
        "is_working": true,
        "is_alternate": false
      },
      {
        "day": "FRI",
        "is_working": true,
        "is_alternate": false
      },
      {
        "day": "SAT",
        "is_working": false,
        "is_alternate": false
      },
      {
        "day": "SUN",
        "is_working": false,
        "is_alternate": false
      }
    ],
    "business_hours": null,
    "branding": {
      "logo_url": null,
      "theme": null
    },
    "status": "TRIAL",
    "primary_legal_entity": null,
    "onboarded_at": null,
    "trial_ends_at": "2026-11-07T16:58:40.123512Z",
    "version": 1
  },
  "meta": {
    "request_id": "7c4e00c5-e3a2-4863-a974-25a6aeccd6d9",
    "server_time": "2026-10-24T16:58:41.005525Z"
  }
}
```

### PATCH with a stale `If-Match` -> 409

```http
PATCH /v1/companies/current
Authorization: Bearer <access_token>
If-Match: 6
Content-Type: application/json

{
  "name": "Renamed"
}
```

**Response `409`**

```http
content-type: application/json
x-request-id: 4d037129-7abc-4063-b286-4a1fff40df9a

{
  "error": {
    "code": "STALE_RESOURCE",
    "message": "The company profile has been modified by another request",
    "details": [
      {
        "field": "version",
        "code": "STALE_RESOURCE",
        "message": "The company profile has been modified by another request",
        "context": {
          "current": {
            "id": "d3e41c33-a411-4d21-bbe0-2de3eb93eb8f",
            "name": "Docs Example Pvt Ltd b98e2392",
            "legal_name": null,
            "registration_number": null,
            "subdomain": null,
            "contact": {
              "email": null,
              "phone": null,
              "website": null
            },
            "address": {
              "line1": null,
              "line2": null,
              "city": null,
              "state": null,
              "postal_code": null,
              "country_code": null
            },
            "industry_code": null,
            "company_size": null,
            "country_code": "IN",
            "currency": "INR",
            "timezone": "Asia/Kolkata",
            "locale": {
              "language_code": "en-IN",
              "date_format": "DD/MM/YYYY"
            },
            "fiscal_year": {
              "start_month": 4
            },
            "working_days": [
              {
                "day": "MON",
                "is_working": true,
                "is_alternate": false
              },
              {
                "day": "TUE",
                "is_working": true,
                "is_alternate": false
              },
              {
                "day": "WED",
                "is_working": true,
                "is_alternate": false
              },
              {
                "day": "THU",
                "is_working": true,
                "is_alternate": false
              },
              {
                "day": "FRI",
                "is_working": true,
                "is_alternate": false
              },
              {
                "day": "SAT",
                "is_working": false,
                "is_alternate": false
              },
              {
                "day": "SUN",
                "is_working": false,
                "is_alternate": false
              }
            ],
            "business_hours": null,
            "branding": {
              "logo_url": null,
              "theme": null
            },
            "status": "TRIAL",
            "primary_legal_entity": null,
            "onboarded_at": null,
            "trial_ends_at": "2026-11-07T16:58:40.123512Z",
            "version": 1
          }
        }
      }
    ],
    "request_id": "4d037129-7abc-4063-b286-4a1fff40df9a",
    "documentation_url": null
  }
}
```

### PATCH with the current `If-Match`

```http
PATCH /v1/companies/current
Authorization: Bearer <access_token>
If-Match: 1
Content-Type: application/json

{
  "name": "Docs Example Pvt Ltd b98e2392"
}
```

**Response `200`**

```http
content-type: application/json
x-request-id: dc4ec4b2-59e7-4f78-9474-ea4166d43f43

{
  "data": {
    "id": "d3e41c33-a411-4d21-bbe0-2de3eb93eb8f",
    "name": "Docs Example Pvt Ltd b98e2392",
    "legal_name": null,
    "registration_number": null,
    "subdomain": null,
    "contact": {
      "email": null,
      "phone": null,
      "website": null
    },
    "address": {
      "line1": null,
      "line2": null,
      "city": null,
      "state": null,
      "postal_code": null,
      "country_code": null
    },
    "industry_code": null,
    "company_size": null,
    "country_code": "IN",
    "currency": "INR",
    "timezone": "Asia/Kolkata",
    "locale": {
      "language_code": "en-IN",
      "date_format": "DD/MM/YYYY"
    },
    "fiscal_year": {
      "start_month": 4
    },
    "working_days": [
      {
        "day": "MON",
        "is_working": true,
        "is_alternate": false
      },
      {
        "day": "TUE",
        "is_working": true,
        "is_alternate": false
      },
      {
        "day": "WED",
        "is_working": true,
        "is_alternate": false
      },
      {
        "day": "THU",
        "is_working": true,
        "is_alternate": false
      },
      {
        "day": "FRI",
        "is_working": true,
        "is_alternate": false
      },
      {
        "day": "SAT",
        "is_working": false,
        "is_alternate": false
      },
      {
        "day": "SUN",
        "is_working": false,
        "is_alternate": false
      }
    ],
    "business_hours": null,
    "branding": {
      "logo_url": null,
      "theme": null
    },
    "status": "TRIAL",
    "primary_legal_entity": null,
    "onboarded_at": null,
    "trial_ends_at": "2026-11-07T16:58:40.123512Z",
    "version": 2
  },
  "meta": {
    "request_id": "dc4ec4b2-59e7-4f78-9474-ea4166d43f43",
    "server_time": "2026-10-24T16:58:41.018070Z"
  }
}
```

### Self-service punch by a user with no employee record -> 422

The company admin created at registration has no linked `Employee`, so `employee_id` in the token is null.

```http
POST /v1/attendance/punches/me
Authorization: Bearer <access_token>
Content-Type: application/json

{
  "direction": "IN"
}
```

**Response `422`**

```http
content-type: application/json
x-request-id: 7518f12a-2600-49d8-bb8a-c41d0c1b97c1

{
  "error": {
    "code": "VALIDATION_ERROR",
    "message": "The caller has no linked employee record \u2014 use the on-behalf endpoint instead",
    "details": [],
    "request_id": "7518f12a-2600-49d8-bb8a-c41d0c1b97c1",
    "documentation_url": null
  }
}
```

### `Idempotency-Key` missing -> 422

```http
POST /v1/leave-applications
Authorization: Bearer <access_token>
Content-Type: application/json

{
  "leave_type_id": "1e8f1e42-68f3-4cdd-9a4f-6af3ef2bef06",
  "start_date": "2026-02-02",
  "end_date": "2026-02-02"
}
```

**Response `422`**

```http
content-type: application/json
x-request-id: 57b4432d-7d9c-4909-b831-52918bbd9057

{
  "error": {
    "code": "IDEMPOTENCY_KEY_REQUIRED",
    "message": "The Idempotency-Key header is required for this request",
    "details": [
      {
        "field": "Idempotency-Key",
        "code": "IDEMPOTENCY_KEY_REQUIRED",
        "message": "Send a unique Idempotency-Key header",
        "context": null
      }
    ],
    "request_id": "57b4432d-7d9c-4909-b831-52918bbd9057",
    "documentation_url": null
  }
}
```

### Unknown route -> 404 envelope

```http
GET /v1/does-not-exist
Authorization: Bearer <access_token>
```

**Response `404`**

```http
content-type: application/json
x-request-id: 8ec28edf-5eaf-4786-8938-fc19693e0658

{
  "error": {
    "code": "NOT_FOUND",
    "message": "Not Found",
    "details": [],
    "request_id": "8ec28edf-5eaf-4786-8938-fc19693e0658",
    "documentation_url": null
  }
}
```
