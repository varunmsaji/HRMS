from hrms.core.db.models.identity import Company

# Column names from docs/modules/company/03_Database_Design.md §2.1 (existing columns).
EXPECTED_COMPANY_COLUMNS = {
    "id",
    "name",
    "legal_name",
    "subdomain",
    "industry_code",
    "country_code",
    "currency",
    "timezone",
    "fy_start_month",
    "logo_url",
    "theme_json",
    "status",
    "onboarded_at",
    "trial_ends_at",
    "data_region",
    "created_at",
    "updated_at",
    "deleted_at",
    "version",
}


def test_company_table_has_all_documented_columns() -> None:
    actual_columns = {column.name for column in Company.__table__.columns}
    assert EXPECTED_COMPANY_COLUMNS <= actual_columns
