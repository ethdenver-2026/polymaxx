import { useEffect } from "react";
import { useQueryClient } from "@tanstack/react-query";

/**
 * Subscribes to the SSE signal stream from the consumer.
 * On each event, invalidates the signals, balances, and positions caches
 * so the UI updates instantly without waiting for the next poll interval.
 */
export function useSignalStream() {
  const queryClient = useQueryClient();

  useEffect(() => {
    const es = new EventSource("/api/signals/stream");

    es.onmessage = () => {
      // A new signal was logged — invalidate stale caches immediately
      console.log("help")
      queryClient.invalidateQueries({ queryKey: ["signals"] });
      queryClient.invalidateQueries({ queryKey: ["balances"] });
      queryClient.invalidateQueries({ queryKey: ["positions"] });
      queryClient.invalidateQueries({ queryKey: ["portfolioValue"] });
    };

    es.onerror = () => {
      // EventSource auto-reconnects; nothing to do here
    };

    return () => es.close();
  }, [queryClient]);
}
