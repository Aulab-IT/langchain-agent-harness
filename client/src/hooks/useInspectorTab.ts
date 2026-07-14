import { useCallback, useState } from "react";
import type { InspectorTab } from "../lib/constants";

const STORAGE_KEY = "harness-inspector-tab";

export function useInspectorTab(defaultTab: InspectorTab = "files") {
  const [tab, setTab] = useState<InspectorTab>(() => {
    const stored = localStorage.getItem(STORAGE_KEY);
    if (
      stored === "trace" ||
      stored === "evidence" ||
      stored === "files" ||
      stored === "capabilities" ||
      stored === "memory" ||
      stored === "context" ||
      stored === "sandbox"
    ) {
      return stored;
    }
    return defaultTab;
  });

  const selectTab = useCallback((next: InspectorTab) => {
    setTab(next);
    localStorage.setItem(STORAGE_KEY, next);
  }, []);

  return { tab, selectTab };
}

export function useInspectorSheet() {
  const [open, setOpen] = useState(false);
  return {
    open,
    openSheet: () => setOpen(true),
    closeSheet: () => setOpen(false),
    toggleSheet: () => setOpen((value) => !value),
  };
}
