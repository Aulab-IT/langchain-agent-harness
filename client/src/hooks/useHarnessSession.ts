import { startTransition, useCallback, useEffect, useMemo, useState } from "react";
import {
  approveRun,
  cancelRun,
  compactContext,
  createSession,
  deleteContextFile,
  deleteSession,
  getRun,
  getRuntimeStatus,
  getSession,
  getSessionEventPage,
  listSessions,
  rejectRun,
  renameSession,
  sendMessage,
  setSessionAutoApprove,
  setSessionModelOverride,
  stopSandbox,
  submitAction,
  subscribeRun,
  uploadContextFile,
} from "../api";
import { EMPTY_USAGE, type View } from "../lib/constants";
import { isTerminalRunStatus } from "../lib/runStatus";
import {
  deriveSkillActivity,
  deriveToolActivity,
  deriveToolSteps,
} from "../lib/sessionActivity";
import type {
  ModelOverride,
  Run,
  RunEvent,
  RuntimeStatus,
  SessionDetail,
  SessionFile,
  SessionSummary,
  Usage,
} from "../types";

function mergeEvents(...groups: RunEvent[][]): RunEvent[] {
  const byId = new Map<number, RunEvent>();
  for (const group of groups) {
    for (const event of group) byId.set(event.id, event);
  }
  return [...byId.values()].sort((left, right) => left.id - right.id);
}

function isTerminalRunEvent(event: RunEvent): boolean {
  if (!event.type.startsWith("run.")) return false;
  return isTerminalRunStatus(event.type.slice(4) as Run["status"]);
}

export function useHarnessSession() {
  const [runtime, setRuntime] = useState<RuntimeStatus | null>(null);
  const [sessions, setSessions] = useState<SessionSummary[]>([]);
  const [session, setSession] = useState<SessionDetail | null>(null);
  const [run, setRun] = useState<Run | null>(null);
  // Store canonico di sessione. Chat/Inspector filtrano il run corrente; Cronologia usa tutto.
  const [events, setEvents] = useState<RunEvent[]>([]);
  const [approval, setApproval] = useState<Record<string, unknown> | null>(null);
  const [actionRequest, setActionRequest] = useState<Record<string, unknown> | null>(null);
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

  const loadEventHistory = useCallback(async (sessionId: string): Promise<RunEvent[]> => {
    const pages: RunEvent[][] = [];
    let before: number | undefined;
    while (true) {
      const page = await getSessionEventPage(sessionId, before);
      pages.unshift(page.events);
      if (!page.has_more_before) break;
      const firstId = page.events[0]?.id;
      if (!firstId || firstId === before) break;
      before = firstId;
    }
    return mergeEvents(...pages);
  }, []);

  const loadSession = useCallback(async (sessionId: string) => {
    const [detail, history] = await Promise.all([
      getSession(sessionId),
      loadEventHistory(sessionId),
    ]);
    const latestApproval = [...history]
      .reverse()
      .find((event) =>
        ["approval.requested", "approval.resolved"].includes(event.type)
        || isTerminalRunEvent(event),
      );
    const latestAction = [...history]
      .reverse()
      .find((event) =>
        ["action.requested", "action.resolved"].includes(event.type)
        || isTerminalRunEvent(event),
      );
    startTransition(() => {
      setSession(detail);
      setRun(detail.latest_run);
      setEvents(history);
      setApproval(
        latestApproval?.type === "approval.requested" ? latestApproval.payload : null,
      );
      setActionRequest(
        latestAction?.type === "action.requested" ? latestAction.payload : null,
      );
      setPending([]);
      setError("");
    });
  }, [loadEventHistory]);

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
    if (!run || isTerminalRunStatus(run.status)) return;
    const stop = subscribeRun(
      run.id,
      (event) => {
        setEvents((current) =>
          current.some((item) => item.id === event.id) ? current : [...current, event],
        );
        if (event.type === "approval.requested") {
          setApproval(event.payload);
        }
        if (event.type === "approval.resolved") {
          setApproval(null);
        }
        if (event.type === "action.requested") {
          setActionRequest(event.payload);
        }
        if (event.type === "action.resolved") {
          setActionRequest(null);
        }
        const eventStatus = event.type.startsWith("run.")
          ? event.type.slice(4) as Run["status"]
          : null;
        if (eventStatus && isTerminalRunStatus(eventStatus)) {
          setApproval(null);
          setActionRequest(null);
          Promise.all([
            getRun(run.id),
            getSession(event.session_id),
            loadEventHistory(event.session_id),
            refreshSessions(),
          ])
            .then(([runValue, detail, history]) => {
              setRun(runValue);
              setSession(detail);
              setEvents((current) =>
                mergeEvents(
                  current.filter((item) => item.type !== "assistant.delta"),
                  history,
                ),
              );
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
            if (isTerminalRunStatus(value.status)) {
              Promise.all([getSession(value.session_id), loadEventHistory(value.session_id)])
                .then(([detail, history]) => {
                  setSession(detail);
                  setEvents((current) =>
                    mergeEvents(
                      current.filter((item) => item.type !== "assistant.delta"),
                      history,
                    ),
                  );
                })
                .catch(() => undefined);
            }
          })
          .catch(() => undefined);
      },
    );
    return stop;
  }, [loadEventHistory, refreshSessions, run?.id]); // eslint-disable-line react-hooks/exhaustive-deps

  const runEvents = useMemo(
    () => (run ? events.filter((event) => event.run_id === run.id) : []),
    [events, run],
  );

  // Il pannello mostra ciò che la sessione ha davvero usato: entrambe le liste derivano
  // dalle invocazioni registrate, non dal catalogo di ciò che sarebbe disponibile.
  const toolSteps = useMemo(() => deriveToolSteps(runEvents), [runEvents]);
  const toolItems = useMemo(() => deriveToolActivity(toolSteps), [toolSteps]);
  const skillItems = useMemo(() => deriveSkillActivity(toolSteps), [toolSteps]);

  const { latestLiveUsage, latestSnapshot, latestBudget } = useMemo(() => {
    let live: Record<string, unknown> | undefined;
    let snapshot: Record<string, unknown> | undefined;
    let budget: Record<string, unknown> | undefined;
    for (let i = runEvents.length - 1; i >= 0 && (!live || !snapshot || !budget); i--) {
      const event = runEvents[i];
      if (!live && event.type === "usage.live") live = event.payload;
      if (!snapshot && event.type === "usage.snapshot") snapshot = event.payload;
      if (!budget && ["budget.updated", "budget.warning", "budget.exceeded"].includes(event.type)) {
        budget = event.payload;
      }
    }
    return { latestLiveUsage: live, latestSnapshot: snapshot, latestBudget: budget };
  }, [runEvents]);

  const active = Boolean(run && !isTerminalRunStatus(run.status));

  const usage: Usage =
    active && (latestSnapshot || latestLiveUsage || latestBudget)
      ? {
          ...EMPTY_USAGE,
          // Input/contesto: esatto per-turno dal provider; output: stima live dallo streaming.
          input_tokens: Number(
            latestSnapshot?.context_input_tokens ?? latestSnapshot?.input_tokens ?? 0,
          ),
          output_tokens: Number(
            latestSnapshot?.cumulative_output_tokens ?? latestSnapshot?.output_tokens ?? latestLiveUsage?.output_tokens ?? 0,
          ),
          total_tokens: Number(
            latestBudget?.total_tokens ?? latestSnapshot?.cumulative_input_tokens ?? latestSnapshot?.input_tokens ?? 0,
          ) + Number(
            latestBudget?.total_tokens ? 0 : latestSnapshot?.cumulative_output_tokens ?? latestSnapshot?.output_tokens ?? latestLiveUsage?.output_tokens ?? 0,
          ),
          context_input_tokens: Number(
            latestSnapshot?.context_input_tokens ?? latestSnapshot?.input_tokens ?? 0,
          ),
          cumulative_input_tokens: Number(
            latestBudget?.cumulative_input_tokens ?? latestSnapshot?.cumulative_input_tokens ?? latestSnapshot?.input_tokens ?? 0,
          ),
          cumulative_output_tokens: Number(
            latestBudget?.cumulative_output_tokens ?? latestSnapshot?.cumulative_output_tokens ?? latestSnapshot?.output_tokens ?? latestLiveUsage?.output_tokens ?? 0,
          ),
          run_total_tokens: Number(latestBudget?.total_tokens ?? 0),
          cost_usd: typeof latestBudget?.cost_usd === "string" ? latestBudget.cost_usd : undefined,
          budget: latestBudget as Usage["budget"] | undefined,
          reasoning_tokens: Number(latestSnapshot?.reasoning_tokens ?? 0),
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
      const [detail, runValue, history] = await Promise.all([
        getSession(session.id),
        getRun(created.run_id),
        loadEventHistory(session.id),
      ]);
      setSession(detail);
      setRun(runValue);
      setEvents(history);
      setPending([]);
      setError("");
      await refreshSessions();
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : "Invio fallito");
    }
  };

  const handleCompact = async (): Promise<string> => {
    if (!session) throw new Error("Sessione non disponibile.");
    const created = await compactContext(session.id);
    const [detail, runValue, history] = await Promise.all([
      getSession(session.id),
      getRun(created.run_id),
      loadEventHistory(session.id),
    ]);
    setSession(detail);
    setRun(runValue);
    setEvents(history);
    return created.run_id;
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

  const handleSessionModel = async (override: ModelOverride) => {
    if (!session) return;
    const previous = session.model_override;
    // Aggiornamento ottimistico: il selettore risponde subito, come il toggle di autonomia.
    setSession((current) => (current ? { ...current, model_override: override } : current));
    try {
      await setSessionModelOverride(session.id, override);
    } catch (reason) {
      setSession((current) => (current ? { ...current, model_override: previous } : current));
      setError(reason instanceof Error ? reason.message : "Cambio modello fallito");
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

  const resolveAction = async (body: { response?: string; cancel?: boolean }) => {
    if (!run) return;
    try {
      await submitAction(run.id, body);
      setActionRequest(null);
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : "Invio azione fallito");
    }
  };

  const selectSession = (id: string) => {
    loadSession(id).catch((reason: unknown) =>
      setError(reason instanceof Error ? reason.message : "Caricamento fallito"),
    );
    setView("control");
    setSidebarOpen(false);
  };

  const refreshRuntime = useCallback(
    () =>
      getRuntimeStatus()
        .then(setRuntime)
        .catch(() => undefined),
    [],
  );

  return {
    runtime,
    refreshRuntime,
    sessions,
    session,
    run,
    events: runEvents,
    traceEvents: events,
    approval,
    actionRequest,
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
    handleCompact,
    handleUpload,
    handleComposerUpload,
    handleRemovePending,
    handleDeleteFile,
    handleDeleteSession,
    handleRename,
    handleToggleAutoApprove,
    handleSessionModel,
    handleStop,
    handleStopSandbox,
    resolveApproval,
    resolveAction,
    selectSession,
  };
}

export type HarnessSession = ReturnType<typeof useHarnessSession>;
