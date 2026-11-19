import { renderHook, waitFor } from "@testing-library/react";
import { expect, it } from "vitest";
import { useInfiniteScroll } from "./useInfiniteScroll";

it("drops results from the previous search if the new search fails", async () => {
  const { result, rerender } = renderHook(
    ({ search }) => useInfiniteScroll(
      async () => {
        if (search === "forecast") throw new Error("Registry unavailable");
        return { items: ["plot"], total: 42, total_pages: 2 };
      },
      [search],
    ),
    { initialProps: { search: "plot" } },
  );
  await waitFor(() => expect(result.current.items).toEqual(["plot"]));
  rerender({ search: "forecast" });
  await waitFor(() => expect(result.current.error).toBe("Registry unavailable"));
  expect(result.current.items).toEqual([]);
  expect(result.current.total).toBe(0);
  expect(result.current.hasMore).toBe(false);
});
