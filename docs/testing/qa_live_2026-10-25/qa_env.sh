export ENVIRONMENT=development TZ=UTC
export DATABASE_URL=postgresql://hrms:hrms_dev_password@localhost:5433/hrms_qa_e2e
export MIGRATIONS_DATABASE_URL=$DATABASE_URL
export REDIS_URL=redis://localhost:6380/2
export JWT_ACCESS_SECRET=qa-access-secret-min-16-chars JWT_REFRESH_SECRET=qa-refresh-secret-min-16-chars
export S3_ENDPOINT_URL=http://127.0.0.1:19000 S3_BUCKET_DOCUMENTS=hrms-documents AWS_ACCESS_KEY_ID=qa_minio AWS_SECRET_ACCESS_KEY=qa_minio_password_1
