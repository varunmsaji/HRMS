// @vitest-environment node
/**
 * The CI guard `scripts/error-exposure-guard.ts`: it rejects raw error text reaching the UI and
 * silent failures, accepts the safe forms, and the real source tree is clean.
 */
import path from "node:path";
import ts from "typescript";
import { describe, expect, it } from "vitest";

import {
  ALLOWLIST,
  applyAllowlist,
  check,
  isProductionSource,
  loadProgram,
  type Violation,
} from "../../../scripts/error-exposure-guard";

const WEB_ROOT = path.resolve(__dirname, "../../..");

const PRELUDE = `
declare class ApiError extends Error { status: number; code: string; }
declare const toast: (o: { title: string }) => void;
declare function describeApiError(e: unknown): string;
declare function reportHandledError(e: unknown): void;
declare const api: { get(): Promise<string> };
`;

/** Compiles `body` (after a small typed prelude) in memory and runs the guard on it. */
function scanSnippet(body: string): Violation[] {
  const name = "/virtual/src/snippet.ts";
  const text = `${PRELUDE}\n${body}\nexport {};`;
  const options: ts.CompilerOptions = {
    target: ts.ScriptTarget.ES2022,
    lib: ["lib.es2022.d.ts", "lib.dom.d.ts"],
    strict: true,
    noEmit: true,
    types: [],
  };
  const host = ts.createCompilerHost(options);
  const realGet = host.getSourceFile.bind(host);
  host.getSourceFile = (file, lang, ...rest) =>
    file === name ? ts.createSourceFile(file, text, lang, true) : realGet(file, lang, ...rest);
  const realExists = host.fileExists.bind(host);
  host.fileExists = (file) => file === name || realExists(file);
  const program = ts.createProgram([name], options, host);
  return check(program, "/virtual", (file) => file === name).map((v) => ({
    ...v,
    line: v.line - PRELUDE.split("\n").length,
  }));
}

const rules = (body: string) => scanSnippet(body).map((v) => v.rule);

describe("prohibited patterns are rejected", () => {
  it("W1: the message of an ApiError or a plain Error", () => {
    expect(rules("function f(e: ApiError) { return e.message; }")).toEqual(["W1"]);
    expect(rules("function f(e: Error | null) { return e?.message; }")).toEqual(["W1"]);
    expect(rules("try { api.get(); } catch (err) { toast({ title: (err as Error).message }); }")).toEqual(["W1"]);
    expect(rules("try { api.get(); } catch (err: any) { toast({ title: err.message }); }")).toEqual(["W1"]);
  });

  it("W2: empty catch blocks and handlers that do nothing", () => {
    expect(rules("try { api.get(); } catch {}")).toEqual(["W2"]);
    expect(rules("try { api.get(); } catch (e) { /* ignored */ }")).toEqual(["W2"]);
    expect(rules("api.get().catch(() => {});")).toEqual(["W2"]);
    expect(rules("api.get().catch(() => null);")).toEqual(["W2"]);
    expect(rules("api.get().catch(() => undefined);")).toEqual(["W2"]);
  });

  it("W3: console.error and console.warn", () => {
    expect(rules("console.error('x');")).toEqual(["W3"]);
    expect(rules("console.warn('x');")).toEqual(["W3"]);
  });

  it("W4: an error interpolated into text", () => {
    expect(rules("function f(e: Error) { return `failed: ${e}`; }")).toEqual(["W4"]);
    expect(rules("try { api.get(); } catch (e) { toast({ title: String(e) }); }")).toEqual(["W4"]);
  });
});

describe("permitted patterns are accepted", () => {
  it("the safe helpers and reporting", () => {
    expect(rules("function f(e: ApiError) { return describeApiError(e); }")).toEqual([]);
    expect(rules("api.get().catch(reportHandledError);")).toEqual([]);
    expect(rules("api.get().catch((e) => { reportHandledError(e); return null; });")).toEqual([]);
    expect(rules("try { api.get(); } catch (e) { reportHandledError(e); }")).toEqual([]);
  });

  it(".message of things that are not errors", () => {
    expect(rules("function f(issue: { message: string }) { return issue.message; }")).toEqual([]);
    expect(rules("function f(d: { details: { message: string }[] }) { return d.details[0]!.message; }")).toEqual([]);
  });

  it("template strings and String() of ordinary values", () => {
    expect(rules("function f(n: number, s: string) { return `${n} ${s}` + String(n); }")).toEqual([]);
  });

  it("the guard reports the rule and the line", () => {
    const [v] = scanSnippet("\n\nfunction f(e: ApiError) { return e.message; }");
    expect(v).toMatchObject({ rule: "W1", text: "e.message" });
  });
});

describe("the allowlist", () => {
  it("applies by file, rule and exact text, and reports entries that match nothing", () => {
    const v: Violation = { file: "src/a.ts", line: 3, rule: "W1", text: "err.message" };
    const entry = { file: "src/a.ts", rule: "W1" as const, text: "err.message", reason: "r" };
    expect(applyAllowlist([v], [entry])).toEqual({ remaining: [], stale: [] });
    expect(applyAllowlist([{ ...v, rule: "W2" }], [entry]).remaining).toHaveLength(1);
    expect(applyAllowlist([], [entry]).stale).toEqual([entry]);
  });

  it("gives every entry a real reason", () => {
    expect(ALLOWLIST.every((a) => a.reason.trim().length > 30)).toBe(true);
  });
});

describe("the real source tree", () => {
  it("has no unlisted raw error exposure or silent failure, and no stale allowlist entry", () => {
    const program = loadProgram(WEB_ROOT);
    const violations = check(program, WEB_ROOT, isProductionSource(WEB_ROOT));
    const { remaining, stale } = applyAllowlist(violations);
    expect(remaining.map((v) => `${v.file}:${v.line} [${v.rule}] ${v.text}`)).toEqual([]);
    expect(stale.map((a) => `${a.file} [${a.rule}] ${a.text}`)).toEqual([]);
  }, 120_000);
});
