#!/bin/bash
cd /media/varun/varun12/work/staff-spectrum/HRMS/apps/api
SP=/tmp/claude-1000/-media-varun-varun12-work-staff-spectrum-HRMS/cec29e6e-c932-4aa7-a66d-2c17cbbd711a/scratchpad
. $SP/qa_env.sh
export REDIS_URL=redis://127.0.0.1:16399/0 CELERY_BROKER_URL=redis://127.0.0.1:16399/1 CELERY_RESULT_BACKEND=redis://127.0.0.1:16399/1
export S3_ENDPOINT_URL=http://127.0.0.1:19998
export EMAIL_PROVIDER=logging FACE_VERIFICATION_PROVIDER=disabled LOG_TO_FILES=false COMPANY_APPROVAL_REQUIRED=false MAX_LEGAL_ENTITIES_PER_COMPANY=0
nohup .venv/bin/python -m uvicorn entrypoints.api:app --port 18001 --host 127.0.0.1 >> $SP/apiB.log 2>&1 &
