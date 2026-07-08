import { startTransition, useCallback, useEffect, useMemo, useState } from "react";
import {
  approveRun,
  cancelRun,
  createSession,
  deleteContextFile,
  deleteSession,
  getRun,
  getRuntimeStatus,
  getSession,
  listSessions,
  rejectRun,
  renameSession,
  sendMessage,
  setSessionAutoApprove,
  stopSandbox,
  subscribeRun,
  uploadContextFile,
} from "../api";
import { EMPTY_USAGE, type View } from "../lib/constants";
import type {
  ActivityItem,
  Run,
  RunEvent,
  RuntimeStatus,
  SessionDetail,
  SessionFile,
  SessionSummary,
  Usage,
} from "../types";

export function useHarnessSession() {
  const [runtime, setRuntime] = useState<RuntimeStatus | null>(null);
  const [sessions, setSessions] = useState<SessionSummary[]>([]);
  const [session, setSession] = useState<SessionDetail | null>(null);
  const [run, setRun] = useState<Run | null>(null);
  const [events, setEvents] = useState<RunEvent[]>([]);
  const [traceEvents, setTraceEvents] = useState<RunEvent[]>([]);
  const [approval, setApproval] = useState<Record<string, unknown> | null>(null);
  const [pending, setPending] = useState<SessionFile[]>([]);
  const [view, setView] = useState<View>("control");
  const [search, setSearch] = useState("");
  const [error, setError] = useState("");
  const [sidebarOpen, setSidebarOpen] = useState(false);

  const refreshSessions = useCallback(async (query = search) => {
    const value = await listSessions(query);
    setSessions(value);
    return value;
  }, [search]);

  const loadSession = useCallback(async (sessionId: string) => {
    const detail = await getSession(sessionId);
    const latestApproval = [...detail.events]
      .reverse()
      .find((event) =>
        [
          "approval.requested",
          "approval.resolved",
          "run.completed",
          "run.failed",
          "run.cancelled",
        ].includes(event.type),
      );
    startTransition(() => {
      setSession(detail);
      setRun(detail.latest_run);
      setEvents(detail.events);
      setTraceEvents(detail.trace_events);
      setApproval(
        latestApproval?.type === "approval.requested" ? latestApproval.payload : null,
      );
      setPending([]);
      setError("");
    });
  }, []);

  useEffect(() => {
    let cancelled = false;
    Promise.all([getRuntimeStatus(), listSessions()])
      .then(async ([runtimeValue, sessionValues]) => {
        if (cancelled) return;
        setRuntime(runtimeValue);
        let available = sessionValues;
        if (!available.length) {
          const created = await createSession();
          available = [created];
        }
        if (cancelled) return;
        setSessions(available);
        await loadSession(available[0].id);
      })
      .catch((reason: unknown) => {
        if (!cancelled) setError(reason instanceof Error ? reason.message : "Backend offline");
      });
    return () => {
      cancelled = true;
    };
  }, [loadSession]);

  useEffect(() => {
    const timer = window.setTimeout(() => {
      refreshSessions(search).catch((reason: unknown) =>
        setError(reason instanceof Error ? reason.message : "Ricerca fallita"),
      );
    }, 250);
    return () => window.clearTimeout(timer);
  }, [refreshSessions, search]);

  useEffect(() => {
    if (!run || ["completed", "failed", "cancelled"].includes(run.status)) return;
    const stop = subscribeRun(
      run.id,
      (event) => {
        setEvents((current) =>
          current.some((item) => item.id === event.id) ? current : [...current, event],
        );
        setTraceEvents((current) =>
          current.some((item) => item.id === event.id) ? current : [...current, event],
        );
        if (event.type === "approval.requested") {
          setApproval(event.payload);
        }
        if (event.type === "approval.resolved") {
          setApproval(null);
        }
        if (["run.completed", "run.failed", "run.cancelled"].includes(event.type)) {
          setApproval(null);
          Promise.all([getRun(run.id), getSession(event.session_id), refreshSessions()])
            .then(([runValue, detail]) => {
              setRun(runValue);
              setSession(detail);
              setEvents(detail.events ?? []);
              setTraceEvents(detail.trace_events ?? []);
            })
            .catch((reason: unknown) => {
              setError(
                reason instanceof Error ? reason.message : "Aggiornamento sessione fallito",
              );
            });
        } else if (event.type === "assistant.completed") {
          getSession(event.session_id)
            .then((detail) => {
              setSession(detail);
              setEvents(detail.events ?? []);
            })
            .catch(() => undefined);
        } else if (event.type.startsWith("file.")) {
          getSession(event.session_id).then(setSession).catch(() => undefined);
        } else {
          getRun(run.id).then(setRun).catch(() => undefined);
        }
      },
      () => {
        getRun(run.id)
          .then((value) => {
            setRun(value);
            if (["completed", "failed", "cancelled"].includes(value.status)) {
              getSession(value.session_id)
                .then((detail) => {
                  setSession(detail);
                  setEvents(detail.events ?? []);
                  setTraceEvents(detail.trace_events ?? []);
                })
                .catch(() => undefined);
            }
          })
          .catch(() => undefined);
      },
    );
    return stop;
  }, [refreshSessions, run?.id]); // eslint-disable-line react-hooks/exhaustive-deps

  const activeToolNames = useMemo(() => {
    const active = new Set<string>();
    for (const event of events) {
      const tool = event.payload.tool;
      if (typeof tool !== "string") continue;
      if (event.type === "tool.started") active.add(tool);
      if (event.type === "tool.completed" || event.type === "tool.failed") active.delete(tool);
    }
    return active;
  }, [events]);

  const observedTools = useMemo(() => {
    const names = new Set(runtime?.tools.map((item) => item.name) ?? []);
    for (const event of events) {
      if (typeof event.payload.tool === "string") names.add(event.payload.tool);
    }
    return [...names];
  }, [events, runtime?.tools]);

  const toolItems = useMemo<ActivityItem[]>(
    () =>
      observedTools.map((name) => {
        const latest = [...events]
          .reverse()
          .find(
            (event) =>
              event.payload.tool === name &&
              ["tool.started", "tool.completed", "tool.failed"].includes(event.type),
          );
        return {
          id: name,
          name,
          detail: "Tool",
          status:
            activeToolNames.has(name) ? "active" : latest?.type === "tool.failed" ? "error" : "ready",
          meta:
            activeToolNames.has(name) ? "in uso" : latest?.type === "tool.failed" ? "errore" : "pronto",
        };
      }),
    [activeToolNames, events, observedTools],
  );

  const skillItems = useMemo<ActivityItem[]>(
    () =>
      (runtime?.skills ?? []).map((item) => {
        const active = events.some(
          (event) => event.type === "skill.started" && event.payload.skill === item.name,
        );
        const completed = events.some(
          (event) => event.type === "skill.completed" && event.payload.skill === item.name,
        );
        return {
          id: item.name,
          name: item.name,
          detail: "Skill locale",
          status: active && !completed ? "active" : "ready",
          meta: completed ? "usata" : active ? "in uso" : "pronta",
        };
      }),
    [events, runtime?.skills],
  );

  const { latestLiveUsage, latestSnapshot } = useMemo(() => {
    let live: Record<string, unknown> | undefined;
    let snapshot: Record<string, unknown> | undefined;
    for (let i = events.length - 1; i >= 0 && (!live || !snapshot); i--) {
      const event = events[i];
      if (!live && event.type === "usage.live") live = event.payload;
      if (!snapshot && event.type === "usage.snapshot") snapshot = event.payload;
    }
    return { latestLiveUsage: live, latestSnapshot: snapshot };
  }, [events]);

  const active = Boolean(run && !["completed", "failed", "cancelled"].includes(run.status));

  const usage: Usage =
    active && (latestSnapshot || latestLiveUsage)
      ? {
          ...EMPTY_USAGE,
          // Input/contesto: esatto per-turno dal provider; output: stima live dallo streaming.
          input_tokens: Number(latestSnapshot?.input_tokens ?? 0),
          output_tokens: Number(
            latestSnapshot?.output_tokens ?? latestLiveUsage?.output_tokens ?? 0,
          ),
          total_tokens: Number(
            latestSnapshot?.total_tokens ?? latestLiveUsage?.output_tokens ?? 0,
          ),
          output_tokens_per_second: Number(latestLiveUsage?.output_tokens_per_second ?? 0),
          context_categories:
            (latestSnapshot?.context_categories as Usage["context_categories"] | undefined) ?? [],
          estimated_context: true,
        }
      : (run?.usage ?? EMPTY_USAGE);

  const handleNew = async () => {
    try {
      setSearch("");
      const created = await createSession();
      const available = await listSessions();
      setSessions(available);
      await loadSession(created.id);
      setView("control");
      setSidebarOpen(false);
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : "Creazione fallita");
    }
  };

  const handleSend = async (content: string) => {
    if (!session) return;
    try {
      const names = pending.map((file) => file.name);
      const created = await sendMessage(session.id, content, names);
      const [detail, runValue] = await Promise.all([
        getSession(session.id),
        getRun(created.run_id),
      ]);
      setSession(detail);
      setRun(runValue);
      setEvents(detail.events ?? []);
      setTraceEvents(detail.trace_events ?? []);
      setPending([]);
      setError("");
      await refreshSessions();
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : "Invio fallito");
    }
  };

  const handleUpload = async (selected: FileList | null) => {
    if (!session || !selected?.length) return;
    try {
      await Promise.all(Array.from(selected).map((file) => uploadContextFile(session.id, file)));
      await loadSession(session.id);
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : "Upload fallito");
    }
  };

  const handleComposerUpload = async (selected: FileList | null) => {
    if (!session || !selected?.length) return;
    try {
      const uploaded = await Promise.all(
        Array.from(selected).map((file) => uploadContextFile(session.id, file)),
      );
      setPending((current) => {
        const merged = new Map(current.map((file) => [file.name, file]));
        for (const file of uploaded) merged.set(file.name, file);
        return [...merged.values()];
      });
      const detail = await getSession(session.id);
      setSession(detail);
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : "Upload fallito");
    }
  };

  const handleRemovePending = async (name: string) => {
    if (!session) return;
    setPending((current) => current.filter((file) => file.name !== name));
    try {
      await deleteContextFile(session.id, name);
      const detail = await getSession(session.id);
      setSession(detail);
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : "Rimozione allegato fallita");
    }
  };

  const handleDeleteFile = async (name: string) => {
    if (!session || !window.confirm(`Eliminare ${name} da questa conversazione?`)) return;
    try {
      await deleteContextFile(session.id, name);
      await loadSession(session.id);
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : "Eliminazione fallita");
    }
  };

  const handleDeleteSession = async () => {
    if (!session || !window.confirm(`Eliminare sessione “${session.title}” e tutti i file?`)) return;
    try {
      await deleteSession(session.id);
      setSearch("");
      const remaining = await listSessions();
      setSessions(remaining);
      if (remaining.length) {
        await loadSession(remaining[0].id);
      } else {
        await handleNew();
      }
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : "Eliminazione fallita");
    }
  };

  const handleStopSandbox = async () => {
    if (!session) return;
    try {
      const sandbox = await stopSandbox(session.id);
      setSession((current) => (current ? { ...current, sandbox } : current));
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : "Arresto sandbox fallito");
    }
  };

  const handleRename = async () => {
    if (!session) return;
    const title = window.prompt("Titolo sessione", session.title)?.trim();
    if (!title) return;
    try {
      await renameSession(session.id, title);
      await Promise.all([loadSession(session.id), refreshSessions()]);
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : "Rinomina fallita");
    }
  };

  const handleToggleAutoApprove = async (enabled: boolean) => {
    if (!session) return;
    // Aggiornamento ottimistico: il toggle risponde subito, senza attendere il round-trip.
    setSession((current) => (current ? { ...current, auto_approve: enabled } : current));
    try {
      await setSessionAutoApprove(session.id, enabled);
      await refreshSessions();
    } catch (reason) {
      setSession((current) => (current ? { ...current, auto_approve: !enabled } : current));
      setError(reason instanceof Error ? reason.message : "Aggiornamento autonomia fallito");
    }
  };

  const handleStop = async () => {
    if (!run) return;
    try {
      await cancelRun(run.id);
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : "Stop fallito");
    }
  };

  const resolveApproval = async (approved: boolean) => {
    if (!run) return;
    try {
      if (approved) await approveRun(run.id);
      else await rejectRun(run.id);
      setApproval(null);
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : "Approvazione fallita");
    }
  };

  const selectSession = (id: string) => {
    loadSession(id).catch((reason: unknown) =>
      setError(reason instanceof Error ? reason.message : "Caricamento fallito"),
    );
    setView("control");
    setSidebarOpen(false);
  };

  return {
    runtime,
    sessions,
    session,
    run,
    events,
    traceEvents,
    approval,
    pending,
    view,
    search,
    error,
    sidebarOpen,
    usage,
    skillItems,
    toolItems,
    setView,
    setSearch,
    setError,
    setSidebarOpen,
    handleNew,
    handleSend,
    handleUpload,
    handleComposerUpload,
    handleRemovePending,
    handleDeleteFile,
    handleDeleteSession,
    handleRename,
    handleToggleAutoApprove,
    handleStop,
    handleStopSandbox,
    resolveApproval,
    selectSession,
  };
}

export type HarnessSession = ReturnType<typeof useHarnessSession>;
