import { useQuery } from "@tanstack/react-query";
import { api } from "../lib/api";

/** Polls real host telemetry only while the tab is visible. */
export function useSystem() {
  return useQuery({
    queryKey: ["system"],
    queryFn: api.system,
    refetchInterval: 15_000,
    refetchIntervalInBackground: false,
  });
}
