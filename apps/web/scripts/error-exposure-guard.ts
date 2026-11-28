/**
 * CI guard: a raw error must not reach a user-facing surface, and a failure must not disappear.
 *
 * Uses the TypeScript compiler (real types, not text search), so it is not fooled by comments,
 * strings, tests, or a variable that merely happens to be called `error`. Run by
 * `src/lib/observability/error-exposure-guard.test.ts` in the existing `vitest` CI step.
 *
 * Rules, for production code under `src/` (test files are not scanned):
 *
 *  W1  `<x>.message` where `x` is an `Error`, `ApiError` or `NetworkError` (or a caught value).
 *      The text an API error carries is safe only because the server made it so; a 5xx has no
 *      support reference unless it goes through `describeApiError` / `describeError`, and a
 *      non-API `Error` (a `TypeError`, a library failure) must never be shown at all.
 *  W2  A silent failure: an empty `catch` block, or `.catch(...)` given a handler that does
 *      nothing (`() => {}`, `() => null`, `() => undefined`). Use `reportHandledError` /
 *      `reportedFallback`, which keep the UI quiet but tell the developer.
 *  W3  `console.error` / `console.warn` outside the allowlist: nothing in production writes to the
 *      browser console, so a failure logged there is a failure nobody sees.
 *  W4  A caught value or `Error` interpolated into a template string or passed to `String(...)`.
 *
 * Every exception is listed in ALLOWLIST with the reason. An entry that no longer matches fails
 * the run, so the list cannot rot.
 */
import fs from "node:fs";
import path from "node:path";
import ts from "typescript";

export interface Violation {
  file: string;
  line: number;
  rule: "W1" | "W2" | "W3" | "W4";
  text: string;
}

export interface Allowed {
  file: string;
  rule: Violation["rule"];
  /** Source text of the flagged node, exactly as written. */
  text: string;
  reason: string;
}

const STATUS_GATED =
  "Only reached for an ApiError with a 4xx status the server answers with a written business " +
  "message (checked on the line above); a 5xx never gets here.";

export const ALLOWLIST: Allowed[] = [
  {
    file: "src/app/app/users/page.tsx",
    rule: "W1",
    text: "err.message",
    reason: `409 conflict toast and 409/422 invite error. ${STATUS_GATED}`,
  },
  {
    file: "src/app/app/weekly-off-patterns/page.tsx",
    rule: "W1",
    text: "err.message",
    reason: "Shown only when the code is WEEKLY_OFF_RULE_INVALID, a 422 with a written sentence.",
  },
  {
    file: "src/app/app/payroll/salary-structures/page.tsx",
    rule: "W1",
    text: "err.message",
    reason: `409/422 on a duplicate structure code. ${STATUS_GATED}`,
  },
  {
    file: "src/app/app/company/page.tsx",
    rule: "W1",
    text: "err.message",
    reason: "Stale-resource (409/412) notice: 'changed by someone else'. " + STATUS_GATED,
  },
  {
    file: "src/components/onboarding/wizard/document-upload-step.tsx",
    rule: "W1",
    text: "err.message",
    reason: `422 file-validation message (type/size). ${STATUS_GATED}`,
  },
  {
    file: "src/components/employee/document-panel.tsx",
    rule: "W1",
    text: "err.message",
    reason: `422 file-validation message (type/size). ${STATUS_GATED}`,
  },
  {
    file: "src/lib/api/errors.ts",
    rule: "W1",
    text: "error.message",
    reason: "The central helper: the one place an ApiError's text is read, adding the reference.",
  },
  {
    file: "src/components/common/route-error.tsx",
    rule: "W1",
    text: "error.message",
    reason: "Route boundary: shown only when isApiError(error); anything else gets a fixed line.",
  },
  {
    file: "src/components/common/route-error.tsx",
    rule: "W3",
    text: "console.error(error)",
    reason: "Development only (guarded by NODE_ENV !== 'production'); production reports instead.",
  },
  {
    file: "src/components/shift-roster/roster-context.tsx",
    rule: "W2",
    text: "The address bar is a convenience",
    reason: "Writing the view to the address bar can be refused by the browser; the in-memory state is what the views read, so nothing is lost.",
  },
  {
    file: "src/components/shift-roster/roster-nav.tsx",
    rule: "W2",
    text: "Storage can be blocked",
    reason: "Reading a remembered view from localStorage can be blocked (private mode); the default view is used.",
  },
  {
    file: "src/components/shift-roster/roster-nav.tsx",
    rule: "W2",
    text: "Remembering the view is a convenience only",
    reason: "Writing the remembered view to localStorage can be blocked; nothing depends on it.",
  },
  {
    file: "src/app/login/page.tsx",
    rule: "W2",
    text: "Not remembered",
    reason: "Remembering the email field in localStorage is a convenience; blocked storage just leaves it empty.",
  },
  {
    file: "src/components/company/welcome-setup-dialog.tsx",
    rule: "W2",
    text: "the dialog just may show again",
    reason: "Marking the welcome dialog as seen in localStorage; blocked storage means it may show again.",
  },
  {
    file: "src/lib/api/client.ts",
    rule: "W2",
    text: "No JSON body",
    reason: "A non-JSON error body (a proxy page) is expected; the client falls through to the fixed generic message and still carries the request id.",
  },
  {
    file: "src/lib/platform/api.ts",
    rule: "W2",
    text: "storage unavailable",
    reason: "Clearing the platform admin session from sessionStorage; if storage is unavailable there is nothing stored to clear.",
  },
  {
    file: "src/lib/platform/api.ts",
    rule: "W2",
    text: "no JSON body (proxy error)",
    reason: "A non-JSON error body (a proxy page) is expected; the client falls through to a fixed generic message.",
  },
  {
    file: "src/lib/observability/report-client-error.ts",
    rule: "W2",
    text: "() => undefined",
    reason: "The reporter itself: a failed report must never raise or recurse into reporting.",
  },
  {
    file: "src/lib/observability/report-client-error.ts",
    rule: "W2",
    text: "Reporting must never throw into the page it is trying to describe.",
    reason: "The reporter itself: a failure to report must never break the page.",
  },
];

const ERROR_TYPE_NAMES = new Set([
  "Error",
  "ApiError",
  "NetworkError",
  "TypeError",
  "RangeError",
  "SyntaxError",
  "DOMException",
]);
const EMPTY_VALUES = new Set(["null", "undefined", "false", "0", "[]"]);

export function check(
  program: ts.Program,
  root: string,
  include: (file: string) => boolean,
): Violation[] {
  const checker = program.getTypeChecker();
  const found: Violation[] = [];

  const isErrorLike = (node: ts.Expression): boolean => {
    const type = checker.getTypeAtLocation(node);
    const parts = type.isUnion() ? type.types : [type];
    return parts.some((part) => ERROR_TYPE_NAMES.has(checker.typeToString(part)));
  };

  const isCaughtValue = (node: ts.Expression): boolean => {
    if (!ts.isIdentifier(node)) return false;
    const symbol = checker.getSymbolAtLocation(node);
    const decl = symbol?.valueDeclaration;
    return (
      !!decl &&
      ts.isVariableDeclaration(decl) &&
      !!decl.parent &&
      ts.isCatchClause(decl.parent)
    );
  };

  const isSilentHandler = (arg: ts.Expression): boolean => {
    if (!ts.isArrowFunction(arg) && !ts.isFunctionExpression(arg)) return false;
    const body = arg.body;
    if (ts.isBlock(body)) return body.statements.length === 0;
    return EMPTY_VALUES.has(body.getText());
  };

  const add = (sf: ts.SourceFile, node: ts.Node, rule: Violation["rule"]) => {
    found.push({
      file: path.relative(root, sf.fileName).split(path.sep).join("/"),
      line: sf.getLineAndCharacterOfPosition(node.getStart()).line + 1,
      rule,
      text: node.getText(),
    });
  };

  for (const sf of program.getSourceFiles()) {
    if (!include(sf.fileName)) continue;
    const visit = (node: ts.Node): void => {
      if (ts.isPropertyAccessExpression(node) && node.name.text === "message") {
        const target = node.expression;
        if (isErrorLike(target) || isCaughtValue(target)) add(sf, node, "W1");
      }
      if (ts.isCatchClause(node) && node.block.statements.length === 0) add(sf, node, "W2");
      if (
        ts.isCallExpression(node) &&
        ts.isPropertyAccessExpression(node.expression) &&
        node.expression.name.text === "catch" &&
        node.arguments.length === 1 &&
        node.arguments[0] &&
        isSilentHandler(node.arguments[0])
      ) {
        add(sf, node.arguments[0], "W2");
      }
      if (
        ts.isCallExpression(node) &&
        ts.isPropertyAccessExpression(node.expression) &&
        ts.isIdentifier(node.expression.expression) &&
        node.expression.expression.text === "console" &&
        ["error", "warn"].includes(node.expression.name.text)
      ) {
        add(sf, node, "W3");
      }
      if (ts.isTemplateSpan(node) && (isErrorLike(node.expression) || isCaughtValue(node.expression))) {
        add(sf, node.expression, "W4");
      }
      if (
        ts.isCallExpression(node) &&
        ts.isIdentifier(node.expression) &&
        node.expression.text === "String" &&
        node.arguments[0] &&
        (isErrorLike(node.arguments[0]) || isCaughtValue(node.arguments[0]))
      ) {
        add(sf, node, "W4");
      }
      ts.forEachChild(node, visit);
    };
    visit(sf);
  }
  return found;
}

export function applyAllowlist(
  violations: Violation[],
  allowlist: Allowed[] = ALLOWLIST,
): { remaining: Violation[]; stale: Allowed[] } {
  const used = new Set<Allowed>();
  const remaining = violations.filter((v) => {
    const match = allowlist.find(
      (a) =>
        a.file === v.file &&
        a.rule === v.rule &&
        // A catch block is matched by the distinctive comment it carries; everything else exactly.
        (a.rule === "W2" ? v.text.includes(a.text) : a.text === v.text),
    );
    if (match) used.add(match);
    return !match;
  });
  return { remaining, stale: allowlist.filter((a) => !used.has(a)) };
}

/** The production program: every non-test file under `src/`, with the project's compiler options. */
export function loadProgram(webRoot: string): ts.Program {
  const configPath = path.join(webRoot, "tsconfig.json");
  const config = ts.readConfigFile(configPath, ts.sys.readFile);
  const parsed = ts.parseJsonConfigFileContent(config.config, ts.sys, webRoot);
  const files = parsed.fileNames.filter(
    (f) => !fs.existsSync(f) || /\.(ts|tsx)$/.test(f),
  );
  return ts.createProgram(files, { ...parsed.options, noEmit: true });
}

export function isProductionSource(webRoot: string): (file: string) => boolean {
  const src = path.join(webRoot, "src") + path.sep;
  return (file) =>
    file.startsWith(src) &&
    !/\.test\.(ts|tsx)$/.test(file) &&
    !file.includes(`${path.sep}__tests__${path.sep}`) &&
    !file.endsWith(".d.ts");
}
