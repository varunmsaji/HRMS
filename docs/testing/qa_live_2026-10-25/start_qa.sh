#!/bin/bash
# starts the PRIVATE QA api (18000) / worker; never touches dev services
cd /media/varun/varun12/work/staff-spectrum/HRMS/apps/api
SP=/tmp/claude-1000/-media-varun-varun12-work-staff-spectrum-HRMS/cec29e6e-c932-4aa7-a66d-2c17cbbd711a/scratchpad
. $SP/qa_env.sh
export EMAIL_PROVIDER=logging FACE_VERIFICATION_PROVIDER=disabled LOG_TO_FILES=false COMPANY_APPROVAL_REQUIRED=false CELERY_BROKER_URL=redis://localhost:6380/14 CELERY_RESULT_BACKEND=redis://localhost:6380/14 MAX_LEGAL_ENTITIES_PER_COMPANY=0
case "$1" in
 api) nohup .venv/bin/python -m uvicorn entrypoints.api:app --port 18000 --host 127.0.0.1 >> $SP/api.log 2>&1 & ;;
 worker) nohup .venv/bin/python -m celery -A entrypoints.worker worker --loglevel=info --concurrency=2 -n qa-worker@%h >> $SP/worker.log 2>&1 & ;;
esac
