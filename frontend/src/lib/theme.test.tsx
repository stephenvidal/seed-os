import { act, render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";
import { ThemeProvider, readPreference, resolveTheme, useTheme } from "./theme";

describe("resolveTheme", () => {
  it("follows the system only when preference is system", () => {
    expect(resolveTheme("system", true)).toBe("dark");
    expect(resolveTheme("system", false)).toBe("light");
    expect(resolveTheme("light", true)).toBe("light");
    expect(resolveTheme("dark", false)).toBe("dark");
  });
});

describe("readPreference", () => {
  it("defaults to system and rejects garbage", () => {
    expect(readPreference()).toBe("system");
    localStorage.setItem("seed.theme", "purple");
    expect(readPreference()).toBe("system");
    localStorage.setItem("seed.theme", "dark");
    expect(readPreference()).toBe("dark");
  });
});

function Probe() {
  const t = useTheme();
  return (
    <button onClick={t.toggle}>
      {t.preference}:{t.resolved}
    </button>
  );
}

describe("ThemeProvider", () => {
  it("applies data-theme and persists the toggled preference", () => {
    render(
      <ThemeProvider>
        <Probe />
      </ThemeProvider>,
    );
    expect(document.documentElement.dataset.theme).toBe("light");
    act(() => screen.getByRole("button").click());
    expect(screen.getByRole("button")).toHaveTextContent("dark:dark");
    expect(document.documentElement.dataset.theme).toBe("dark");
    expect(localStorage.getItem("seed.theme")).toBe("dark");
  });
});
