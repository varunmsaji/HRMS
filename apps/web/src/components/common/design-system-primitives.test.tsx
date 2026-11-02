import { render, screen } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";

import { PageHeader } from "@/components/common/page-header";
import { EmployeeIdentityCell } from "@/components/employee/employee-identity";
import { EmployeeStatusBadge } from "@/components/employee/employee-status-badge";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import {
  Table,
  TableBody,
  TableCell,
  TableContainer,
  TableHead,
  TableHeader,
  TableRow,
  TableToolbar,
  tableNeedsHorizontalScroll,
} from "@/components/ui/table";

describe("Design System Shared Primitives", () => {
  it("renders PageHeader with back link, badge, meta, and actions", () => {
    render(
      <PageHeader
        backHref="/app/employees"
        backLabel="Employees"
        title="Asha Rao"
        description="Employee code EMP-001"
        badge={<EmployeeStatusBadge status="ACTIVE" />}
        meta={<span>asha.rao@example.com</span>}
        actions={<Button size="sm">Edit</Button>}
      />,
    );

    expect(screen.getByRole("heading", { name: "Asha Rao" })).toBeInTheDocument();
    expect(screen.getByRole("link", { name: /Employees/i })).toHaveAttribute(
      "href",
      "/app/employees",
    );
    expect(screen.getByText("Active")).toBeInTheDocument();
    expect(screen.getByText("asha.rao@example.com")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Edit" })).toBeInTheDocument();
  });

  it("renders Button loading state with aria-busy and disabled", () => {
    render(<Button loading>Saving…</Button>);
    const btn = screen.getByRole("button", { name: /Saving/i });
    expect(btn).toBeDisabled();
    expect(btn).toHaveAttribute("aria-busy", "true");
  });

  it("renders EmployeeIdentityCell with initials, code, subtitle, and link", () => {
    render(
      <EmployeeIdentityCell
        name="Priya Sharma"
        code="EMP-042"
        subtitle="Engineering"
        href="/app/employees/emp-042"
      />,
    );

    expect(screen.getByText("PS")).toBeInTheDocument();
    expect(screen.getByRole("link", { name: /Priya Sharma/i })).toHaveAttribute(
      "href",
      "/app/employees/emp-042",
    );
    expect(screen.getByText("EMP-042")).toBeInTheDocument();
    expect(screen.getByText("Engineering")).toBeInTheDocument();
  });

  it("renders TableContainer, TableToolbar, and numeric TableCell alignment", () => {
    render(
      <TableContainer>
        <TableToolbar>
          <span>Filter bar</span>
        </TableToolbar>
        <Table>
          <TableHeader>
            <TableRow>
              <TableHead>Component</TableHead>
              <TableHead align="right">Amount</TableHead>
            </TableRow>
          </TableHeader>
          <TableBody>
            <TableRow>
              <TableCell>Basic Salary</TableCell>
              <TableCell align="right" numeric>
                ₹50,000.00
              </TableCell>
            </TableRow>
          </TableBody>
        </Table>
      </TableContainer>,
    );

    expect(screen.getByText("Filter bar")).toBeInTheDocument();
    expect(screen.getByRole("columnheader", { name: "Amount" })).toBeInTheDocument();
    expect(screen.getByRole("cell", { name: "₹50,000.00" })).toHaveClass("tabular-nums");
  });

  it("renders Badge with dot indicator for semantic states", () => {
    render(
      <Badge variant="success" dot>
        Approved
      </Badge>,
    );
    expect(screen.getByText("Approved")).toBeInTheDocument();
  });

  it("renders Badge as an inline element so it can sit inside a paragraph without a hydration error", () => {
    const error = vi.spyOn(console, "error").mockImplementation(() => {});
    render(
      <p>
        <Badge variant="secondary">Casual Leave</Badge>
      </p>,
    );
    expect(screen.getByText("Casual Leave").tagName).toBe("SPAN");
    expect(error).not.toHaveBeenCalled();
    error.mockRestore();
  });

  it("hints at horizontal scrolling only when the table is wider than its container", () => {
    expect(tableNeedsHorizontalScroll(800, 390)).toBe(true);
    expect(tableNeedsHorizontalScroll(390, 390)).toBe(false);
    expect(tableNeedsHorizontalScroll(391, 390)).toBe(false);
    expect(tableNeedsHorizontalScroll(392, 390)).toBe(true);
  });

  it("exposes the scrollport to the keyboard when the table overflows", async () => {
    const widths = new WeakMap<Element, { scroll: number; client: number }>();
    const originalScroll = Object.getOwnPropertyDescriptor(HTMLElement.prototype, "scrollWidth");
    const originalClient = Object.getOwnPropertyDescriptor(HTMLElement.prototype, "clientWidth");
    Object.defineProperty(HTMLElement.prototype, "scrollWidth", {
      configurable: true,
      get() {
        return widths.get(this)?.scroll ?? 0;
      },
    });
    Object.defineProperty(HTMLElement.prototype, "clientWidth", {
      configurable: true,
      get() {
        return widths.get(this)?.client ?? 0;
      },
    });
    const Original = globalThis.ResizeObserver;
    globalThis.ResizeObserver = class {
      private readonly callback: ResizeObserverCallback;
      constructor(callback: ResizeObserverCallback) {
        this.callback = callback;
      }
      observe(target: Element) {
        widths.set(target, { scroll: 800, client: 390 });
        this.callback([], this as unknown as ResizeObserver);
      }
      unobserve() {}
      disconnect() {}
    };
    try {
      render(
        <Table>
          <TableBody>
            <TableRow>
              <TableCell>Asha Rao</TableCell>
            </TableRow>
          </TableBody>
        </Table>,
      );
      expect(await screen.findByText("Scroll horizontally to see more columns")).toBeInTheDocument();
      expect(screen.getByRole("region", { name: "Scrollable table" })).toHaveAttribute("tabindex", "0");
    } finally {
      globalThis.ResizeObserver = Original;
      if (originalScroll) Object.defineProperty(HTMLElement.prototype, "scrollWidth", originalScroll);
      if (originalClient) Object.defineProperty(HTMLElement.prototype, "clientWidth", originalClient);
    }
  });

  it("does not show the scroll hint or an extra tab stop when the table fits", async () => {
    const widths = new WeakMap<Element, { scroll: number; client: number }>();
    const originalScroll = Object.getOwnPropertyDescriptor(HTMLElement.prototype, "scrollWidth");
    const originalClient = Object.getOwnPropertyDescriptor(HTMLElement.prototype, "clientWidth");
    Object.defineProperty(HTMLElement.prototype, "scrollWidth", {
      configurable: true,
      get() {
        return widths.get(this)?.scroll ?? 0;
      },
    });
    Object.defineProperty(HTMLElement.prototype, "clientWidth", {
      configurable: true,
      get() {
        return widths.get(this)?.client ?? 0;
      },
    });
    const Original = globalThis.ResizeObserver;
    globalThis.ResizeObserver = class {
      private readonly callback: ResizeObserverCallback;
      constructor(callback: ResizeObserverCallback) {
        this.callback = callback;
      }
      observe(target: Element) {
        widths.set(target, { scroll: 390, client: 390 });
        this.callback([], this as unknown as ResizeObserver);
      }
      unobserve() {}
      disconnect() {}
    };
    try {
      render(
        <Table>
          <TableBody>
            <TableRow>
              <TableCell>Asha Rao</TableCell>
            </TableRow>
          </TableBody>
        </Table>,
      );
      await screen.findByText("Asha Rao");
      expect(screen.queryByText("Scroll horizontally to see more columns")).not.toBeInTheDocument();
      expect(screen.queryByRole("region", { name: "Scrollable table" })).not.toBeInTheDocument();
    } finally {
      globalThis.ResizeObserver = Original;
      if (originalScroll) Object.defineProperty(HTMLElement.prototype, "scrollWidth", originalScroll);
      if (originalClient) Object.defineProperty(HTMLElement.prototype, "clientWidth", originalClient);
    }
  });
});
