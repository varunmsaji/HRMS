# Data models - employee_import

Generated from the Pydantic/OpenAPI schemas. `Required` = present in the schema's `required` list (for *Read* models this means the server always sends it). `Nullable` = schema allows `null`. "Server-generated" lists fields that appear on a `*Read` model but not on its `*Create`/`*Update` counterpart (derived by name match - an inference, not a declared flag).

## EmployeeImportBatchRead
<a id="employeeimportbatchread"></a>

| Field | Required | Type | Nullable | Constraints / default | Description |
|---|---|---|---|---|---|
| `id` | yes | string(uuid) | no | - | - |
| `company_id` | yes | string(uuid) | no | - | - |
| `status` | yes | string | no | - | - |
| `original_filename` | yes | string | no | - | - |
| `total_rows` | yes | integer | no | - | - |
| `processed_rows` | yes | integer | no | - | - |
| `success_count` | yes | integer | no | - | - |
| `error_count` | yes | integer | no | - | - |
| `started_at` | yes | string | yes | - | - |
| `completed_at` | yes | string | yes | - | - |
| `created_at` | yes | string | no | - | - |
| `updated_at` | yes | string | no | - | - |

## EmployeeImportRowErrorRead
<a id="employeeimportrowerrorread"></a>

| Field | Required | Type | Nullable | Constraints / default | Description |
|---|---|---|---|---|---|
| `id` | yes | string(uuid) | no | - | - |
| `row_number` | yes | integer | no | - | - |
| `raw_row` | yes | map&lt;string, string&gt; | no | - | - |
| `error_code` | yes | string | no | - | - |
| `error_message` | yes | string | no | - | - |

