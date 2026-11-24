import { humanize, money, parseConditionValue, relative } from "./format";

describe("parseConditionValue", () => {
  it.each([
    ["true", "eq", true],
    ["false", "eq", false],
    ["100000", "gte", 100000],
    [" 12.5 ", "lte", 12.5],
    ["production", "eq", "production"],
    ["a, b ,c", "in", ["a", "b", "c"]],
    ["1,2", "in", ["1", "2"]],
  ])("%j with %s → %j", (raw, op, expected) => {
    expect(parseConditionValue(raw, op)).toEqual(expected);
  });
});

describe("relative", () => {
  const now = Date.parse("2026-01-01T12:00:00Z");
  it("past and future", () => {
    expect(relative("2026-01-01T11:59:30Z", now)).toBe("30s ago");
    expect(relative("2026-01-01T11:00:00Z", now)).toBe("1h ago");
    expect(relative("2025-12-30T12:00:00Z", now)).toBe("2d ago");
    expect(relative("2026-01-01T12:10:00Z", now)).toBe("in 10m");
  });
});

describe("money / humanize", () => {
  it("formats currency and tolerates unknown codes", () => {
    expect(money(null)).toBe("");
    expect(money(1200, "INR")).toContain("1,200");
    expect(money(5, "NOT-A-CODE")).toContain("NOT-A-CODE");
  });
  it("humanizes snake case", () => expect(humanize("auto_approved")).toBe("auto approved"));
});
