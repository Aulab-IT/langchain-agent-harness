import { X } from "lucide-react";
import { ApprovalDialog } from "./components/shared/ApprovalDialog";
import { UserActionDialog } from "./components/shared/UserActionDialog";
import { ChatPanel } from "./components/chat/ChatPanel";
import { AppShell } from "./components/layout/AppShell";
import { InspectorDock } from "./components/layout/InspectorDock";
import {
  InspectorMobileTrigger,
  InspectorRail,
} from "./components/layout/InspectorRail";
import { Sidebar } from "./components/layout/Sidebar";
import { Topbar } from "./components/layout/Topbar";
import { SettingsView } from "./components/settings/SettingsView";
import { SkillsView } from "./components/skills/SkillsView";
import { SubagentsView } from "./components/subagents/SubagentsView";
import { ToolsView } from "./components/tools/ToolsView";
import { Spinner } from "./components/shared/PanelEmpty";
import { TraceView } from "./components/traces/TraceView";
import { TriggersView } from "./components/triggers/TriggersView";
import { ImproveView } from "./components/improve/ImproveView";
import { NotificationsProvider } from "./components/notifications/NotificationsContext";
import { NotificationToaster } from "./components/notifications/NotificationToaster";
import { useHarnessSession } from "./hooks/useHarnessSession";
import { useInspectorSheet, useInspectorTab } from "./hooks/useInspectorTab";

export default function App() {
  const harness = useHarnessSession();
  const { tab, selectTab } = useInspectorTab();
  const inspectorSheet = useInspectorSheet();

  const {
    runtime,
    sessions,
    session,
    run,
    events,
    traceEvents,
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
  } = harness;

  return (
    <NotificationsProvider>
    <AppShell
      sidebar={
        <Sidebar
          open={sidebarOpen}
          view={view}
          sessions={sessions}
          activeSessionId={session?.id ?? null}
          activeTitle={session?.title ?? null}
          search={search}
          onSearch={setSearch}
          onClose={() => setSidebarOpen(false)}
          onNew={handleNew}
          onSelect={selectSession}
          onView={setView}
        />
      }
      dock={
        runtime && session ? (
          <InspectorDock
            tab={tab}
            onTabChange={selectTab}
            sessionId={session.id}
            sessionTitle={session.title}
            modelOverride={session.model_override}
            messageCount={session.messages.filter((message) => message.role !== "system").length}
            files={session.files}
            skills={skillItems}
            tools={toolItems}
            usage={usage}
            contextWindow={runtime.context_window}
            runtime={runtime}
            sessionSandbox={session.sandbox}
            run={run}
            events={events}
            onUpload={handleUpload}
            onDeleteFile={handleDeleteFile}
            onStopSandbox={handleStopSandbox}
            onCompact={handleCompact}
          />
        ) : null
      }
    >
      <Topbar
        session={session}
        runtime={runtime}
        run={run}
        events={events}
        usage={usage}
        onMenu={() => setSidebarOpen(true)}
        onRename={handleRename}
        onDelete={handleDeleteSession}
      />

      <div className="flex min-h-0 flex-col overflow-hidden">
        {error ? (
          <div className="mx-4 mt-2 flex shrink-0 items-center justify-between gap-3 rounded-lg border border-danger/30 bg-danger/10 px-4 py-2.5 text-sm text-danger lg:mx-4">
            {error}
            <button
              type="button"
              aria-label="Chiudi errore"
              className="shrink-0 rounded p-1 hover:bg-danger/10"
              onClick={() => setError("")}
            >
              <X size={14} />
            </button>
          </div>
        ) : null}

        {!runtime || !session ? (
          <div className="flex min-h-0 flex-1 items-center justify-center overflow-hidden p-8">
            <Spinner label="Connessione control plane…" />
          </div>
        ) : view === "traces" ? (
          <div className="min-h-0 flex-1 overflow-y-auto p-4">
            <TraceView events={traceEvents} />
          </div>
        ) : view === "skills" ? (
          <div className="min-h-0 flex-1 overflow-y-auto p-4">
            <SkillsView />
          </div>
        ) : view === "subagents" ? (
          <div className="min-h-0 flex-1 overflow-y-auto p-4">
            <SubagentsView />
          </div>
        ) : view === "tools" ? (
          <div className="min-h-0 flex-1 overflow-y-auto p-4">
            <ToolsView />
          </div>
        ) : view === "triggers" ? (
          <div className="min-h-0 flex-1 overflow-y-auto p-4">
            <TriggersView
              runtime={runtime}
              onSchedulerChange={harness.refreshRuntime}
              onOpenSession={selectSession}
            />
          </div>
        ) : view === "improve" ? (
          <div className="min-h-0 flex-1 overflow-y-auto p-4">
            <ImproveView runtime={runtime} />
          </div>
        ) : view === "settings" ? (
          <div className="min-h-0 flex-1 overflow-y-auto p-4">
            <SettingsView runtime={runtime} onSaved={harness.refreshRuntime} />
          </div>
        ) : (
          <div className="min-h-0 flex-1 overflow-hidden">
            <div className="flex h-full min-h-0 flex-col gap-3 overflow-hidden p-3 xl:gap-3 xl:p-4">
            <ChatPanel
              className="min-h-0 flex-1"
            session={session}
            run={run}
            skills={runtime.skills}
            models={runtime.models}
            events={events}
            pending={pending}
            onSend={handleSend}
            onUpload={handleComposerUpload}
            onRemovePending={handleRemovePending}
            onTimeline={() => setView("traces")}
            onStop={handleStop}
            onToggleAutoApprove={handleToggleAutoApprove}
            onSessionModel={handleSessionModel}
          />
          <InspectorMobileTrigger onClick={inspectorSheet.openSheet} />
          {inspectorSheet.open ? (
            <>
              <button
                type="button"
                className="fixed inset-0 z-30 bg-black/50 xl:hidden"
                aria-label="Chiudi inspector"
                onClick={inspectorSheet.closeSheet}
              />
              <InspectorRail
                variant="sheet"
                tab={tab}
                onTabChange={selectTab}
                sessionId={session.id}
                files={session.files}
                skills={skillItems}
                tools={toolItems}
                usage={usage}
                contextWindow={runtime.context_window}
                runtime={runtime}
                sessionSandbox={session.sandbox}
                run={run}
                events={events}
                onUpload={handleUpload}
                onDeleteFile={handleDeleteFile}
                onStopSandbox={handleStopSandbox}
                onCompact={handleCompact}
                onClose={inspectorSheet.closeSheet}
              />
            </>
          ) : null}
            </div>
          </div>
        )}
      </div>

      {approval && run ? (
        <ApprovalDialog
          runId={run.id}
          payload={approval}
          onApprove={() => resolveApproval(true)}
          onReject={() => resolveApproval(false)}
          onCancel={handleStop}
        />
      ) : null}

      {actionRequest && run && session ? (
        <UserActionDialog
          runId={run.id}
          sessionId={session.id}
          payload={actionRequest}
          onSubmit={resolveAction}
          onCancel={() => resolveAction({ cancel: true })}
        />
      ) : null}
    </AppShell>
    <NotificationToaster />
    </NotificationsProvider>
  );
}
