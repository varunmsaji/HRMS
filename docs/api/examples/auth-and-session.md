# Authentication & session - recorded exchanges

> **Recorded, not synthesized.** Produced by [`../tools/record_examples.py`](../tools/record_examples.py) against a local API (`ENVIRONMENT=development`, isolated `hrms_test` database, `COMPANY_APPROVAL_REQUIRED=false`, `EMAIL_PROVIDER=logging`) on 2026-10-24. Access tokens, refresh cookies and one-time email tokens are redacted; all other values are verbatim. The throwaway password in these files is a documentation-only value.

### Registration config (public)

```http
GET /v1/companies/registration-config
```

**Response `200`**

```http
content-type: application/json
x-request-id: e044eb6f-6319-4288-875f-600b6beb57b8

{
  "data": {
    "allowed_company_timezones": [
      "Asia/Kolkata"
    ]
  },
  "meta": {
    "request_id": "e044eb6f-6319-4288-875f-600b6beb57b8",
    "server_time": "2026-10-24T16:58:40.084796Z"
  }
}
```

### Register a company (public) - issues the first session

The response body has no refresh token; it arrives in the `Set-Cookie: hrms_refresh=<refresh-token> header (Path=/v1/auth, HttpOnly).

```http
POST /v1/companies/register
Content-Type: application/json

{
  "name": "Docs Example Pvt Ltd b98e2392",
  "country_code": "IN",
  "currency": "INR",
  "timezone": "Asia/Kolkata",
  "fy_start_month": 4,
  "admin_first_name": "Asha",
  "admin_last_name": "Verma",
  "admin_email": "docs.admin.b98e2392@example.com",
  "admin_password": "Docs-Example-Pass1"
}
```

**Response `201`**

```http
content-type: application/json
set-cookie: hrms_refresh=<refresh-token>; HttpOnly; Max-Age=2592000; Path=/v1/auth; SameSite=lax
x-request-id: d530f32d-6035-45d6-a41a-ebecf0274f02

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
    "request_id": "d530f32d-6035-45d6-a41a-ebecf0274f02",
    "server_time": "2026-10-24T16:58:40.218975Z"
  }
}
```

### Current user (`/auth/me`)

```http
GET /v1/auth/me
Authorization: Bearer <access_token>
```

**Response `200`**

```http
content-type: application/json
x-request-id: 896b1d78-857d-4ddb-b218-19054e4e5563

{
  "data": {
    "user": {
      "id": "c2810364-5e96-4e49-8d94-1df6f45db78a",
      "email": "docs.admin.b98e2392@example.com",
      "company_id": "d3e41c33-a411-4d21-bbe0-2de3eb93eb8f",
      "employee_id": null,
      "permissions": [
        "ATTENDANCE.FACE_ENROLLMENT_MANAGE",
        "ATTENDANCE.LEAVE_PROJECTION_SYNC",
        "ATTENDANCE.LOCK",
        "ATTENDANCE.OVERTIME_APPROVE",
        "ATTENDANCE.POLICY_MANAGE",
        "ATTENDANCE.PUNCH",
        "ATTENDANCE.PUNCH_ON_BEHALF",
        "ATTENDANCE.RECOMPUTE",
        "ATTENDANCE.REGULARIZATION_APPROVE",
        "ATTENDANCE.REGULARIZATION_REQUEST",
        "ATTENDANCE.REGULARIZATION_REQUEST_ON_BEHALF",
        "ATTENDANCE.ROSTER_MANAGE",
        "ATTENDANCE.UNLOCK",
        "ATTENDANCE.VIEW",
        "ATTENDANCE.VIEW_ALL",
        "DASHBOARD.COMPANY.VIEW",
        "EMPLOYEE.BULK_IMPORT",
        "EMPLOYEE.CONFIRM",
        "EMPLOYEE.CREATE",
        "EMPLOYEE.DEACTIVATE",
        "EMPLOYEE.INVITE",
        "EMPLOYEE.PROMOTE",
        "EMPLOYEE.TERMINATE",
        "EMPLOYEE.TRANSFER",
        "EMPLOYEE.UPDATE",
        "EMPLOYEE.UPDATE_COMPENSATION",
        "EMPLOYEE.UPDATE_SENSITIVE",
        "EMPLOYEE.VIEW",
        "EMPLOYEE.VIEW_ALL",
        "EMPLOYEE.VIEW_BANKING",
        "EMPLOYEE.VIEW_COMPENSATION",
        "EMPLOYEE.VIEW_DOCUMENTS",
        "EMPLOYEE.VIEW_EXPERIENCE",
        "EMPLOYEE.VIEW_NOMINEE",
        "EMPLOYEE.VIEW_SENSITIVE",
        "EMPLOYEE.VIEW_STATUTORY",
        "LEAVE.APPLICATION_APPROVE",
        "LEAVE.APPLICATION_CANCEL_APPROVED",
        "LEAVE.APPLICATION_REASSIGN",
        "LEAVE.APPLICATION_SUBMIT",
        "LEAVE.APPLICATION_SUBMIT_ON_BEHALF",
        "LEAVE.BALANCE_ADJUST",
        "LEAVE.BALANCE_VIEW",
        "LEAVE.BALANCE_VIEW_ALL",
        "LEAVE.COMBINATION_RULE_MANAGE",
        "LEAVE.POLICY_MANAGE",
        "LEAVE.STATUTORY_MINIMUM_MANAGE",
        "LEAVE.TYPE_MANAGE",
        "LEAVE.YEAR_SETTING_MANAGE",
        "ONBOARDING.ACTIVATE",
        "ONBOARDING.CANCEL",
        "ONBOARDING.CREATE",
        "ONBOARDING.REVIEW",
        "ONBOARDING.VIEW",
        "ORG.BRANCH.MANAGE",
        "ORG.CALENDAR.MANAGE",
        "ORG.COMPANY.MANAGE",
        "ORG.DEPARTMENT.MANAGE",
        "ORG.DESIGNATION.MANAGE",
        "ORG.GRADE.MANAGE",
        "ORG.HOLIDAY.MANAGE",
        "ORG.LEGAL_ENTITY.MANAGE",
        "ORG.SHIFT.MANAGE",
        "PAYROLL.BANK_ADVICE_DOWNLOAD",
        "PAYROLL.PAYSLIP_VIEW_OWN",
        "PAYROLL.RUN_APPROVE",
        "PAYROLL.RUN_PROCESS",
        "PAYROLL.RUN_VIEW",
        "PAYROLL.SETUP_MANAGE",
        "PAYROLL.STATUTORY_MANAGE",
        "SETTINGS.ROLE.MANAGE",
        "SETTINGS.USER.MANAGE"
      ],
      "company_timezone": "Asia/Kolkata",
      "company_status": "TRIAL"
    }
  },
  "meta": {
    "request_id": "896b1d78-857d-4ddb-b218-19054e4e5563",
    "server_time": "2026-10-24T16:58:40.228818Z"
  }
}
```

### Login before verifying the email -> 403

Registration issues a session without verification, but a later *login* is refused until the email is verified.

```http
POST /v1/auth/login
Content-Type: application/json

{
  "email": "docs.admin.b98e2392@example.com",
  "password": "Docs-Example-Pass1"
}
```

**Response `403`**

```http
content-type: application/json
x-request-id: 9c9be398-95f7-48a8-ac07-16b8537343e3

{
  "error": {
    "code": "EMAIL_NOT_VERIFIED",
    "message": "Please verify your email address before signing in",
    "details": [],
    "request_id": "9c9be398-95f7-48a8-ac07-16b8537343e3",
    "documentation_url": null
  }
}
```

### Verify email (token redacted)

The real token was read from the server log (EMAIL_PROVIDER=logging) and is redacted below.

```http
POST /v1/auth/email/verify
Content-Type: application/json

{
  "token": "<one-time-token>"
}
```

**Response `200`**

```http
content-type: application/json
x-request-id: ea30906b-6bba-41db-9102-8a674efa8c81

{
  "data": {
    "verified": true
  },
  "meta": {
    "request_id": "ea30906b-6bba-41db-9102-8a674efa8c81",
    "server_time": "2026-10-24T16:58:40.277814Z"
  }
}
```

### Verify the same token again -> 401

```http
POST /v1/auth/email/verify
Content-Type: application/json

{
  "token": "<one-time-token>"
}
```

**Response `401`**

```http
www-authenticate: Bearer
content-type: application/json
x-request-id: 99ae67ec-5241-48ed-ba1d-26e532518ef9

{
  "error": {
    "code": "INVALID_TOKEN",
    "message": "This verification link is invalid or has expired",
    "details": [],
    "request_id": "99ae67ec-5241-48ed-ba1d-26e532518ef9",
    "documentation_url": null
  }
}
```

### Resend verification (always 202)

Same 202 whether or not the address exists (anti-enumeration).

```http
POST /v1/auth/email/resend-verification
Content-Type: application/json

{
  "email": "nobody@example.com"
}
```

**Response `202`**

```http
content-type: application/json
x-request-id: 1382f5cb-0256-4f89-acff-3e42a9428d71

{
  "data": {
    "accepted": true
  },
  "meta": {
    "request_id": "1382f5cb-0256-4f89-acff-3e42a9428d71",
    "server_time": "2026-10-24T16:58:40.281409Z"
  }
}
```

### Forgot password (always 202)

```http
POST /v1/auth/password/forgot
Content-Type: application/json

{
  "email": "nobody@example.com"
}
```

**Response `202`**

```http
content-type: application/json
x-request-id: 92c2c65c-7cec-4710-ba9e-4f8e0438b659

{
  "data": {
    "accepted": true
  },
  "meta": {
    "request_id": "92c2c65c-7cec-4710-ba9e-4f8e0438b659",
    "server_time": "2026-10-24T16:58:40.283179Z"
  }
}
```

### Login with a wrong password -> 401

```http
POST /v1/auth/login
Content-Type: application/json

{
  "email": "docs.admin.b98e2392@example.com",
  "password": "Wrong-Password-1"
}
```

**Response `401`**

```http
www-authenticate: Bearer
content-type: application/json
x-request-id: e39ab531-0303-42e5-b0ff-a51317c62776

{
  "error": {
    "code": "INVALID_CREDENTIALS",
    "message": "Invalid email or password",
    "details": [],
    "request_id": "e39ab531-0303-42e5-b0ff-a51317c62776",
    "documentation_url": null
  }
}
```

### Login (success)

```http
POST /v1/auth/login
Content-Type: application/json

{
  "email": "docs.admin.b98e2392@example.com",
  "password": "Docs-Example-Pass1",
  "company_id": "d3e41c33-a411-4d21-bbe0-2de3eb93eb8f"
}
```

**Response `200`**

```http
content-type: application/json
set-cookie: hrms_refresh=<refresh-token>; HttpOnly; Max-Age=2592000; Path=/v1/auth; SameSite=lax
x-request-id: 92898d3b-bbb4-4f56-8ea3-405862900468

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
    "request_id": "92898d3b-bbb4-4f56-8ea3-405862900468",
    "server_time": "2026-10-24T16:58:40.375482Z"
  }
}
```

### Refresh using the cookie (no body)

The cookie jar sends `hrms_refresh` automatically. The previous refresh token is rotated (single use).

```http
POST /v1/auth/token/refresh
```

**Response `200`**

```http
content-type: application/json
set-cookie: hrms_refresh=<refresh-token>; HttpOnly; Max-Age=2592000; Path=/v1/auth; SameSite=lax
x-request-id: 5b8fbd6e-d2a8-48aa-a4e0-310d981b9935

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
    "request_id": "5b8fbd6e-d2a8-48aa-a4e0-310d981b9935",
    "server_time": "2026-10-24T16:58:40.382727Z"
  }
}
```

### Replay the rotated refresh token explicitly -> 401 and the family is revoked

Reuse detection: this revokes the whole token family and its session, so the newest cookie stops working too.

```http
POST /v1/auth/token/refresh
Content-Type: application/json

{
  "refresh_token": "<refresh-token>"
}
```

**Response `401`**

```http
www-authenticate: Bearer
content-type: application/json
x-request-id: ad304ac1-0ded-4272-a2a9-b5c9b106f76a

{
  "error": {
    "code": "INVALID_TOKEN",
    "message": "Refresh token has been revoked",
    "details": [],
    "request_id": "ad304ac1-0ded-4272-a2a9-b5c9b106f76a",
    "documentation_url": null
  }
}
```

### Refresh with the (now revoked) newest cookie -> 401

```http
POST /v1/auth/token/refresh
```

**Response `401`**

```http
www-authenticate: Bearer
content-type: application/json
x-request-id: ad847f2c-e538-418e-abb2-58ac1cc8344b

{
  "error": {
    "code": "INVALID_TOKEN",
    "message": "Refresh token has been revoked",
    "details": [],
    "request_id": "ad847f2c-e538-418e-abb2-58ac1cc8344b",
    "documentation_url": null
  }
}
```

### Access token of the revoked session -> 401

Revoking the session also invalidates the still-unexpired access token (checked on every request).

```http
GET /v1/auth/me
Authorization: Bearer <access_token>
```

**Response `401`**

```http
www-authenticate: Bearer
content-type: application/json
x-request-id: 28a880d1-23cc-49c3-aa05-217c728fcae4

{
  "error": {
    "code": "INVALID_TOKEN",
    "message": "Session is no longer valid",
    "details": [],
    "request_id": "28a880d1-23cc-49c3-aa05-217c728fcae4",
    "documentation_url": null
  }
}
```

### Login again

```http
POST /v1/auth/login
Content-Type: application/json

{
  "email": "docs.admin.b98e2392@example.com",
  "password": "Docs-Example-Pass1"
}
```

**Response `200`**

```http
content-type: application/json
set-cookie: hrms_refresh=<refresh-token>; HttpOnly; Max-Age=2592000; Path=/v1/auth; SameSite=lax
x-request-id: f0c26f73-7f26-4ae9-b883-230222fbff27

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
    "request_id": "f0c26f73-7f26-4ae9-b883-230222fbff27",
    "server_time": "2026-10-24T16:58:40.437953Z"
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

### Wrong method -> 405 envelope

```http
DELETE /v1/auth/login
```

**Response `405`**

```http
content-type: application/json
x-request-id: a29dfd43-5ab2-4246-a148-e6b6727bfd0c

{
  "error": {
    "code": "METHOD_NOT_ALLOWED",
    "message": "Method Not Allowed",
    "details": [],
    "request_id": "a29dfd43-5ab2-4246-a148-e6b6727bfd0c",
    "documentation_url": null
  }
}
```

### Logout -> 204

```http
POST /v1/auth/logout
Authorization: Bearer <access_token>
```

**Response `204`**

```http
content-type: application/json
set-cookie: hrms_refresh=""; expires=Sat, 24 Oct 2026 16:58:41 GMT; Max-Age=0; Path=/v1/auth; SameSite=lax
x-request-id: 7b4ba0f9-fb7e-4864-9eca-514a76455e33

(empty body)
```

### Use the access token after logout -> 401

```http
GET /v1/auth/me
Authorization: Bearer <access_token>
```

**Response `401`**

```http
www-authenticate: Bearer
content-type: application/json
x-request-id: 0a6b8eee-3818-4d6e-9611-ac872594e5f7

{
  "error": {
    "code": "INVALID_TOKEN",
    "message": "Session is no longer valid",
    "details": [],
    "request_id": "0a6b8eee-3818-4d6e-9611-ac872594e5f7",
    "documentation_url": null
  }
}
```

### Register a second company (for the lockout demo)

```http
POST /v1/companies/register
Content-Type: application/json

{
  "name": "Docs Lock Ltd b98e2392",
  "admin_first_name": "Lock",
  "admin_last_name": "Test",
  "admin_email": "docs.lock.b98e2392@example.com",
  "admin_password": "Docs-Example-Pass1"
}
```

**Response `201`**

```http
content-type: application/json
set-cookie: hrms_refresh=<refresh-token>; HttpOnly; Max-Age=2592000; Path=/v1/auth; SameSite=lax
x-request-id: a292dea6-f50f-4bdc-9c49-4e063b7b3b9c

{
  "data": {
    "access_token": "<jwt-access-token>",
    "token_type": "Bearer",
    "expires_in_minutes": 15,
    "company_id": "fc64cb6b-0817-4827-b46c-d81621274cb4",
    "companies": [
      {
        "id": "fc64cb6b-0817-4827-b46c-d81621274cb4",
        "name": "Docs Lock Ltd b98e2392",
        "is_primary": true
      }
    ]
  },
  "meta": {
    "request_id": "a292dea6-f50f-4bdc-9c49-4e063b7b3b9c",
    "server_time": "2026-10-24T16:59:43.137790Z"
  }
}
```

### Wrong password #1 (lockout after 5)

```http
POST /v1/auth/login
Content-Type: application/json

{
  "email": "docs.lock.b98e2392@example.com",
  "password": "Wrong-Password-1"
}
```

**Response `401`**

```http
www-authenticate: Bearer
content-type: application/json
x-request-id: 1bc8adcb-6d17-480f-a153-7d59dd12fc77

{
  "error": {
    "code": "INVALID_CREDENTIALS",
    "message": "Invalid email or password",
    "details": [],
    "request_id": "1bc8adcb-6d17-480f-a153-7d59dd12fc77",
    "documentation_url": null
  }
}
```

### Wrong password #2 (lockout after 5)

```http
POST /v1/auth/login
Content-Type: application/json

{
  "email": "docs.lock.b98e2392@example.com",
  "password": "Wrong-Password-1"
}
```

**Response `401`**

```http
www-authenticate: Bearer
content-type: application/json
x-request-id: ff906218-6152-4baf-a29e-166226affdcf

{
  "error": {
    "code": "INVALID_CREDENTIALS",
    "message": "Invalid email or password",
    "details": [],
    "request_id": "ff906218-6152-4baf-a29e-166226affdcf",
    "documentation_url": null
  }
}
```

### Wrong password #3 (lockout after 5)

```http
POST /v1/auth/login
Content-Type: application/json

{
  "email": "docs.lock.b98e2392@example.com",
  "password": "Wrong-Password-1"
}
```

**Response `401`**

```http
www-authenticate: Bearer
content-type: application/json
x-request-id: 4d470bbb-bc13-4c1c-9cae-8daeb721cafd

{
  "error": {
    "code": "INVALID_CREDENTIALS",
    "message": "Invalid email or password",
    "details": [],
    "request_id": "4d470bbb-bc13-4c1c-9cae-8daeb721cafd",
    "documentation_url": null
  }
}
```

### Wrong password #4 (lockout after 5)

```http
POST /v1/auth/login
Content-Type: application/json

{
  "email": "docs.lock.b98e2392@example.com",
  "password": "Wrong-Password-1"
}
```

**Response `401`**

```http
www-authenticate: Bearer
content-type: application/json
x-request-id: 079f415d-c26d-4db3-a7ca-e6aeba57ac3d

{
  "error": {
    "code": "INVALID_CREDENTIALS",
    "message": "Invalid email or password",
    "details": [],
    "request_id": "079f415d-c26d-4db3-a7ca-e6aeba57ac3d",
    "documentation_url": null
  }
}
```

### Wrong password #5 (lockout after 5)

```http
POST /v1/auth/login
Content-Type: application/json

{
  "email": "docs.lock.b98e2392@example.com",
  "password": "Wrong-Password-1"
}
```

**Response `401`**

```http
www-authenticate: Bearer
content-type: application/json
x-request-id: f9d38270-6ef5-42ad-b021-c18b396e9db4

{
  "error": {
    "code": "INVALID_CREDENTIALS",
    "message": "Invalid email or password",
    "details": [],
    "request_id": "f9d38270-6ef5-42ad-b021-c18b396e9db4",
    "documentation_url": null
  }
}
```

### Wrong password #6 (lockout after 5)

Lockout is checked before the password, so even the correct password is refused with 423 while locked.

```http
POST /v1/auth/login
Content-Type: application/json

{
  "email": "docs.lock.b98e2392@example.com",
  "password": "Wrong-Password-1"
}
```

**Response `423`**

```http
content-type: application/json
x-request-id: 9cbfde5e-7670-440e-ac14-6a01a4c467cb

{
  "error": {
    "code": "ACCOUNT_LOCKED",
    "message": "Account is temporarily locked",
    "details": [],
    "request_id": "9cbfde5e-7670-440e-ac14-6a01a4c467cb",
    "documentation_url": null
  }
}
```

### Correct password while locked -> 423

```http
POST /v1/auth/login
Content-Type: application/json

{
  "email": "docs.lock.b98e2392@example.com",
  "password": "Docs-Example-Pass1"
}
```

**Response `423`**

```http
content-type: application/json
x-request-id: 00f05b3b-a736-4b20-8ebc-ac5605f0c736

{
  "error": {
    "code": "ACCOUNT_LOCKED",
    "message": "Account is temporarily locked",
    "details": [],
    "request_id": "00f05b3b-a736-4b20-8ebc-ac5605f0c736",
    "documentation_url": null
  }
}
```

### Login attempt 1 (rate-limit demo)

```http
POST /v1/auth/login
Content-Type: application/json

{
  "email": "ratelimit.b98e2392@example.com",
  "password": "x"
}
```

**Response `401`**

```http
www-authenticate: Bearer
content-type: application/json
x-request-id: 4fe9f1f9-57e8-4feb-9881-ec4a837c18d8

{
  "error": {
    "code": "INVALID_CREDENTIALS",
    "message": "Invalid email or password",
    "details": [],
    "request_id": "4fe9f1f9-57e8-4feb-9881-ec4a837c18d8",
    "documentation_url": null
  }
}
```

### Login attempt 2 (rate-limit demo)

```http
POST /v1/auth/login
Content-Type: application/json

{
  "email": "ratelimit.b98e2392@example.com",
  "password": "x"
}
```

**Response `401`**

```http
www-authenticate: Bearer
content-type: application/json
x-request-id: 1092d995-afb9-4103-93e7-cf97fa6a466d

{
  "error": {
    "code": "INVALID_CREDENTIALS",
    "message": "Invalid email or password",
    "details": [],
    "request_id": "1092d995-afb9-4103-93e7-cf97fa6a466d",
    "documentation_url": null
  }
}
```

### Login attempt 3 (rate-limit demo)

```http
POST /v1/auth/login
Content-Type: application/json

{
  "email": "ratelimit.b98e2392@example.com",
  "password": "x"
}
```

**Response `401`**

```http
www-authenticate: Bearer
content-type: application/json
x-request-id: cd6d4a3a-f196-460a-b6a6-306cc5606b86

{
  "error": {
    "code": "INVALID_CREDENTIALS",
    "message": "Invalid email or password",
    "details": [],
    "request_id": "cd6d4a3a-f196-460a-b6a6-306cc5606b86",
    "documentation_url": null
  }
}
```

### Login attempt 4 (rate-limit demo)

```http
POST /v1/auth/login
Content-Type: application/json

{
  "email": "ratelimit.b98e2392@example.com",
  "password": "x"
}
```

**Response `401`**

```http
www-authenticate: Bearer
content-type: application/json
x-request-id: fa5c57b9-65db-421d-bb04-2433deac511a

{
  "error": {
    "code": "INVALID_CREDENTIALS",
    "message": "Invalid email or password",
    "details": [],
    "request_id": "fa5c57b9-65db-421d-bb04-2433deac511a",
    "documentation_url": null
  }
}
```

### Login attempt 5 (rate-limit demo)

```http
POST /v1/auth/login
Content-Type: application/json

{
  "email": "ratelimit.b98e2392@example.com",
  "password": "x"
}
```

**Response `401`**

```http
www-authenticate: Bearer
content-type: application/json
x-request-id: 8a0609f7-5944-412a-ad1f-de7b20b90ff5

{
  "error": {
    "code": "INVALID_CREDENTIALS",
    "message": "Invalid email or password",
    "details": [],
    "request_id": "8a0609f7-5944-412a-ad1f-de7b20b90ff5",
    "documentation_url": null
  }
}
```

### Login attempt 6 (rate-limit demo)

```http
POST /v1/auth/login
Content-Type: application/json

{
  "email": "ratelimit.b98e2392@example.com",
  "password": "x"
}
```

**Response `401`**

```http
www-authenticate: Bearer
content-type: application/json
x-request-id: 6d8ee6e9-d18a-42ec-a3d2-cef2fbf4cfbf

{
  "error": {
    "code": "INVALID_CREDENTIALS",
    "message": "Invalid email or password",
    "details": [],
    "request_id": "6d8ee6e9-d18a-42ec-a3d2-cef2fbf4cfbf",
    "documentation_url": null
  }
}
```

### Login attempt 7 (rate-limit demo)

```http
POST /v1/auth/login
Content-Type: application/json

{
  "email": "ratelimit.b98e2392@example.com",
  "password": "x"
}
```

**Response `401`**

```http
www-authenticate: Bearer
content-type: application/json
x-request-id: 7b701de2-782c-4c28-84bd-b5fc8a1e6d12

{
  "error": {
    "code": "INVALID_CREDENTIALS",
    "message": "Invalid email or password",
    "details": [],
    "request_id": "7b701de2-782c-4c28-84bd-b5fc8a1e6d12",
    "documentation_url": null
  }
}
```

### Login attempt 8 (rate-limit demo)

```http
POST /v1/auth/login
Content-Type: application/json

{
  "email": "ratelimit.b98e2392@example.com",
  "password": "x"
}
```

**Response `401`**

```http
www-authenticate: Bearer
content-type: application/json
x-request-id: 3e983fa5-daaf-4b0c-956a-c467ca6bb989

{
  "error": {
    "code": "INVALID_CREDENTIALS",
    "message": "Invalid email or password",
    "details": [],
    "request_id": "3e983fa5-daaf-4b0c-956a-c467ca6bb989",
    "documentation_url": null
  }
}
```

### Login attempt 9 (rate-limit demo)

```http
POST /v1/auth/login
Content-Type: application/json

{
  "email": "ratelimit.b98e2392@example.com",
  "password": "x"
}
```

**Response `401`**

```http
www-authenticate: Bearer
content-type: application/json
x-request-id: bb2d0329-c1d1-4374-8021-330c627a7e86

{
  "error": {
    "code": "INVALID_CREDENTIALS",
    "message": "Invalid email or password",
    "details": [],
    "request_id": "bb2d0329-c1d1-4374-8021-330c627a7e86",
    "documentation_url": null
  }
}
```

### Login attempt 10 (rate-limit demo)

```http
POST /v1/auth/login
Content-Type: application/json

{
  "email": "ratelimit.b98e2392@example.com",
  "password": "x"
}
```

**Response `401`**

```http
www-authenticate: Bearer
content-type: application/json
x-request-id: fbe8c41b-e537-4450-831a-ae010140b672

{
  "error": {
    "code": "INVALID_CREDENTIALS",
    "message": "Invalid email or password",
    "details": [],
    "request_id": "fbe8c41b-e537-4450-831a-ae010140b672",
    "documentation_url": null
  }
}
```

### Login attempt 11 (rate-limit demo)

```http
POST /v1/auth/login
Content-Type: application/json

{
  "email": "ratelimit.b98e2392@example.com",
  "password": "x"
}
```

**Response `429`**

```http
retry-after: 60
content-type: application/json
x-request-id: ed2e6c7a-79a0-445b-a807-9e9e1df2c909

{
  "error": {
    "code": "RATE_LIMITED",
    "message": "Too many requests \u2014 please try again later",
    "details": [],
    "request_id": "ed2e6c7a-79a0-445b-a807-9e9e1df2c909",
    "documentation_url": null
  }
}
```
