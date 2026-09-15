import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";
import { Chart, parseChartSpec } from "./Chart";

describe("parseChartSpec", () => {
  it("reads a well-formed spec", () => {
    const spec = parseChartSpec('{"type":"bar","title":"T","unit":"$","data":[{"label":"A","value":1}]}');
    expect(spec).toMatchObject({ type: "bar", title: "T", unit: "$" });
    expect(spec!.data).toHaveLength(1);
  });

  it("returns null on malformed JSON so it can fall back to a code block", () => {
    expect(parseChartSpec("{not json")).toBeNull();
  });

  it("returns null when there is no usable data", () => {
    expect(parseChartSpec('{"type":"bar","data":[]}')).toBeNull();
    expect(parseChartSpec('{"type":"bar","data":[{"label":"A"}]}')).toBeNull();
  });

  it("drops non-numeric points rather than rendering NaN bars", () => {
    const spec = parseChartSpec('{"data":[{"label":"A","value":1},{"label":"B","value":"lots"}]}');
    expect(spec!.data).toHaveLength(1);
  });

  it("defaults an unknown chart type to bar", () => {
    expect(parseChartSpec('{"type":"radar","data":[{"label":"A","value":1}]}')!.type).toBe("bar");
  });
});

describe("Chart", () => {
  it("labels every bar with its value", () => {
    render(<Chart spec={{ type: "bar", unit: "$", data: [
      { label: "Solar", value: 40 }, { label: "Gas", value: 70 }] }} />);
    expect(screen.getByText("Solar")).toBeInTheDocument();
    expect(screen.getByText("$40")).toBeInTheDocument();
    expect(screen.getByText("$70")).toBeInTheDocument();
  });

  it("does not print the share twice when values are already percentages", () => {
    render(<Chart spec={{ type: "pie", unit: "%", data: [
      { label: "Solar", value: 61 }, { label: "Wind", value: 39 }] }} />);
    // "61% 61%" was the bug: unit and computed share said the same thing.
    expect(screen.getByText("61%")).toBeInTheDocument();
    expect(screen.queryAllByText("61%")).toHaveLength(1);
  });

  it("adds the share when the unit is not a percentage", () => {
    render(<Chart spec={{ type: "pie", unit: "TWh", data: [
      { label: "Solar", value: 50 }, { label: "Wind", value: 50 }] }} />);
    expect(screen.getAllByText("50%")).toHaveLength(2);
  });

  it("draws a single-slice pie as a full circle", () => {
    // Start and end points coincide on a full arc, collapsing the path.
    const { container } = render(<Chart spec={{ type: "pie", data: [{ label: "All", value: 100 }] }} />);
    const path = container.querySelector(".chart-pie path")!;
    expect(path.getAttribute("d")).toContain("a");
  });

  it("gives charts an accessible description of the data", () => {
    render(<Chart spec={{ type: "line", data: [
      { label: "2020", value: 10 }, { label: "2024", value: 40 }] }} />);
    expect(screen.getByRole("img", { name: /2020 10, 2024 40/ })).toBeInTheDocument();
  });
});
