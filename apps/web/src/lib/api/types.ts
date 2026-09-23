/** Shared response envelope shapes — mirrors `apps/api/src/hrms/shared/pagination.py` and
 * `core/errors/envelope.py`. Kept in one place so every API integration speaks the same shape. */

export interface ResponseMeta {
  request_id: string;
  server_time?: string | null;
}

export interface DataEnvelope<T> {
  data: T;
  meta: ResponseMeta;
}

/** API-01 pagination contract — 1-indexed `page`, server-capped `per_page` (max 100). */
export interface PaginationMeta {
  page: number;
  per_page: number;
  total: number;
  total_pages: number;
  next_cursor?: string | null;
}

export interface ListEnvelope<T> {
  data: T[];
  pagination: PaginationMeta | null;
  meta: ResponseMeta;
}

export interface ErrorDetail {
  field?: string | null;
  code: string;
  message: string;
  context?: Record<string, unknown> | null;
}

export interface ErrorBody {
  code: string;
  message: string;
  details: ErrorDetail[];
  request_id: string;
  documentation_url?: string | null;
}

export interface ErrorEnvelope {
  error: ErrorBody;
}
